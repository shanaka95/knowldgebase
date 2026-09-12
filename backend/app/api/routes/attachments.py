import logging
import uuid
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Annotated, Any, BinaryIO, Literal, cast
from urllib.parse import quote

from anyio import to_thread
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select
from starlette.background import BackgroundTask

from app.api.deps import AuthDep, SessionDep, WriteAuth
from app.api.serializers import to_attachment_public
from app.core.config import settings
from app.core.permissions import require_document, require_namespace
from app.models import (
    Attachment,
    AttachmentPublic,
    AttachmentsPublic,
    CleanupKind,
    CleanupTask,
    Message,
    User,
)
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])

CHUNK = 1024 * 1024


def _storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage | None = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Object storage not configured")
    return storage


def _check_access(
    session: Session,
    user: User,
    attachment: Attachment,
    min_role: Literal["viewer", "editor"],
) -> None:
    if attachment.document_id is not None:
        require_document(session, user, attachment.document_id, min_role)
    else:
        require_namespace(session, user, attachment.namespace_id, min_role)


@router.post("/", response_model=AttachmentPublic)
async def upload_attachment(
    request: Request,
    session: SessionDep,
    auth: WriteAuth,
    file: Annotated[UploadFile, File()],
    namespace_id: Annotated[uuid.UUID, Form()],
    document_id: Annotated[uuid.UUID | None, Form()] = None,
) -> Any:
    """Upload an image or file (multipart). Bound to a document when ``document_id`` is given."""
    if document_id is not None:
        document, _ = require_document(session, auth.user, document_id, "editor")
        if document.namespace_id != namespace_id:
            raise HTTPException(
                status_code=400, detail="Document is not in this namespace"
            )
    else:
        require_namespace(session, auth.user, namespace_id, "editor")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    spooled: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(max_size=8 * CHUNK)
    size = 0
    while chunk := await file.read(CHUNK):
        size += len(chunk)
        if size > max_bytes:
            spooled.close()
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit",
            )
        spooled.write(chunk)
    spooled.seek(0)

    filename = PurePosixPath(file.filename or "upload").name[:255] or "upload"
    suffix = PurePosixPath(filename).suffix.lower()[:16]
    attachment_id = uuid.uuid4()
    object_key = f"ns/{namespace_id}/{attachment_id}{suffix}"
    content_type = file.content_type or "application/octet-stream"

    storage = _storage(request)
    try:
        await to_thread.run_sync(
            storage.put, object_key, cast(BinaryIO, spooled), size, content_type
        )
    finally:
        spooled.close()

    attachment = Attachment(
        id=attachment_id,
        namespace_id=namespace_id,
        document_id=document_id,
        uploader_id=auth.user.id,
        filename=filename,
        content_type=content_type[:127],
        size=size,
        object_key=object_key,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return to_attachment_public(attachment)


@router.get("/", response_model=AttachmentsPublic)
def read_attachments(
    session: SessionDep,
    auth: AuthDep,
    namespace_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> Any:
    if document_id is not None:
        require_document(session, auth.user, document_id, "viewer")
        where = [Attachment.document_id == document_id]
    elif namespace_id is not None:
        require_namespace(session, auth.user, namespace_id, "viewer")
        where = [Attachment.namespace_id == namespace_id]
    else:
        raise HTTPException(
            status_code=422, detail="namespace_id or document_id is required"
        )
    rows = session.exec(
        select(Attachment).where(*where).order_by(col(Attachment.created_at).desc())
    ).all()
    data = [to_attachment_public(a) for a in rows]
    return AttachmentsPublic(data=data, count=len(data))


@router.get("/{attachment_id}", response_model=AttachmentPublic)
def read_attachment(
    session: SessionDep, auth: AuthDep, attachment_id: uuid.UUID
) -> Any:
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _check_access(session, auth.user, attachment, "viewer")
    return to_attachment_public(attachment)


@router.get("/{attachment_id}/download")
async def download_attachment(
    request: Request, session: SessionDep, auth: AuthDep, attachment_id: uuid.UUID
) -> StreamingResponse:
    """Stream the file bytes. Requires read access to the document/namespace."""
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _check_access(session, auth.user, attachment, "viewer")
    storage = _storage(request)
    try:
        obj = await to_thread.run_sync(storage.open, attachment.object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("attachment %s missing in storage: %s", attachment.id, exc)
        raise HTTPException(status_code=404, detail="File not found in storage")
    filename = quote(attachment.filename)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        "Cache-Control": "private, max-age=3600",
    }
    if obj.size:
        headers["Content-Length"] = str(obj.size)
    return StreamingResponse(
        obj.stream,
        media_type=attachment.content_type,
        headers=headers,
        background=BackgroundTask(obj.close),
    )


@router.delete("/{attachment_id}")
async def delete_attachment(
    request: Request, session: SessionDep, auth: WriteAuth, attachment_id: uuid.UUID
) -> Message:
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _check_access(session, auth.user, attachment, "editor")
    storage = _storage(request)
    try:
        await to_thread.run_sync(storage.delete, attachment.object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("deferring object delete for %s: %s", attachment.object_key, exc)
        session.add(
            CleanupTask(
                kind=CleanupKind.minio_object,
                payload={"object_key": attachment.object_key},
            )
        )
    session.delete(attachment)
    session.commit()
    return Message(message="Attachment deleted")
