"""Worker process: polls the Postgres queue and runs embedding jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import uuid
from collections.abc import Coroutine
from typing import Any

from app.core.config import settings
from app.models import CleanupKind, CleanupTask
from app.services.embeddings import EmbeddingClient
from app.services.llm import LLMClient
from app.services.storage import MinioStorage, ObjectStorage
from app.services.vectors import QdrantStore, VectorStore
from app.worker import healthfile, queue
from app.worker.imports import run_import
from app.worker.pipeline import PipelineDeps, run_job

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        *,
        vectors: VectorStore,
        storage: ObjectStorage | None,
        llm: LLMClient,
        embedder: EmbeddingClient,
        concurrency: int | None = None,
        import_concurrency: int | None = None,
        poll_interval: float | None = None,
        name: str | None = None,
    ) -> None:
        self.name = name or f"{socket.gethostname()}:{os.getpid()}"
        self.concurrency = concurrency or settings.WORKER_CONCURRENCY
        self.import_concurrency = import_concurrency or settings.IMPORT_CONCURRENCY
        self.poll_interval = poll_interval or settings.WORKER_POLL_INTERVAL_SECONDS
        self.vectors = vectors
        self.storage = storage
        self.deps = PipelineDeps(
            llm=llm,
            embedder=embedder,
            vectors=vectors,
            shutting_down=lambda: self.shutting_down,
        )
        self.running: dict[uuid.UUID, asyncio.Task[object]] = {}
        self.running_imports: dict[uuid.UUID, asyncio.Task[object]] = {}
        self.shutting_down = False
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ setup

    def request_stop(self) -> None:
        if not self.shutting_down:
            logger.info("shutdown requested")
        self.shutting_down = True
        self._stop.set()

    async def _ensure_collection(self) -> None:
        delay = 2.0
        while not self.shutting_down:
            try:
                await self.vectors.ensure_collection()
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("qdrant not ready (%s); retrying in %.0fs", exc, delay)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                delay = min(delay * 2, 30)

    # ------------------------------------------------------------- background

    async def _heartbeat_loop(self) -> None:
        while not self.shutting_down:
            try:
                await asyncio.to_thread(queue.heartbeat, self.name, list(self.running))
                healthfile.touch()
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat failed: %s", exc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.WORKER_HEARTBEAT_SECONDS
                )

    async def _cancel_watcher_loop(self) -> None:
        while not self.shutting_down:
            try:
                if self.running:
                    for job_id in await asyncio.to_thread(
                        queue.cancelled_job_ids, list(self.running)
                    ):
                        task = self.running.get(job_id)
                        if task is not None and not task.done():
                            logger.info(
                                "cancelling job %s (requested)", str(job_id)[:8]
                            )
                            task.cancel()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cancel watcher failed: %s", exc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    # ------------------------------------------------------------------- jobs

    def _spawn(self, job_id: uuid.UUID, coro: Coroutine[Any, Any, object]) -> None:
        task: asyncio.Task[object] = asyncio.ensure_future(coro)
        self.running[job_id] = task

        def _done(t: asyncio.Task[object]) -> None:
            self.running.pop(job_id, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error("job task crashed: %r", t.exception())

        task.add_done_callback(_done)

    def _spawn_import(self, job: queue.ImportSnapshot, storage: ObjectStorage) -> None:
        task: asyncio.Task[object] = asyncio.ensure_future(
            run_import(job, storage=storage)
        )
        self.running_imports[job.id] = task

        def _done(t: asyncio.Task[object]) -> None:
            self.running_imports.pop(job.id, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error("import task crashed: %r", t.exception())

        task.add_done_callback(_done)

    async def _process_cleanup_tasks(self, limit: int = 10) -> None:
        tasks = await asyncio.to_thread(queue.claim_cleanup_tasks, limit)
        for task in tasks:
            try:
                await self._run_cleanup(task)
                await asyncio.to_thread(queue.complete_cleanup_task, task.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup %s failed: %s", task.kind, exc)
                await asyncio.to_thread(queue.fail_cleanup_task, task.id, str(exc))

    async def _run_cleanup(self, task: CleanupTask) -> None:
        if task.kind == CleanupKind.qdrant_document:
            await self.vectors.delete_document(
                uuid.UUID(str(task.payload["document_id"]))
            )
        elif task.kind == CleanupKind.minio_object:
            if self.storage is None:
                raise RuntimeError("no object storage configured")
            await asyncio.to_thread(
                self.storage.delete, str(task.payload["object_key"])
            )
        else:  # pragma: no cover
            raise RuntimeError(f"unknown cleanup kind {task.kind}")

    async def tick(self) -> int:
        """One scheduler iteration; returns the number of jobs started."""
        await asyncio.to_thread(queue.reclaim_stale)
        await asyncio.to_thread(queue.reclaim_stale_imports)
        started = 0

        free = self.concurrency - len(self.running)
        if free > 0:
            for job in await asyncio.to_thread(queue.claim_jobs, self.name, free):
                logger.info(
                    "claimed job %s for doc %s v%s",
                    str(job.id)[:8],
                    str(job.document_id)[:8],
                    job.doc_version,
                )
                self._spawn(job.id, run_job(job, self.deps))
                started += 1

        # Imports are slow (a VLM call per page) but not CPU-bound here, so they
        # get their own small budget instead of competing for embedding slots.
        import_free = self.import_concurrency - len(self.running_imports)
        storage = self.storage
        if import_free > 0 and storage is not None:
            for import_job in await asyncio.to_thread(
                queue.claim_import_jobs, self.name, import_free
            ):
                logger.info(
                    "claimed import %s (%s)",
                    str(import_job.id)[:8],
                    import_job.filename,
                )
                self._spawn_import(import_job, storage)
                started += 1

        await self._process_cleanup_tasks()
        return started

    # -------------------------------------------------------------------- run

    async def run(self) -> None:
        logger.info(
            "worker %s starting (concurrency=%s, llm=%s, embeddings=%s)",
            self.name,
            self.concurrency,
            settings.LLM_MODEL,
            settings.EMBEDDING_MODEL,
        )
        await asyncio.to_thread(
            queue.register_worker,
            self.name,
            socket.gethostname(),
            os.getpid(),
            self.concurrency,
        )
        await self._ensure_collection()
        background = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._cancel_watcher_loop()),
        ]
        try:
            while not self.shutting_down:
                try:
                    await self.tick()
                except Exception as exc:  # noqa: BLE001
                    logger.error("scheduler tick failed: %s", exc, exc_info=True)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.poll_interval
                    )
        finally:
            # release in-flight jobs so another worker (or this one after restart) picks them up
            for task in list(self.running.values()):
                task.cancel()
            if self.running:
                await asyncio.gather(*self.running.values(), return_exceptions=True)
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(queue.unregister_worker, self.name)
            logger.info("worker %s stopped", self.name)


async def main() -> None:
    vectors = QdrantStore()
    storage: ObjectStorage | None
    try:
        storage = MinioStorage()
    except Exception as exc:  # noqa: BLE001
        logger.warning("object storage unavailable: %s", exc)
        storage = None
    llm = LLMClient()
    embedder = EmbeddingClient()
    worker = Worker(vectors=vectors, storage=storage, llm=llm, embedder=embedder)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)
    try:
        await worker.run()
    finally:
        await llm.close()
        await embedder.close()
        await vectors.close()
