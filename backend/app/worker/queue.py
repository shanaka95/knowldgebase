"""Postgres-backed job queue primitives.

Every function here is *synchronous* and opens its own short transaction over the
shared engine. The async worker invokes them via ``asyncio.to_thread`` so an
``asyncio`` cancellation can never interrupt a half-written transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, col, delete, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    Attachment,
    CleanupTask,
    Document,
    DocumentChunk,
    EmbeddingJob,
    EmbeddingStatus,
    ImportFile,
    ImportJob,
    ImportParser,
    ImportStatus,
    JobStage,
    JobStatus,
    WorkerHeartbeat,
)
from app.services.suggestions import store_suggestion
from app.services.versioning import detect_document_language, record_version
from app.worker.errors import JobCancelled, JobSuperseded
from app.worker.fallback_chunker import Chunk


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Worker registration / heartbeat
# ---------------------------------------------------------------------------


def register_worker(name: str, hostname: str, pid: int, concurrency: int) -> None:
    with Session(engine) as session:
        row = session.get(WorkerHeartbeat, name)
        now = _now()
        if row is None:
            row = WorkerHeartbeat(
                name=name,
                hostname=hostname,
                pid=pid,
                started_at=now,
                heartbeat_at=now,
                concurrency=concurrency,
            )
        else:
            row.started_at = now
            row.heartbeat_at = now
            row.concurrency = concurrency
            row.running_jobs = 0
        session.add(row)
        session.commit()


def heartbeat(name: str, running_job_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        now = _now()
        row = session.get(WorkerHeartbeat, name)
        if row is not None:
            row.heartbeat_at = now
            row.running_jobs = len(running_job_ids)
            session.add(row)
        if running_job_ids:
            session.connection().execute(
                text(
                    "UPDATE embeddingjob SET heartbeat_at = :now "
                    "WHERE id = ANY(:ids) AND locked_by = :name AND status = 'running'"
                ),
                {"now": now, "ids": running_job_ids, "name": name},
            )
        session.commit()


def unregister_worker(name: str) -> None:
    with Session(engine) as session:
        row = session.get(WorkerHeartbeat, name)
        if row is not None:
            session.delete(row)
            session.commit()


# ---------------------------------------------------------------------------
# Claiming / leases
# ---------------------------------------------------------------------------


def claim_jobs(worker_name: str, limit: int) -> list[EmbeddingJob]:
    """Atomically move up to ``limit`` due jobs to ``running`` for this worker."""
    if limit <= 0:
        return []
    with Session(engine) as session:
        rows = (
            session.connection()
            .execute(
                text(
                    """
                UPDATE embeddingjob SET
                    status = 'running',
                    stage = 'claimed',
                    locked_by = :worker,
                    locked_at = :now,
                    heartbeat_at = :now,
                    started_at = COALESCE(started_at, :now)
                WHERE id IN (
                    SELECT id FROM embeddingjob
                    WHERE status = 'queued'
                      AND run_after <= :now
                      AND cancel_requested = false
                    ORDER BY run_after, created_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
                """
                ),
                {"worker": worker_name, "now": _now(), "limit": limit},
            )
            .all()
        )
        session.commit()
        ids = [r[0] for r in rows]
        if not ids:
            return []
        jobs = session.exec(
            select(EmbeddingJob).where(col(EmbeddingJob.id).in_(ids))
        ).all()
        for job in jobs:
            session.expunge(job)
        return list(jobs)


def reclaim_stale(lease_seconds: int | None = None) -> int:
    """Return running jobs whose worker stopped heart-beating to the queue."""
    lease = lease_seconds or settings.WORKER_LEASE_SECONDS
    cutoff = _now() - timedelta(seconds=lease)
    with Session(engine) as session:
        stale = session.exec(
            select(EmbeddingJob).where(
                EmbeddingJob.status == JobStatus.running,
                col(EmbeddingJob.heartbeat_at) < cutoff,
            )
        ).all()
        for job in stale:
            job.attempts += 1
            job.locked_by = None
            job.locked_at = None
            job.error = "worker lease expired"
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.failed
                job.finished_at = _now()
                doc = session.get(Document, job.document_id)
                if doc is not None and doc.version == job.doc_version:
                    doc.embedding_status = EmbeddingStatus.failed
                    doc.embedding_error = f"attempt {job.attempts}/{job.max_attempts}: worker lease expired"
                    doc.embedding_attempts = job.attempts
                    session.add(doc)
            else:
                job.status = JobStatus.queued
                job.run_after = _now()
                job.stage = None
            session.add(job)
        session.commit()
        return len(stale)


def release_job(job_id: uuid.UUID) -> None:
    """Put an in-flight job back on the queue (graceful shutdown)."""
    with Session(engine) as session:
        job = session.get(EmbeddingJob, job_id)
        if job is not None and job.status == JobStatus.running:
            job.status = JobStatus.queued
            job.stage = None
            job.locked_by = None
            job.locked_at = None
            job.run_after = _now()
            session.add(job)
            doc = session.get(Document, job.document_id)
            if doc is not None and doc.version == job.doc_version:
                doc.embedding_status = EmbeddingStatus.pending
                session.add(doc)
            session.commit()


# ---------------------------------------------------------------------------
# Job state transitions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DocumentSnapshot:
    id: uuid.UUID
    namespace_id: uuid.UUID
    title: str
    content_html: str
    version: int


def load_document(document_id: uuid.UUID) -> DocumentSnapshot | None:
    with Session(engine) as session:
        doc = session.get(Document, document_id)
        if doc is None:
            return None
        return DocumentSnapshot(
            id=doc.id,
            namespace_id=doc.namespace_id,
            title=doc.title,
            content_html=doc.content_html,
            version=doc.version,
        )


@dataclass(slots=True)
class JobFlags:
    exists: bool
    cancel_requested: bool
    status: JobStatus | None
    document_version: int | None


def read_flags(job_id: uuid.UUID) -> JobFlags:
    with Session(engine) as session:
        job = session.get(EmbeddingJob, job_id)
        if job is None:
            return JobFlags(False, True, None, None)
        doc = session.get(Document, job.document_id)
        return JobFlags(
            True, job.cancel_requested, job.status, doc.version if doc else None
        )


def cancelled_job_ids(job_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Ids among ``job_ids`` whose row asks for cancellation or is no longer running."""
    if not job_ids:
        return []
    with Session(engine) as session:
        rows = session.exec(
            select(EmbeddingJob.id).where(
                col(EmbeddingJob.id).in_(job_ids),
                (col(EmbeddingJob.cancel_requested) == True)  # noqa: E712
                | (col(EmbeddingJob.status) != JobStatus.running),
            )
        ).all()
        return list(rows)


def set_stage(
    job_id: uuid.UUID,
    stage: JobStage,
    progress: int,
    doc_status: EmbeddingStatus | None = None,
) -> None:
    with Session(engine) as session:
        job = session.get(EmbeddingJob, job_id)
        if job is None:
            return
        job.stage = stage
        job.progress = progress
        job.heartbeat_at = _now()
        session.add(job)
        if doc_status is not None:
            doc = session.get(Document, job.document_id)
            # only the job for the current version may drive the document status
            if doc is not None and doc.version == job.doc_version:
                doc.embedding_status = doc_status
                session.add(doc)
        session.commit()


def finish_job(
    job_id: uuid.UUID,
    status: JobStatus,
    error: str | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    """Terminal state for cancelled/superseded jobs (document untouched)."""
    with Session(engine) as session:
        job = session.get(EmbeddingJob, job_id)
        if job is None:
            return
        job.status = status
        job.finished_at = _now()
        job.locked_by = None
        if error is not None:
            job.error = error[:2000]
        if stats:
            job.stats = {**(job.stats or {}), **stats}
        session.add(job)
        session.commit()


def retry_or_fail(
    job_id: uuid.UUID,
    error: str,
    stats: dict[str, Any] | None = None,
    *,
    force_fail: bool = False,
) -> JobStatus:
    """Re-queue with backoff while attempts remain, else fail the job and document."""
    with Session(engine) as session:
        job = session.get(EmbeddingJob, job_id)
        if job is None:
            return JobStatus.failed
        job.attempts += 1
        job.error = error[:2000]
        job.locked_by = None
        job.locked_at = None
        if stats:
            job.stats = {**(job.stats or {}), **stats}
        doc = session.get(Document, job.document_id)
        owns_document = doc is not None and doc.version == job.doc_version
        if not force_fail and job.attempts < job.max_attempts:
            backoff = settings.EMBEDDING_RETRY_BACKOFF_SECONDS * (
                2 ** (job.attempts - 1)
            )
            job.status = JobStatus.queued
            job.stage = None
            job.progress = 0
            job.run_after = _now() + timedelta(seconds=backoff)
            if owns_document and doc is not None:
                doc.embedding_status = EmbeddingStatus.pending
                doc.embedding_error = (
                    f"attempt {job.attempts}/{job.max_attempts}: {error}"[:2000]
                )
                doc.embedding_attempts = job.attempts
                session.add(doc)
            result = JobStatus.queued
        else:
            job.status = JobStatus.failed
            job.finished_at = _now()
            if owns_document and doc is not None:
                doc.embedding_status = EmbeddingStatus.failed
                doc.embedding_error = (
                    f"attempt {job.attempts}/{job.max_attempts}: {error}"[:2000]
                )
                doc.embedding_attempts = job.attempts
                session.add(doc)
            result = JobStatus.failed
        session.add(job)
        session.commit()
        return result


def commit_results(
    *,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    doc_version: int,
    summary: str | None,
    chunks: list[Chunk],
    chunking_method: str,
    stats: dict[str, Any],
) -> None:
    """Write chunks + document state + job success in ONE transaction.

    Re-checks the document version under ``FOR UPDATE`` so a concurrent update
    that slipped in after the embedding stage cannot be overwritten.
    """
    with Session(engine) as session:
        doc = session.exec(
            select(Document).where(Document.id == document_id).with_for_update()
        ).one_or_none()
        if doc is None or doc.version != doc_version:
            raise JobSuperseded()
        job = session.get(EmbeddingJob, job_id)
        if job is None or job.cancel_requested:
            raise JobCancelled()

        session.exec(
            delete(DocumentChunk).where(col(DocumentChunk.document_id) == document_id)
        )
        for index, chunk in enumerate(chunks):
            session.add(
                DocumentChunk(
                    document_id=document_id,
                    doc_version=doc_version,
                    chunk_index=index,
                    title=chunk.title[:300],
                    text=chunk.text,
                    char_count=chunk.char_count,
                )
            )

        now = _now()
        doc.summary = summary
        doc.embedding_status = EmbeddingStatus.ready
        doc.embedding_version = doc_version
        doc.chunk_count = len(chunks)
        doc.chunking_method = chunking_method
        doc.embedding_updated_at = now
        doc.embedding_error = None
        doc.embedding_attempts = job.attempts
        session.add(doc)

        job.status = JobStatus.succeeded
        job.stage = JobStage.done
        job.progress = 100
        job.finished_at = now
        job.locked_by = None
        job.chunk_count = len(chunks)
        job.chunking_method = chunking_method
        job.stats = {**(job.stats or {}), **stats}
        session.add(job)
        session.commit()


# ---------------------------------------------------------------------------
# Cleanup tasks (orphaned vectors / objects)
# ---------------------------------------------------------------------------


def claim_cleanup_tasks(limit: int) -> list[CleanupTask]:
    with Session(engine) as session:
        rows = (
            session.connection()
            .execute(
                text(
                    """
                UPDATE cleanuptask SET run_after = :later
                WHERE id IN (
                    SELECT id FROM cleanuptask
                    WHERE run_after <= :now
                    ORDER BY run_after
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
                """
                ),
                {"now": _now(), "later": _now() + timedelta(minutes=5), "limit": limit},
            )
            .all()
        )
        session.commit()
        ids = [r[0] for r in rows]
        if not ids:
            return []
        tasks = session.exec(
            select(CleanupTask).where(col(CleanupTask.id).in_(ids))
        ).all()
        for t in tasks:
            session.expunge(t)
        return list(tasks)


def complete_cleanup_task(task_id: uuid.UUID) -> None:
    with Session(engine) as session:
        task = session.get(CleanupTask, task_id)
        if task is not None:
            session.delete(task)
            session.commit()


def fail_cleanup_task(task_id: uuid.UUID, error: str, max_attempts: int = 10) -> None:
    with Session(engine) as session:
        task = session.get(CleanupTask, task_id)
        if task is None:
            return
        task.attempts += 1
        task.error = error[:1000]
        if task.attempts >= max_attempts:
            # give up but keep the row for inspection: park it far in the future
            task.run_after = _now() + timedelta(days=3650)
        else:
            task.run_after = _now() + timedelta(seconds=60 * task.attempts)
        session.add(task)
        session.commit()


def queue_depth() -> dict[str, int]:
    with Session(engine) as session:
        rows = (
            session.connection()
            .execute(text("SELECT status, count(*) FROM embeddingjob GROUP BY status"))
            .all()
        )
        return {str(r[0]): int(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# Import jobs (PDF / image -> document)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ImportPart:
    """One file of a multi-file import, detached from the session."""

    position: int
    filename: str
    content_type: str
    size: int
    object_key: str


@dataclass(slots=True)
class ImportSnapshot:
    """Detached copy of an import job, safe to use outside the session."""

    id: uuid.UUID
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None
    created_by: uuid.UUID | None
    title: str | None
    doc_type: str | None
    prompt: str | None
    filename: str
    content_type: str
    size: int
    object_key: str
    attempts: int
    max_attempts: int
    # Set when several uploads are being combined into one page, in order.
    # Empty for the ordinary one-file import, which uses ``object_key``.
    parts: list[ImportPart] = field(default_factory=list)


def claim_import_jobs(worker_name: str, limit: int) -> list[ImportSnapshot]:
    """Atomically claim up to ``limit`` due import jobs (same lease protocol)."""
    if limit <= 0:
        return []
    with Session(engine) as session:
        rows = (
            session.connection()
            .execute(
                text(
                    """
                UPDATE importjob SET
                    status = 'rendering',
                    locked_by = :worker,
                    locked_at = :now,
                    heartbeat_at = :now,
                    started_at = COALESCE(started_at, :now)
                WHERE id IN (
                    SELECT id FROM importjob
                    WHERE status = 'queued'
                      AND run_after <= :now
                      AND cancel_requested = false
                    ORDER BY run_after, created_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
                """
                ),
                {"worker": worker_name, "now": _now(), "limit": limit},
            )
            .all()
        )
        session.commit()
        ids = [r[0] for r in rows]
        if not ids:
            return []
        jobs = session.exec(select(ImportJob).where(col(ImportJob.id).in_(ids))).all()
        parts_by_job: dict[uuid.UUID, list[ImportPart]] = {}
        for row in session.exec(
            select(ImportFile)
            .where(col(ImportFile.job_id).in_(ids))
            .order_by(col(ImportFile.job_id), col(ImportFile.position))
        ).all():
            parts_by_job.setdefault(row.job_id, []).append(
                ImportPart(
                    position=row.position,
                    filename=row.filename,
                    content_type=row.content_type,
                    size=row.size,
                    object_key=row.object_key,
                )
            )
        return [
            ImportSnapshot(
                id=j.id,
                namespace_id=j.namespace_id,
                folder_id=j.folder_id,
                created_by=j.created_by,
                title=j.title,
                doc_type=j.doc_type,
                prompt=j.prompt,
                filename=j.filename,
                content_type=j.content_type,
                size=j.size,
                object_key=j.object_key,
                parts=parts_by_job.get(j.id, []),
                attempts=j.attempts,
                max_attempts=j.max_attempts,
            )
            for j in jobs
        ]


def import_heartbeat(worker_name: str, job_ids: list[uuid.UUID]) -> None:
    if not job_ids:
        return
    with Session(engine) as session:
        session.connection().execute(
            text(
                "UPDATE importjob SET heartbeat_at = :now "
                "WHERE id = ANY(:ids) AND locked_by = :worker"
            ),
            {"now": _now(), "ids": list(job_ids), "worker": worker_name},
        )
        session.commit()


def reclaim_stale_imports(lease_seconds: int | None = None) -> int:
    """Requeue import jobs whose worker died mid-parse."""
    lease = lease_seconds or settings.WORKER_LEASE_SECONDS
    cutoff = _now() - timedelta(seconds=lease)
    with Session(engine) as session:
        result = session.connection().execute(
            text(
                """
                UPDATE importjob SET
                    status = 'queued',
                    locked_by = NULL,
                    attempts = attempts + 1,
                    pages_done = 0,
                    error = 'worker lease expired',
                    run_after = :now
                WHERE status IN ('rendering', 'parsing', 'creating')
                  AND heartbeat_at < :cutoff
                """
            ),
            {"now": _now(), "cutoff": cutoff},
        )
        session.connection().execute(
            text(
                """
                UPDATE importjob SET status = 'failed', finished_at = :now
                WHERE status = 'queued'
                  AND attempts >= max_attempts
                  AND error = 'worker lease expired'
                """
            ),
            {"now": _now()},
        )
        session.commit()
        return int(result.rowcount or 0)


def import_cancel_requested(job_id: uuid.UUID) -> bool:
    with Session(engine) as session:
        row = (
            session.connection()
            .execute(
                text("SELECT cancel_requested FROM importjob WHERE id = :id"),
                {"id": job_id},
            )
            .first()
        )
        return bool(row[0]) if row else True  # a vanished job counts as cancelled


def set_import_progress(
    job_id: uuid.UUID,
    *,
    status: ImportStatus | None = None,
    pages_total: int | None = None,
    pages_done: int | None = None,
    parser: str | None = None,
) -> None:
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if pages_total is not None:
            job.pages_total = pages_total
        if pages_done is not None:
            job.pages_done = pages_done
        if parser is not None:
            job.parser = ImportParser(parser)
        job.heartbeat_at = _now()
        session.add(job)
        session.commit()


def finish_import(
    job_id: uuid.UUID,
    status: ImportStatus,
    *,
    document_id: uuid.UUID | None = None,
    attachment_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None:
            return
        job.status = status
        job.finished_at = _now()
        job.locked_by = None
        if document_id is not None:
            job.document_id = document_id
        if attachment_id is not None:
            job.attachment_id = attachment_id
        if error is not None:
            job.error = error[:2000]
        session.add(job)
        session.commit()


def retry_or_fail_import(job_id: uuid.UUID, error: str) -> ImportStatus:
    """Back off and requeue, or give up after ``max_attempts``."""
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None:
            return ImportStatus.failed
        job.attempts += 1
        job.error = error[:2000]
        job.locked_by = None
        job.pages_done = 0
        if job.attempts < job.max_attempts:
            backoff = settings.EMBEDDING_RETRY_BACKOFF_SECONDS * (
                2 ** (job.attempts - 1)
            )
            job.status = ImportStatus.queued
            job.run_after = _now() + timedelta(seconds=backoff)
        else:
            job.status = ImportStatus.failed
            job.finished_at = _now()
        session.add(job)
        session.commit()
        return job.status


def create_document_from_import(
    job: ImportSnapshot,
    *,
    title: str,
    content_html: str,
    content_text: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create the page and keep the upload as its source attachment.

    Returns ``(document_id, attachment_id)``. The attachment reuses the object
    already in MinIO, so nothing is copied and the original file stays
    downloadable from the page for good.
    """
    # One attachment per uploaded file, so a page combined from several scans
    # can still produce each original. The first is the page's source.
    uploads = job.parts or [
        ImportPart(
            position=0,
            filename=job.filename,
            content_type=job.content_type,
            size=job.size,
            object_key=job.object_key,
        )
    ]
    with Session(engine) as session:
        attachments = [
            Attachment(
                namespace_id=job.namespace_id,
                uploader_id=job.created_by,
                filename=part.filename,
                content_type=part.content_type,
                size=part.size,
                object_key=part.object_key,
                # Numbered as an original of version 1, which is the version
                # this import is about to create. That is what lets the page
                # offer all of them, in the order they were chosen, and say
                # which version they correspond to.
                source_order=position,
                source_version=1,
            )
            for position, part in enumerate(uploads)
        ]
        session.add_all(attachments)
        session.flush()
        attachment = attachments[0]

        # An import names a page after its own first heading, so a batch of
        # identical forms arrives as several pages called the same thing.
        # Nobody typed those names, so they step aside instead of failing.
        unique_title = crud.available_document_title(
            session,
            namespace_id=job.namespace_id,
            folder_id=job.folder_id,
            title=title[:300],
        )
        document = Document(
            namespace_id=job.namespace_id,
            folder_id=job.folder_id,
            title=unique_title,
            doc_type=job.doc_type,
            content_html=content_html,
            content_text=content_text,
            language=detect_document_language(unique_title, content_text),
            created_by=job.created_by,
            updated_by=job.created_by,
            source_attachment_id=attachment.id,
            embedding_status=EmbeddingStatus.pending,
        )
        session.add(document)
        session.flush()

        for a in attachments:
            a.document_id = document.id
        session.add_all(attachments)

        record_version(session, document, created_by=job.created_by)
        crud.enqueue_embedding_job(session=session, document=document, force=True)
        session.commit()
        return document.id, attachment.id


# ---------------------------------------------------------------------------
# Example searches
# ---------------------------------------------------------------------------


def document_owner(document_id: uuid.UUID) -> uuid.UUID | None:
    """Whose page this is - the person its example search belongs to."""
    with Session(engine) as session:
        document = session.get(Document, document_id)
        return document.created_by if document is not None else None


def save_search_suggestion(
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    namespace_id: uuid.UUID,
    question: str,
) -> None:
    with Session(engine) as session:
        store_suggestion(
            session,
            user_id=user_id,
            document_id=document_id,
            namespace_id=namespace_id,
            question=question,
        )
