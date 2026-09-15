"""Per-job context: stage reporting and cooperative cancellation checkpoints."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from app.models import EmbeddingJob, EmbeddingStatus, JobStage, UsageFeature
from app.services.usage import UsageMeter
from app.worker import queue
from app.worker.errors import JobCancelled, JobSuperseded


class JobContext:
    """One job's cancellation checkpoints, stage timings and metering.

    ``EmbeddingJob`` has no owner column - the page does. Indexing is real
    money (chunking and summarising are chat calls, and every chunk is
    embedded), so the owner is resolved once when the job starts rather than
    the work going uncounted. A page whose author has been deleted belongs to
    nobody and the meter simply records nothing.
    """

    def __init__(self, job: EmbeddingJob, user_id: uuid.UUID | None = None) -> None:
        self.job_id: uuid.UUID = job.id
        self.document_id: uuid.UUID = job.document_id
        self.doc_version: int = job.doc_version
        self.attempts: int = job.attempts
        self.stats: dict[str, Any] = {}
        self.meter = UsageMeter(user_id=user_id, feature=UsageFeature.indexing)
        self._stage_started = time.perf_counter()
        self._stage: JobStage | None = None

    async def checkpoint(self) -> None:
        """Re-read the job row; raise if the job was cancelled or superseded."""
        flags = await asyncio.to_thread(queue.read_flags, self.job_id)
        if not flags.exists or flags.cancel_requested:
            raise JobCancelled()
        if flags.status != "running":
            raise JobCancelled()
        if flags.document_version is None:
            raise JobCancelled()  # document deleted
        if flags.document_version != self.doc_version:
            raise JobSuperseded()

    async def set_stage(
        self,
        stage: JobStage,
        progress: int,
        doc_status: EmbeddingStatus | None = None,
    ) -> None:
        self._record_stage_time()
        self._stage = stage
        await asyncio.to_thread(
            queue.set_stage, self.job_id, stage, progress, doc_status
        )

    async def set_progress(self, progress: int) -> None:
        if self._stage is None:
            return
        await asyncio.to_thread(
            queue.set_stage, self.job_id, self._stage, progress, None
        )

    def _record_stage_time(self) -> None:
        now = time.perf_counter()
        if self._stage is not None:
            ms = round((now - self._stage_started) * 1000)
            self.stats.setdefault("stage_ms", {})[str(self._stage)] = ms
        self._stage_started = now

    def finalize_stats(self) -> dict[str, Any]:
        self._record_stage_time()
        return self.stats
