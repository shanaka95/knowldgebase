"""Helpers that turn ORM rows into the ``*Public`` response models."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.permissions import get_document_role, get_namespace_role, has_min_role
from app.models import (
    Attachment,
    AttachmentPublic,
    Document,
    DocumentPublic,
    DocumentSummaryPublic,
    EmbeddingJob,
    EmbeddingJobPublic,
    ImportJob,
    ImportJobPublic,
    Namespace,
    NamespaceMember,
    NamespacePublic,
    NamespaceRole,
    ShareRole,
    User,
    UserRef,
)


def user_ref(user: User | None) -> UserRef | None:
    if user is None:
        return None
    return UserRef(id=user.id, email=user.email, full_name=user.full_name)


def user_refs_by_id(
    session: Session, ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    users = session.exec(select(User).where(col(User.id).in_(wanted))).all()
    return {u.id: UserRef(id=u.id, email=u.email, full_name=u.full_name) for u in users}


def to_namespace_public(
    session: Session,
    user: User,
    namespace: Namespace,
    role: NamespaceRole | None = None,
) -> NamespacePublic:
    if role is None:
        role = get_namespace_role(session, user, namespace)
    document_count = session.exec(
        select(func.count())
        .select_from(Document)
        .where(Document.namespace_id == namespace.id)
    ).one()
    member_count = session.exec(
        select(func.count())
        .select_from(NamespaceMember)
        .where(NamespaceMember.namespace_id == namespace.id)
    ).one()
    owner = session.get(User, namespace.owner_id)
    return NamespacePublic(
        id=namespace.id,
        name=namespace.name,
        slug=namespace.slug,
        description=namespace.description,
        icon=namespace.icon,
        color=namespace.color,
        owner_id=namespace.owner_id,
        owner=user_ref(owner),
        my_role=role,
        document_count=document_count,
        member_count=member_count + 1,  # owner counts as a member
        created_at=namespace.created_at,
        updated_at=namespace.updated_at,
    )


def role_for_documents(
    session: Session, user: User, namespace: Namespace | None
) -> ShareRole | None:
    """Document role implied by the namespace role (None if no namespace access)."""
    if namespace is None:
        return None
    ns_role = get_namespace_role(session, user, namespace)
    if ns_role is None:
        return None
    return ShareRole.editor if has_min_role(ns_role, "editor") else ShareRole.viewer


def to_document_summary(
    document: Document, my_role: ShareRole | None
) -> DocumentSummaryPublic:
    return DocumentSummaryPublic(
        id=document.id,
        namespace_id=document.namespace_id,
        namespace_slug=document.namespace.slug if document.namespace else None,
        folder_id=document.folder_id,
        title=document.title,
        version=document.version,
        created_by=document.created_by,
        updated_by=document.updated_by,
        created_at=document.created_at,
        updated_at=document.updated_at,
        embedding_status=document.embedding_status,
        embedding_version=document.embedding_version,
        embedding_error=document.embedding_error,
        embedding_attempts=document.embedding_attempts,
        chunk_count=document.chunk_count,
        chunking_method=document.chunking_method,
        embedding_updated_at=document.embedding_updated_at,
        is_stale=document.embedding_version != document.version,
        my_role=my_role,
        source_attachment_id=document.source_attachment_id,
    )


def to_document_public(
    session: Session, user: User, document: Document, my_role: ShareRole | None = None
) -> DocumentPublic:
    if my_role is None:
        my_role = get_document_role(session, user, document)
    refs = user_refs_by_id(session, [document.created_by, document.updated_by])
    summary = to_document_summary(document, my_role)
    source: AttachmentPublic | None = None
    if document.source_attachment_id is not None:
        # The original PDF/image an imported page was built from stays available.
        attachment = session.get(Attachment, document.source_attachment_id)
        if attachment is not None:
            source = to_attachment_public(attachment)
    return DocumentPublic(
        **summary.model_dump(),
        content_html=document.content_html,
        content_text=document.content_text,
        summary=document.summary,
        updated_by_user=refs.get(document.updated_by) if document.updated_by else None,
        created_by_user=refs.get(document.created_by) if document.created_by else None,
        source_attachment=source,
    )


def to_job_public(job: EmbeddingJob) -> EmbeddingJobPublic:
    return EmbeddingJobPublic.model_validate(job)


def attachment_download_url(attachment_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/attachments/{attachment_id}/download"


def to_attachment_public(attachment: Attachment) -> AttachmentPublic:
    return AttachmentPublic(
        id=attachment.id,
        namespace_id=attachment.namespace_id,
        document_id=attachment.document_id,
        uploader_id=attachment.uploader_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size=attachment.size,
        download_url=attachment_download_url(attachment.id),
        created_at=attachment.created_at,
    )


def to_import_job_public(session: Session, job: ImportJob) -> ImportJobPublic:
    namespace = session.get(Namespace, job.namespace_id)
    return ImportJobPublic(
        id=job.id,
        namespace_id=job.namespace_id,
        namespace_slug=namespace.slug if namespace else None,
        folder_id=job.folder_id,
        document_id=job.document_id,
        attachment_id=job.attachment_id,
        title=job.title,
        prompt=job.prompt,
        filename=job.filename,
        content_type=job.content_type,
        size=job.size,
        status=job.status,
        parser=job.parser,
        pages_total=job.pages_total,
        pages_done=job.pages_done,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )
