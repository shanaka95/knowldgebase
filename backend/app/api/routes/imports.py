"""Import PDFs and images as pages.

The upload is stored in object storage and queued; the background worker renders
each page, parses it with the MinerU vision model (falling back to the general
multimodal LLM) and creates the page. The original file is kept and attached to
the created page so it can be opened later.
"""

import uuid
from dataclasses import dataclass
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
    ImportFile,
    ImportJob,
    ImportJobPublic,
    ImportJobsPublic,
    ImportStatus,
    Message,
    User,
    clean_document_type,
)
from app.services import parsing
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/imports", tags=["imports"])

CHUNK = 1024 * 1024
# A person choosing files in a dialog, not a bulk loader. Keeping this modest
# bounds how long one request holds a connection while it streams uploads.
MAX_BATCH_FILES = 20
SUPPORTED_LABEL = "PDF, PNG, JPEG, WebP, GIF, BMP or TIFF"


def _get_job(session: Session, user: User, import_id: uuid.UUID) -> ImportJob:
    job = session.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    if not user.is_superuser and job.created_by != user.id:
        # hide existence from other users
        raise HTTPException(status_code=404, detail="Import not found")
    return job


@dataclass(slots=True)
class StoredUpload:
    """An upload that has already been read, checked and put in object storage."""

    filename: str
    content_type: str
    size: int
    object_key: str


def _check_destination(
    session: Session, user: User, namespace_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    require_namespace(session, user, namespace_id, "editor")
    if folder_id is not None:
        folder, _, _ = require_folder(session, user, folder_id, "editor")
        if folder.namespace_id != namespace_id:
            raise HTTPException(
                status_code=400, detail="Folder is not in this namespace"
            )


async def _store(
    storage: ObjectStorage, file: UploadFile, key_prefix: str
) -> StoredUpload:
    """Validate one upload and stream it into object storage.

    Streamed through a spooled temporary file rather than read into memory: a
    hundred-page scan is large, and several of them arrive at once now.
    """
    filename = PurePosixPath(file.filename or "upload").name[:255] or "upload"
    content_type = file.content_type or "application/octet-stream"
    if not parsing.is_supported(content_type, filename):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type {content_type!r} for {filename!r}. "
                f"Upload a {SUPPORTED_LABEL} file."
            ),
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
                detail=(
                    f"{filename} exceeds the {settings.MAX_IMPORT_SIZE_MB} MB limit"
                ),
            )
        spooled.write(chunk)
    spooled.seek(0)

    suffix = PurePosixPath(filename).suffix.lower()[:16]
    object_key = f"{key_prefix}{suffix}"
    try:
        await to_thread.run_sync(
            storage.put, object_key, cast(BinaryIO, spooled), size, content_type
        )
    finally:
        spooled.close()
    return StoredUpload(filename, content_type[:127], size, object_key)


@router.post("/", response_model=ImportJobPublic)
async def create_import(
    session: SessionDep,
    auth: WriteAuth,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    namespace_id: Annotated[uuid.UUID, Form()],
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    doc_type: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
) -> Any:
    """Upload one PDF or image and queue it to be turned into a page.

    Leave `title` empty to have the page named after its own first heading,
    which is almost always better than the filename. Use `/imports/batch` for
    several files at once.
    """
    _check_destination(session, auth.user, namespace_id, folder_id)

    job_id = uuid.uuid4()
    stored = await _store(storage, file, f"imports/{job_id}")

    job = ImportJob(
        id=job_id,
        namespace_id=namespace_id,
        folder_id=folder_id,
        created_by=auth.user.id,
        # Left as given: when it is empty the worker promotes the document's own
        # heading to the title, and only falls back to the filename if there is
        # none. Defaulting here would hide that heading.
        title=((title or "").strip()[:300] or None),
        doc_type=clean_document_type(doc_type),
        prompt=(prompt or "").strip() or None,
        filename=stored.filename,
        content_type=stored.content_type,
        size=stored.size,
        object_key=stored.object_key,
        max_attempts=3,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_import_job_public(session, job)


@router.post("/batch", response_model=ImportJobsPublic)
async def create_imports(
    session: SessionDep,
    auth: WriteAuth,
    storage: StorageDep,
    files: Annotated[list[UploadFile], File()],
    namespace_id: Annotated[uuid.UUID, Form()],
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    doc_type: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
    combine: Annotated[bool, Form()] = False,
) -> Any:
    """Upload several files at once, into the same space and folder.

    By default each file becomes its own page, named after its own first
    heading. With `combine=true` the files become a single page instead, in the
    order they were sent - which is what you want for a document that arrived as
    a set of scans, or a report split across several files.

    `title` applies only when combining, or when there is exactly one file;
    giving several files their own page and one shared title would produce a
    list of identically named pages.
    """
    if not files:
        raise HTTPException(status_code=422, detail="Attach at least one file")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Up to {MAX_BATCH_FILES} files at a time",
        )
    _check_destination(session, auth.user, namespace_id, folder_id)

    clean_title = (title or "").strip()[:300] or None
    clean_prompt = (prompt or "").strip() or None
    # Unlike the title, the type applies to every page in the batch: a set of
    # scans chosen together is a set of the same kind of thing.
    kind = clean_document_type(doc_type)

    if combine and len(files) > 1:
        job_id = uuid.uuid4()
        stored = [
            await _store(storage, f, f"imports/{job_id}-{i}")
            for i, f in enumerate(files)
        ]
        total = sum(s.size for s in stored)
        job = ImportJob(
            id=job_id,
            namespace_id=namespace_id,
            folder_id=folder_id,
            created_by=auth.user.id,
            title=clean_title,
            doc_type=kind,
            prompt=clean_prompt,
            # A label for the list, since there is no single filename any more.
            filename=f"{stored[0].filename} +{len(stored) - 1} more"[:255],
            content_type=stored[0].content_type,
            size=total,
            # The first part doubles as the job's own object so that anything
            # reading a job the old way still finds a real file.
            object_key=stored[0].object_key,
            max_attempts=3,
        )
        session.add(job)
        session.flush()
        for position, part in enumerate(stored):
            session.add(
                ImportFile(
                    job_id=job.id,
                    position=position,
                    filename=part.filename,
                    content_type=part.content_type,
                    size=part.size,
                    object_key=part.object_key,
                )
            )
        session.commit()
        session.refresh(job)
        return ImportJobsPublic(data=[to_import_job_public(session, job)], count=1)

    jobs: list[ImportJob] = []
    for file in files:
        job_id = uuid.uuid4()
        stored_one = await _store(storage, file, f"imports/{job_id}")
        jobs.append(
            ImportJob(
                id=job_id,
                namespace_id=namespace_id,
                folder_id=folder_id,
                created_by=auth.user.id,
                title=clean_title if len(files) == 1 else None,
                doc_type=kind,
                prompt=clean_prompt,
                filename=stored_one.filename,
                content_type=stored_one.content_type,
                size=stored_one.size,
                object_key=stored_one.object_key,
                max_attempts=3,
            )
        )
    session.add_all(jobs)
    session.commit()
    for job in jobs:
        session.refresh(job)
    data = [to_import_job_public(session, job) for job in jobs]
    return ImportJobsPublic(data=data, count=len(data))


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
