"""Helpers that turn ORM rows into the ``*Public`` response models."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.permissions import (
    accessible_documents_filter,
    get_document_role,
    get_namespace_role,
    has_min_role,
    held_namespace_role,
)
from app.models import (
    Attachment,
    AttachmentPublic,
    Document,
    DocumentPublic,
    DocumentSummaryPublic,
    EmbeddingJob,
    EmbeddingJobPublic,
    ImportFile,
    ImportJob,
    ImportJobPublic,
    Namespace,
    NamespaceMember,
    NamespacePublic,
    NamespaceRole,
    ShareRole,
    User,
    UserGroup,
    UserPublic,
    UserRef,
)
from app.services import quota


def to_user_public(
    session: Session,
    user: User,
    *,
    groups: dict[uuid.UUID, UserGroup] | None = None,
    used: dict[uuid.UUID, int] | None = None,
) -> UserPublic:
    """An account as its owner sees it: resolved numbers, no provenance.

    The limit columns are nullable now, and a nullable column must never reach
    the wire - `UserPublic` declares them as plain ints, so serialising the raw
    row would raise for every account that inherits. Resolving here is also what
    keeps groups invisible: the reader is told their number and cannot tell
    whether it came from their account, their group or the defaults.

    Every place that builds a `UserPublic` goes through this. `model_validate`
    on a `User` is now a bug.
    """
    limits = quota.resolve_limits(session, user, groups=groups)
    return UserPublic(
        **user.model_dump(
            include={
                "email",
                "is_active",
                "is_superuser",
                "full_name",
                "id",
                "created_at",
                "email_verified_at",
            }
        ),
        max_pages=limits.max_pages,
        pages_used=(
            used[user.id] if used is not None else quota.pages_used(session, user.id)
        ),
        max_shares_per_document=limits.max_shares_per_document,
        max_members_per_space=limits.max_members_per_space,
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
        # The relationship, not the administrator override: a space nobody
        # shared with you is not a space you are an admin of.
        role = held_namespace_role(session, user, namespace)

    # Counts are scoped to the caller. Somebody who was shared a single page can
    # see the space around it, and must not learn from these numbers how much
    # else is in there or how many people it is shared with.
    document_count = session.exec(
        select(func.count())
        .select_from(Document)
        .where(
            Document.namespace_id == namespace.id,
            accessible_documents_filter(session, user),
        )
    ).one()
    member_count: int | None = None
    if role is not None:
        member_count = (
            session.exec(
                select(func.count())
                .select_from(NamespaceMember)
                .where(NamespaceMember.namespace_id == namespace.id)
            ).one()
            + 1  # the owner counts as a member
        )
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
        # Said plainly rather than left for the interface to work out, which it
        # could only do by comparing ids it would otherwise not need.
        shared_with_you=namespace.owner_id != user.id,
        document_count=document_count,
        member_count=member_count,
        created_at=namespace.created_at,
        updated_at=namespace.updated_at,
    )


def to_namespace_publics(
    session: Session,
    user: User,
    namespaces: Sequence[Namespace],
) -> list[NamespacePublic]:
    """Serialise a list of spaces in a fixed number of queries.

    ``to_namespace_public`` runs three queries per space - page count, member
    count, owner - which is fine for one space and is 3N queries for a list.
    Somebody with forty spaces was paying a hundred and twenty round trips to
    open the space switcher. These are the same numbers, gathered once.
    """
    if not namespaces:
        return []

    ids = [ns.id for ns in namespaces]

    # The role each space is labelled with is the one actually held here. An
    # administrator is not a member of everybody's spaces, and saying so put an
    # ADMIN badge on spaces that had never been shared with them.
    memberships = session.exec(
        select(NamespaceMember).where(
            col(NamespaceMember.namespace_id).in_(ids),
            NamespaceMember.user_id == user.id,
        )
    ).all()
    by_namespace = {m.namespace_id: m.role for m in memberships}
    roles: dict[uuid.UUID, NamespaceRole | None] = {
        ns.id: (
            NamespaceRole.admin if ns.owner_id == user.id else by_namespace.get(ns.id)
        )
        for ns in namespaces
    }

    # Page counts stay scoped to the caller, exactly as the single-space path
    # does: a share on one page must not reveal how much else is in the space.
    page_counts: dict[uuid.UUID, int] = dict(
        session.exec(
            select(Document.namespace_id, func.count())
            .where(
                col(Document.namespace_id).in_(ids),
                accessible_documents_filter(session, user),
            )
            .group_by(col(Document.namespace_id))
        ).all()
    )

    member_counts: dict[uuid.UUID, int] = dict(
        session.exec(
            select(NamespaceMember.namespace_id, func.count())
            .where(col(NamespaceMember.namespace_id).in_(ids))
            .group_by(col(NamespaceMember.namespace_id))
        ).all()
    )

    owners = user_refs_by_id(session, [ns.owner_id for ns in namespaces])

    return [
        NamespacePublic(
            id=ns.id,
            name=ns.name,
            slug=ns.slug,
            description=ns.description,
            icon=ns.icon,
            color=ns.color,
            owner_id=ns.owner_id,
            owner=owners.get(ns.owner_id),
            my_role=roles.get(ns.id),
            shared_with_you=ns.owner_id != user.id,
            document_count=page_counts.get(ns.id, 0),
            # None for somebody who only holds shares on individual pages: they
            # are not a member, so the size of the membership is not theirs.
            member_count=(
                member_counts.get(ns.id, 0) + 1
                if roles.get(ns.id) is not None
                else None
            ),
            created_at=ns.created_at,
            updated_at=ns.updated_at,
        )
        for ns in namespaces
    ]


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
        namespace_name=document.namespace.name if document.namespace else None,
        folder_id=document.folder_id,
        title=document.title,
        doc_type=document.doc_type,
        # Without this the interface cannot tell a published page from an
        # unpublished one, and the "share by link" switch reads as off on a page
        # whose link is live.
        public_slug=document.public_slug,
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
    # Every file the page was imported from, in the order they were uploaded.
    # A page combined from eight scans used to offer the first one and keep the
    # other seven to itself.
    originals = [
        to_attachment_public(a)
        for a in session.exec(
            select(Attachment)
            .where(
                Attachment.document_id == document.id,
                col(Attachment.source_order).is_not(None),
            )
            .order_by(col(Attachment.source_order))
        ).all()
    ]
    if not originals and document.source_attachment_id is not None:
        # Imported before originals were numbered, and not covered by the
        # backfill: the page still has the one file it always showed.
        attachment = session.get(Attachment, document.source_attachment_id)
        if attachment is not None:
            originals = [to_attachment_public(attachment)]
    return DocumentPublic(
        **summary.model_dump(),
        content_html=document.content_html,
        content_text=document.content_text,
        summary=document.summary,
        language=document.language,
        updated_by_user=refs.get(document.updated_by) if document.updated_by else None,
        created_by_user=refs.get(document.created_by) if document.created_by else None,
        source_attachment=originals[0] if originals else None,
        source_attachments=originals,
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
        source_order=attachment.source_order,
        source_version=attachment.source_version,
        created_at=attachment.created_at,
    )


def to_import_job_public(session: Session, job: ImportJob) -> ImportJobPublic:
    namespace = session.get(Namespace, job.namespace_id)
    parts = session.exec(
        select(ImportFile)
        .where(ImportFile.job_id == job.id)
        .order_by(col(ImportFile.position))
    ).all()
    filenames = [f.filename for f in parts] or [job.filename]
    return ImportJobPublic(
        id=job.id,
        namespace_id=job.namespace_id,
        namespace_slug=namespace.slug if namespace else None,
        folder_id=job.folder_id,
        document_id=job.document_id,
        attachment_id=job.attachment_id,
        title=job.title,
        doc_type=job.doc_type,
        prompt=job.prompt,
        filename=job.filename,
        content_type=job.content_type,
        size=job.size,
        file_count=len(filenames),
        filenames=filenames,
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
