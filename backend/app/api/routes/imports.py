"""Import PDFs and images as pages.

The upload is stored in object storage and queued; the background worker renders
each page, parses it with the MinerU vision model (falling back to the general
multimodal LLM) and creates the page. The original file is kept and attached to
the created page so it can be opened later.
"""

import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Annotated, Any, BinaryIO, cast

from anyio import to_thread
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session, col, func, select

from app.api.deps import AuthDep, SessionDep, StorageDep, WriteAuth
from app.api.serializers import to_import_job_public
from app.core.config import settings
from app.core.permissions import require_folder, require_namespace
from app.models import (
    CleanupKind,
    CleanupTask,
    ImportJob,
    ImportJobPublic,
    ImportJobsPublic,
    ImportStatus,
    Message,
    User,
)
from app.services import parsing

router = APIRouter(prefix="/imports", tags=["imports"])

CHUNK = 1024 * 1024
SUPPORTED_LABEL = "PDF, PNG, JPEG, WebP, GIF, BMP or TIFF"


def _get_job(session: Session, user: User, import_id: uuid.UUID) -> ImportJob:
    job = session.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    if not user.is_superuser and job.created_by != user.id:
        # hide existence from other users
        raise HTTPException(status_code=404, detail="Import not found")
    return job


@router.post("/", response_model=ImportJobPublic)
async def create_import(
    session: SessionDep,
    auth: WriteAuth,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    namespace_id: Annotated[uuid.UUID, Form()],
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
) -> Any:
    """Upload a PDF or image and queue it to be turned into a page."""
    require_namespace(session, auth.user, namespace_id, "editor")
    if folder_id is not None:
        folder, _, _ = require_folder(session, auth.user, folder_id, "editor")
        if folder.namespace_id != namespace_id:
            raise HTTPException(
                status_code=400, detail="Folder is not in this namespace"
            )

    filename = PurePosixPath(file.filename or "upload").name[:255] or "upload"
    content_type = file.content_type or "application/octet-stream"
    if not parsing.is_supported(content_type, filename):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {content_type!r}. Upload a {SUPPORTED_LABEL} file.",
        )

    max_bytes = settings.MAX_IMPORT_SIZE_MB * 1024 * 1024
    spooled: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(max_size=8 * CHUNK)
    size = 0
    while chunk := await file.read(CHUNK):
        size += len(chunk)
        if size > max_bytes:
            spooled.close()
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {settings.MAX_IMPORT_SIZE_MB} MB limit",
            )
        spooled.write(chunk)
    spooled.seek(0)

    job_id = uuid.uuid4()
    suffix = PurePosixPath(filename).suffix.lower()[:16]
    object_key = f"imports/{job_id}{suffix}"
    try:
        await to_thread.run_sync(
            storage.put, object_key, cast(BinaryIO, spooled), size, content_type
        )
    finally:
        spooled.close()

    job = ImportJob(
        id=job_id,
        namespace_id=namespace_id,
        folder_id=folder_id,
        created_by=auth.user.id,
        # Left as given: when it is empty the worker promotes the document's own
        # heading to the title, and only falls back to the filename if there is
        # none. Defaulting here would hide that heading.
        title=((title or "").strip()[:300] or None),
        prompt=(prompt or "").strip() or None,
        filename=filename,
        content_type=content_type[:127],
        size=size,
        object_key=object_key,
        max_attempts=3,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_import_job_public(session, job)


@router.get("/", response_model=ImportJobsPublic)
def read_imports(
    session: SessionDep,
    auth: AuthDep,
    namespace_id: uuid.UUID | None = None,
    status: ImportStatus | None = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
) -> Any:
    """List your own imports (superusers see every import)."""
    where: list[Any] = []
    if not auth.user.is_superuser:
        where.append(ImportJob.created_by == auth.user.id)
    if namespace_id is not None:
        where.append(ImportJob.namespace_id == namespace_id)
    if status is not None:
        where.append(ImportJob.status == status)

    count = session.exec(
        select(func.count()).select_from(ImportJob).where(*where)
    ).one()
    rows = session.exec(
        select(ImportJob)
        .where(*where)
        .order_by(col(ImportJob.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return ImportJobsPublic(
        data=[to_import_job_public(session, j) for j in rows], count=count
    )


@router.get("/{import_id}", response_model=ImportJobPublic)
def read_import(session: SessionDep, auth: AuthDep, import_id: uuid.UUID) -> Any:
    return to_import_job_public(session, _get_job(session, auth.user, import_id))


@router.post("/{import_id}/retry", response_model=ImportJobPublic)
def retry_import(session: SessionDep, auth: WriteAuth, import_id: uuid.UUID) -> Any:
    """Queue a failed or cancelled import again from the start."""
    job = _get_job(session, auth.user, import_id)
    if job.status not in (ImportStatus.failed, ImportStatus.cancelled):
        raise HTTPException(
            status_code=409,
            detail=f"Only failed or cancelled imports can be retried (this one is {job.status})",
        )
    job.status = ImportStatus.queued
    job.attempts = 0
    job.pages_done = 0
    job.error = None
    job.parser = None
    job.run_after = datetime.now(UTC)
    job.cancel_requested = False
    job.locked_by = None
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_import_job_public(session, job)


@router.post("/{import_id}/cancel", response_model=ImportJobPublic)
def cancel_import(session: SessionDep, auth: WriteAuth, import_id: uuid.UUID) -> Any:
    """Ask the worker to stop; a job that has not started yet is cancelled outright."""
    job = _get_job(session, auth.user, import_id)
    if job.status in (ImportStatus.done, ImportStatus.cancelled):
        return to_import_job_public(session, job)
    job.cancel_requested = True
    if job.status == ImportStatus.queued:
        job.status = ImportStatus.cancelled
        job.finished_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_import_job_public(session, job)


@router.delete("/{import_id}")
def delete_import(
    session: SessionDep, auth: WriteAuth, import_id: uuid.UUID
) -> Message:
    job = _get_job(session, auth.user, import_id)
    if job.attachment_id is None:
        # Nothing references the upload any more, so the object can go too. When
        # an attachment exists it owns the object and must keep it.
        session.add(
            CleanupTask(
                kind=CleanupKind.minio_object,
                payload={"object_key": job.object_key},
            )
        )
    session.delete(job)
    session.commit()
    return Message(message="Import deleted")
