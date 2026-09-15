import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, func, select

from app import crud
from app.api.deps import (
    AuthDep,
    SessionDep,
    StorageDep,
    WriteAuth,
    get_current_active_superuser,
)
from app.api.serializers import (
    role_for_documents,
    to_document_public,
    to_document_summary,
    to_job_public,
    to_namespace_publics,
    user_ref,
    user_refs_by_id,
)
from app.core.config import settings
from app.core.content import html_to_text, normalize_content
from app.core.permissions import (
    accessible_documents_filter,
    can_delete_document,
    can_share_document,
    get_document_role,
    get_namespace_role,
    require_document,
    require_namespace,
)
from app.models import (
    COMMON_DOCUMENT_TYPES,
    Attachment,
    CleanupKind,
    CleanupTask,
    Document,
    DocumentChunk,
    DocumentChunkPublic,
    DocumentClone,
    DocumentCreate,
    DocumentEmbeddingsPublic,
    DocumentLanguages,
    DocumentMove,
    DocumentPublic,
    DocumentShare,
    DocumentShareCreate,
    DocumentSharePublic,
    DocumentSharesPublic,
    DocumentShareUpdate,
    DocumentsPublic,
    DocumentTypeCount,
    DocumentTypesPublic,
    DocumentUpdate,
    DocumentVersion,
    DocumentVersionPublic,
    DocumentVersionsPublic,
    DocumentVersionSummary,
    EmbeddingJob,
    EmbeddingJobPublic,
    EmbeddingStatus,
    EmbeddingSummary,
    Folder,
    JobStatus,
    LanguageOption,
    Message,
    Namespace,
    NamespaceMember,
    PublicLink,
    SharedWithMe,
    ShareEmails,
    ShareInvitation,
    ShareInvitationPublic,
    ShareResult,
    ShareRole,
    ShareSkipped,
    TranslationPublic,
    TranslationRequest,
    User,
    UserRef,
    clean_document_type,
)
from app.services import credits, quota, sharing
from app.services import notes as notes_service
from app.services.cloning import copy_embedded_attachments
from app.services.email import (
    Email,
    EmailError,
    get_email_sender,
    share_invitation_email,
    share_notice_email,
)
from app.services.language import LANGUAGES, is_supported, language_name
from app.services.translation import (
    TranslationError,
    translate_version,
    translated_languages,
)
from app.services.versioning import (
    detect_document_language,
    get_version,
    list_versions,
    record_version,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

IN_PROGRESS = {
    EmbeddingStatus.chunking,
    EmbeddingStatus.summarizing,
    EmbeddingStatus.embedding,
}


# --- collection endpoints (must be registered before "/{document_id}") ---------


@router.get("/", response_model=DocumentsPublic)
def read_documents(
    session: SessionDep,
    auth: AuthDep,
    namespace_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    root_only: bool = False,
    skip: int = 0,
    limit: int = Query(default=100, le=500),
) -> Any:
    """List documents (metadata only) the user can read, optionally filtered."""
    where: list[Any] = [accessible_documents_filter(session, auth.user)]
    if namespace_id is not None:
        where.append(Document.namespace_id == namespace_id)
    if folder_id is not None:
        where.append(Document.folder_id == folder_id)
    elif root_only:
        where.append(col(Document.folder_id).is_(None))
    count = session.exec(select(func.count()).select_from(Document).where(*where)).one()
    docs = session.exec(
        select(Document)
        .where(*where)
        .order_by(col(Document.updated_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DocumentsPublic(
        data=[_summary_with_role(session, auth.user, d) for d in docs], count=count
    )


@router.get("/recent", response_model=DocumentsPublic)
def read_recent_documents(
    session: SessionDep, auth: AuthDep, limit: int = Query(default=20, le=100)
) -> Any:
    docs = session.exec(
        select(Document)
        .where(accessible_documents_filter(session, auth.user))
        .order_by(col(Document.updated_at).desc())
        .limit(limit)
    ).all()
    data = [_summary_with_role(session, auth.user, d) for d in docs]
    return DocumentsPublic(data=data, count=len(data))


@router.get("/shared-with-me", response_model=SharedWithMe)
def read_shared_with_me(session: SessionDep, auth: AuthDep) -> Any:
    """Namespaces where the user is a member (not owner) and individually shared documents."""
    member_ns = session.exec(
        select(Namespace)
        .join(NamespaceMember, col(NamespaceMember.namespace_id) == col(Namespace.id))
        .where(
            NamespaceMember.user_id == auth.user.id, Namespace.owner_id != auth.user.id
        )
        .order_by(col(Namespace.name))
    ).all()
    shared_docs = session.exec(
        select(Document, DocumentShare.role)
        .join(DocumentShare, col(DocumentShare.document_id) == col(Document.id))
        .where(DocumentShare.user_id == auth.user.id)
        .order_by(col(Document.updated_at).desc())
    ).all()
    return SharedWithMe(
        namespaces=to_namespace_publics(session, auth.user, member_ns),
        documents=[to_document_summary(d, ShareRole(role)) for d, role in shared_docs],
    )


@router.get("/embeddings/summary", response_model=EmbeddingSummary)
def read_embedding_summary(session: SessionDep, auth: AuthDep) -> Any:
    """Counts of accessible documents by indexing state (dashboard tiles)."""
    access = accessible_documents_filter(session, auth.user)
    rows = session.exec(
        select(
            Document.embedding_status, Document.embedding_version, Document.version
        ).where(access)
    ).all()
    summary = EmbeddingSummary(total=len(rows))
    for status, emb_version, version in rows:
        if status == EmbeddingStatus.failed:
            summary.failed += 1
        elif status in IN_PROGRESS:
            summary.in_progress += 1
        elif status == EmbeddingStatus.pending:
            summary.pending += 1
        elif status == EmbeddingStatus.ready and emb_version != version:
            summary.stale += 1
        else:
            summary.ready += 1
    accessible_ids = select(Document.id).where(access)
    summary.queued_jobs = session.exec(
        select(func.count())
        .select_from(EmbeddingJob)
        .where(
            EmbeddingJob.status == JobStatus.queued,
            col(EmbeddingJob.document_id).in_(accessible_ids),
        )
    ).one()
    summary.running_jobs = session.exec(
        select(func.count())
        .select_from(EmbeddingJob)
        .where(
            EmbeddingJob.status == JobStatus.running,
            col(EmbeddingJob.document_id).in_(accessible_ids),
        )
    ).one()
    return summary


def _require_page_capacity(
    session: Session, user_id: uuid.UUID, wanted: int = 1
) -> None:
    """Refuse the request if the account has no room for another page.

    409, the same code this API already uses for "the state of things is in
    the way" - a duplicate title, a retry in the wrong state. The message names
    the number and never the group it came from.
    """
    try:
        quota.ensure_page_capacity(session, user_id, wanted=wanted)
    except quota.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/", response_model=DocumentPublic)
def create_document(
    session: SessionDep, auth: WriteAuth, document_in: DocumentCreate
) -> Any:
    """Create a document. ``content`` may be HTML (default), Markdown or plain text."""
    namespace, _ = require_namespace(
        session, auth.user, document_in.namespace_id, "editor"
    )
    if document_in.folder_id is not None:
        folder = session.get(Folder, document_in.folder_id)
        if folder is None or folder.namespace_id != namespace.id:
            raise HTTPException(status_code=400, detail="Folder not in this namespace")
    _require_page_capacity(session, auth.user.id)
    html, text = normalize_content(document_in.content, document_in.content_format)
    title = document_in.title.strip()
    if crud.document_title_taken(
        session,
        namespace_id=namespace.id,
        folder_id=document_in.folder_id,
        title=title,
    ):
        raise HTTPException(
            status_code=409, detail="There is already a page with this name here"
        )
    document = Document(
        namespace_id=namespace.id,
        folder_id=document_in.folder_id,
        title=title,
        doc_type=clean_document_type(document_in.doc_type),
        content_html=html,
        content_text=text,
        language=detect_document_language(title, text),
        version=1,
        created_by=auth.user.id,
        updated_by=auth.user.id,
    )
    session.add(document)
    session.flush()
    record_version(session, document, created_by=auth.user.id)
    if (document_in.note or "").strip():
        # Before the enqueue below, so the first index already has it rather
        # than the page being embedded twice for one creation.
        notes_service.add(
            session,
            document,
            body=document_in.note or "",
            author_id=auth.user.id,
            reindex=False,
        )
    crud.enqueue_embedding_job(session=session, document=document)
    session.commit()
    session.refresh(document)
    return to_document_public(session, auth.user, document)


@router.get("/types", response_model=DocumentTypesPublic)
def read_document_types(session: SessionDep, auth: AuthDep) -> Any:
    """The types worth offering: the ones you already use, then the usual ones.

    Counted across the pages you can see, so the list reflects how this person
    actually files things rather than a fixed vocabulary.
    """
    rows = session.exec(
        select(Document.doc_type, func.count())
        .where(
            col(Document.doc_type).is_not(None),
            accessible_documents_filter(session, auth.user),
        )
        .group_by(col(Document.doc_type))
    ).all()

    counts: dict[str, int] = {}
    for name, total in rows:
        if name:
            counts[name] = int(total)

    used = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    data = [DocumentTypeCount(name=name, count=total) for name, total in used]
    seen = {name.lower() for name in counts}
    data += [
        DocumentTypeCount(name=name, count=0)
        for name in COMMON_DOCUMENT_TYPES
        if name.lower() not in seen
    ]
    return DocumentTypesPublic(data=data, count=len(data))


# --- single document -----------------------------------------------------------


@router.get("/{document_id}", response_model=DocumentPublic)
def read_document(session: SessionDep, auth: AuthDep, document_id: uuid.UUID) -> Any:
    document, role = require_document(session, auth.user, document_id, "viewer")
    return to_document_public(session, auth.user, document, role)


@router.put("/{document_id}", response_model=DocumentPublic)
def update_document(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    document_in: DocumentUpdate,
) -> Any:
    """Update title and/or content.

    The version is bumped (and embeddings re-generated) only when the title or the
    derived plain text changes; formatting-only edits are saved without a new version.
    Pass ``expected_version`` for optimistic locking (409 on mismatch).
    """
    document, role = require_document(session, auth.user, document_id, "editor")
    if (
        document_in.expected_version is not None
        and document_in.expected_version != document.version
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Document was modified elsewhere",
                "current_version": document.version,
                "updated_at": document.updated_at.isoformat()
                if document.updated_at
                else None,
            },
        )
    new_title = (
        document.title if document_in.title is None else document_in.title.strip()
    )
    if new_title != document.title and crud.document_title_taken(
        session,
        namespace_id=document.namespace_id,
        folder_id=document.folder_id,
        title=new_title,
        exclude_id=document.id,
    ):
        raise HTTPException(
            status_code=409, detail="There is already a page with this name here"
        )
    new_html, new_text = document.content_html, document.content_text
    if document_in.content is not None:
        new_html, new_text = normalize_content(
            document_in.content, document_in.content_format
        )

    changed = crud.content_changed(
        document.title, document.content_text, new_title, new_text
    )
    document.title = new_title
    document.content_html = new_html
    document.content_text = new_text
    if document_in.doc_type is not None:
        # An empty string clears it; leaving the field out leaves it alone. The
        # type is metadata, not content, so changing it alone does not make the
        # page stale or re-run the AI index.
        document.doc_type = clean_document_type(document_in.doc_type)
    document.updated_by = auth.user.id
    document.updated_at = datetime.now(UTC)
    if changed:
        document.version += 1
        document.language = detect_document_language(new_title, new_text)
        # The new version has no translations of its own yet, by design: the
        # words changed, so last version's German no longer describes them.
        record_version(session, document, created_by=auth.user.id)
        crud.enqueue_embedding_job(session=session, document=document)
    session.add(document)
    session.commit()
    session.refresh(document)
    return to_document_public(session, auth.user, document, role)


@router.post("/{document_id}/move", response_model=DocumentPublic)
def move_document(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID, move_in: DocumentMove
) -> Any:
    """Move a document to another folder and/or namespace."""
    document, _ = require_document(session, auth.user, document_id, "editor")
    target_ns_id = move_in.namespace_id or document.namespace_id
    if target_ns_id != document.namespace_id:
        # moving across namespaces requires editor rights on both sides
        require_namespace(session, auth.user, document.namespace_id, "editor")
    target_ns, _ = require_namespace(session, auth.user, target_ns_id, "editor")
    if move_in.folder_id is not None:
        folder = session.get(Folder, move_in.folder_id)
        if folder is None or folder.namespace_id != target_ns.id:
            raise HTTPException(
                status_code=400, detail="Folder not in the target namespace"
            )
    if crud.document_title_taken(
        session,
        namespace_id=target_ns.id,
        folder_id=move_in.folder_id,
        title=document.title,
        exclude_id=document.id,
    ):
        raise HTTPException(
            status_code=409,
            detail="There is already a page with this name in the destination",
        )
    document.namespace_id = target_ns.id
    document.folder_id = move_in.folder_id
    document.updated_at = datetime.now(UTC)
    session.add(document)
    session.commit()
    session.refresh(document)
    return to_document_public(session, auth.user, document)


@router.delete("/{document_id}")
def delete_document(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID
) -> Message:
    document, _ = require_document(session, auth.user, document_id, "viewer")
    if not can_delete_document(session, auth.user, document):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.add(
        CleanupTask(
            kind=CleanupKind.qdrant_document,
            payload={
                "document_id": str(document.id),
                "namespace_id": str(document.namespace_id),
            },
        )
    )
    session.delete(document)
    session.commit()
    return Message(message="Document deleted successfully")


@router.post("/{document_id}/clone", response_model=DocumentPublic)
def clone_document(
    session: SessionDep,
    auth: WriteAuth,
    storage: StorageDep,
    document_id: uuid.UUID,
    body: DocumentClone,
) -> Any:
    """Copy a page you can read into a space you can write to.

    The copy belongs to you. It is a separate page from the moment it exists:
    editing it does not touch the original, the original's shares do not follow
    it, and nobody else can see it until you share it yourself. That is the
    point - it is how somebody keeps a copy of something shared with them
    without depending on the sharer leaving it in place.

    Images embedded in the page are copied into the destination space too.
    Pointing the copy at the original's files would leave it broken for anyone
    who cannot read the original, which is most of the reason to clone.
    """
    source, _ = require_document(session, auth.user, document_id, "viewer")
    target_ns, _ = require_namespace(session, auth.user, body.namespace_id, "editor")
    # A copy is a page like any other, and it is charged to whoever made the
    # copy. Without this, cloning pages shared with you is an unmetered way to
    # fill the knowledge base - it only needs *viewer* on the original.
    _require_page_capacity(session, auth.user.id)
    if body.folder_id is not None:
        folder = session.get(Folder, body.folder_id)
        if folder is None or folder.namespace_id != target_ns.id:
            raise HTTPException(status_code=400, detail="Folder not in this namespace")

    html, attachments = copy_embedded_attachments(
        session,
        storage,
        html=source.content_html,
        source_namespace_id=source.namespace_id,
        target_namespace_id=target_ns.id,
        uploader_id=auth.user.id,
        reader=auth.user,
    )
    title = (body.title or f"{source.title} (copy)").strip()[:300]
    # A copy is never refused over its name: "(copy)", then "(copy) (2)".
    title = crud.available_document_title(
        session,
        namespace_id=target_ns.id,
        folder_id=body.folder_id,
        title=title,
    )

    clone_text = html_to_text(html)
    clone = Document(
        namespace_id=target_ns.id,
        folder_id=body.folder_id,
        title=title,
        doc_type=source.doc_type,
        content_html=html,
        content_text=clone_text,
        language=source.language or detect_document_language(title, clone_text),
        version=1,
        created_by=auth.user.id,
        updated_by=auth.user.id,
    )
    session.add(clone)
    session.flush()
    for attachment in attachments:
        attachment.document_id = clone.id
        session.add(attachment)
    # The copy starts its own history at version 1. The original's versions and
    # translations stay with the original - they describe a page this one is no
    # longer tied to.
    record_version(session, clone, created_by=auth.user.id)
    # A copy without the notes would lose the part explaining why the page was
    # worth copying.
    notes_service.copy_to(session, source.id, clone, author_id=auth.user.id)
    crud.enqueue_embedding_job(session=session, document=clone)
    session.commit()
    session.refresh(clone)
    return to_document_public(session, auth.user, clone)


# --- shares -------------------------------------------------------------------


async def _deliver_quietly(message: Email) -> None:
    """Tell somebody they were given access; never fail the share over it.

    The access has already been granted by the time this runs. A mail outage
    should not be reported back as though the share did not happen.
    """
    try:
        await get_email_sender().send(message)
    except EmailError as exc:
        logger.error("could not send %r: %s", message.subject, exc)


def _share_public(session: SessionDep, share: DocumentShare) -> DocumentSharePublic:
    ref = user_ref(session.get(User, share.user_id))
    assert ref is not None
    return DocumentSharePublic(
        id=share.id,
        document_id=share.document_id,
        user=ref,
        role=share.role,
        created_at=share.created_at,
    )


@router.get("/{document_id}/shares", response_model=DocumentSharesPublic)
def read_document_shares(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID
) -> Any:
    document, _ = require_document(session, auth.user, document_id, "viewer")
    shares = session.exec(
        select(DocumentShare)
        .where(DocumentShare.document_id == document.id)
        .order_by(col(DocumentShare.created_at))
    ).all()
    data = [_share_public(session, s) for s in shares]
    return DocumentSharesPublic(data=data, count=len(data))


@router.post("/{document_id}/shares", response_model=DocumentSharePublic)
def share_document(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    share_in: DocumentShareCreate,
) -> Any:
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    user = crud.get_confirmed_user_by_email(session=session, email=share_in.email)
    if user is None:
        # Not an error any more: the address simply has no account yet, so it
        # gets an invitation. Callers that want to know which happened should
        # use /shares/batch, whose reply says so.
        raise HTTPException(
            status_code=409,
            detail=(
                "No account for this address yet. Use /shares/batch to invite "
                "them by email."
            ),
        )
    namespace = session.get(Namespace, document.namespace_id)
    if (
        namespace is not None
        and get_namespace_role(session, user, namespace) is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="This user already has access through the space",
        )
    existing = session.exec(
        select(DocumentShare).where(
            DocumentShare.document_id == document.id, DocumentShare.user_id == user.id
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="Document is already shared with this user"
        )
    share = DocumentShare(
        document_id=document.id,
        user_id=user.id,
        role=share_in.role,
        created_by=auth.user.id,
    )
    session.add(share)
    session.commit()
    session.refresh(share)
    return _share_public(session, share)


@router.post("/{document_id}/shares/batch", response_model=ShareResult)
async def share_document_with_many(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    body: ShareEmails,
) -> Any:
    """Share one page with several addresses at once.

    Addresses that already have an account get access immediately and an email
    saying so. Addresses that do not get an invitation: still no access, but a
    branded message telling them who shared what, and a link to create an
    account. The invitation becomes real access when that address is confirmed.

    The reply separates the three outcomes - `shared`, `invited`, `skipped` -
    so the interface can say plainly which is which rather than guessing.
    """
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    namespace = session.get(Namespace, document.namespace_id)
    sharer = sharing.display_name(auth.user)
    link = sharing.document_url(document.id, namespace.slug if namespace else None)

    # The ceiling belongs to whoever owns the space this page lives in: it is
    # their content being distributed, whoever pressed the button.
    owner = session.get(User, namespace.owner_id) if namespace else None
    # Through the resolver now that the column is nullable: reading it raw
    # would compare an int against None the moment an owner inherits.
    limit = quota.limits_for_owner(session, owner).max_shares_per_document
    used = sharing.recipient_count(session, document.id)

    result = ShareResult(recipients=used, max_recipients=limit)
    seen: set[str] = set()

    for raw in body.emails:
        address = sharing.normalise_email(str(raw))
        if address in seen:
            continue
        seen.add(address)

        if address == sharing.normalise_email(auth.user.email):
            result.skipped.append(
                ShareSkipped(email=address, reason="That is your own address")
            )
            continue

        if used >= limit:
            result.skipped.append(
                ShareSkipped(
                    email=address,
                    reason=(
                        f"This page has reached its limit of {limit} people. "
                        "Remove someone, or share it by link instead."
                    ),
                )
            )
            continue

        user = crud.get_confirmed_user_by_email(session=session, email=address)

        if user is not None:
            if (
                namespace is not None
                and get_namespace_role(session, user, namespace) is not None
            ):
                result.skipped.append(
                    ShareSkipped(
                        email=address,
                        reason="Already has access through the space",
                    )
                )
                continue
            existing = session.exec(
                select(DocumentShare).where(
                    DocumentShare.document_id == document.id,
                    DocumentShare.user_id == user.id,
                )
            ).first()
            if existing is not None:
                existing.role = body.role
                session.add(existing)
                session.commit()
                session.refresh(existing)
                result.shared.append(_share_public(session, existing))
                continue

            share = DocumentShare(
                document_id=document.id,
                user_id=user.id,
                role=body.role,
                created_by=auth.user.id,
            )
            session.add(share)
            session.commit()
            session.refresh(share)
            result.shared.append(_share_public(session, share))
            used += 1
            await _deliver_quietly(
                share_notice_email(
                    user.email,
                    sharer=sharer,
                    title=document.title,
                    url=link,
                    can_edit=body.role == ShareRole.editor,
                    note=body.message,
                )
            )
            continue

        was_pending = sharing.pending_invitation(
            session, address, document_id=document.id
        )
        record, token = sharing.invite(
            session,
            document=document,
            email=address,
            role=body.role,
            invited_by=auth.user,
        )
        if was_pending is None:
            used += 1
        result.invited.append(
            ShareInvitationPublic(
                id=record.id,
                email=record.email,
                role=record.role,
                expires_at=record.expires_at,
                created_at=record.created_at,
                target="page",
            )
        )
        await _deliver_quietly(
            share_invitation_email(
                address,
                sharer=sharer,
                title=document.title,
                url=sharing.invitation_url(token),
                can_edit=body.role == ShareRole.editor,
                days=settings.SHARE_INVITE_TTL_DAYS,
                note=body.message,
            )
        )

    result.recipients = used
    return result


@router.get("/{document_id}/invitations", response_model=list[ShareInvitationPublic])
def read_document_invitations(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID
) -> Any:
    """Invitations on this page that nobody has accepted yet."""
    document, _ = require_document(session, auth.user, document_id, "viewer")
    rows = session.exec(
        select(ShareInvitation)
        .where(
            ShareInvitation.document_id == document.id,
            col(ShareInvitation.accepted_at).is_(None),
        )
        .order_by(col(ShareInvitation.created_at))
    ).all()
    return [
        ShareInvitationPublic(
            id=r.id,
            email=r.email,
            role=r.role,
            expires_at=r.expires_at,
            created_at=r.created_at,
            target="page",
        )
        for r in rows
    ]


@router.delete("/{document_id}/invitations/{invitation_id}")
def cancel_invitation(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> Message:
    """Withdraw an invitation. The emailed link stops working immediately."""
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    record = session.get(ShareInvitation, invitation_id)
    if record is None or record.document_id != document.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    session.delete(record)
    session.commit()
    return Message(message="Invitation withdrawn")


# --- public links --------------------------------------------------------------


@router.post("/{document_id}/public", response_model=PublicLink)
def publish_document(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID
) -> Any:
    """Make this page readable by anyone holding its link.

    The link is the only credential, so treat it as one. Publishing twice keeps
    the existing link rather than invalidating a copy already sent.
    """
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    slug = sharing.publish(session, document, auth.user)
    return PublicLink(
        slug=slug,
        url=sharing.public_url(slug),
        shared_at=document.public_shared_at,
    )


@router.delete("/{document_id}/public")
def unpublish_document(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID
) -> Message:
    """Withdraw the public link. Anyone still holding it gets nothing."""
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    sharing.unpublish(session, document)
    return Message(message="This page is no longer shared by link")


@router.patch("/{document_id}/shares/{user_id}", response_model=DocumentSharePublic)
def update_document_share(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    share_in: DocumentShareUpdate,
) -> Any:
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    share = session.exec(
        select(DocumentShare).where(
            DocumentShare.document_id == document.id, DocumentShare.user_id == user_id
        )
    ).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found")
    share.role = share_in.role
    session.add(share)
    session.commit()
    session.refresh(share)
    return _share_public(session, share)


@router.delete("/{document_id}/shares/{user_id}")
def unshare_document(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID, user_id: uuid.UUID
) -> Message:
    document, _ = require_document(session, auth.user, document_id, "editor")
    if not can_share_document(session, auth.user, document):
        raise HTTPException(
            status_code=403, detail="Only space editors can share documents"
        )
    share = session.exec(
        select(DocumentShare).where(
            DocumentShare.document_id == document.id, DocumentShare.user_id == user_id
        )
    ).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found")
    session.delete(share)
    session.commit()
    return Message(message="Share removed")


# --- embeddings ------------------------------------------------------------------


@router.get("/{document_id}/embeddings", response_model=DocumentEmbeddingsPublic)
def read_document_embeddings(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID
) -> Any:
    """Indexing state, job history, summary and chunks of a document."""
    document, _ = require_document(session, auth.user, document_id, "viewer")
    jobs = session.exec(
        select(EmbeddingJob)
        .where(EmbeddingJob.document_id == document.id)
        .order_by(col(EmbeddingJob.created_at).desc())
        .limit(10)
    ).all()
    current = session.exec(
        select(EmbeddingJob)
        .where(
            EmbeddingJob.document_id == document.id,
            col(EmbeddingJob.status).in_([JobStatus.queued, JobStatus.running]),
        )
        .order_by(col(EmbeddingJob.created_at).desc())
    ).first()
    chunks: list[DocumentChunkPublic] = []
    if document.embedding_version is not None:
        rows = session.exec(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.doc_version == document.embedding_version,
            )
            .order_by(col(DocumentChunk.chunk_index))
        ).all()
        chunks = [DocumentChunkPublic.model_validate(c) for c in rows]
    return DocumentEmbeddingsPublic(
        document_id=document.id,
        version=document.version,
        embedding_version=document.embedding_version,
        is_stale=document.embedding_version != document.version,
        embedding_status=document.embedding_status,
        embedding_error=document.embedding_error,
        embedding_attempts=document.embedding_attempts,
        chunk_count=document.chunk_count,
        chunking_method=document.chunking_method,
        embedding_updated_at=document.embedding_updated_at,
        summary=document.summary,
        current_job=to_job_public(current) if current else None,
        jobs=[to_job_public(j) for j in jobs],
        chunks=chunks,
    )


@router.post(
    "/embeddings/reindex-all", dependencies=[Depends(get_current_active_superuser)]
)
def reindex_all_embeddings(session: SessionDep) -> Message:
    """Queue every document for re-indexing.

    Needed after the vector collection schema changes (for example when BM25
    sparse vectors were introduced), since existing points cannot be migrated
    in place.
    """
    documents = session.exec(select(Document)).all()
    for document in documents:
        crud.enqueue_embedding_job(
            session=session, document=document, force=True, reset_attempts=True
        )
    session.commit()
    return Message(message=f"Queued {len(documents)} documents for re-indexing")


@router.post("/{document_id}/embeddings/regenerate", response_model=EmbeddingJobPublic)
def regenerate_document_embeddings(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID
) -> Any:
    """Force a fresh chunking + summary + embedding run (also used for retry)."""
    document, _ = require_document(session, auth.user, document_id, "editor")
    job = crud.enqueue_embedding_job(
        session=session, document=document, force=True, reset_attempts=True
    )
    session.commit()
    session.refresh(job)
    return to_job_public(job)


# --- helpers -----------------------------------------------------------------------


def _summary_with_role(session: SessionDep, user: User, document: Document) -> Any:
    namespace = session.get(Namespace, document.namespace_id)
    role = role_for_documents(session, user, namespace)
    if role is None:
        role = get_document_role(session, user, document, namespace)
    return to_document_summary(document, role)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def _version_summary(
    version: DocumentVersion,
    current: int,
    originals: dict[int, list[str]],
    refs: dict[uuid.UUID, UserRef],
) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        version=version.version,
        title=version.title,
        doc_type=version.doc_type,
        language=version.language,
        char_count=len(version.content_text or ""),
        is_current=version.version == current,
        source_filenames=originals.get(version.version, []),
        created_by_user=refs.get(version.created_by) if version.created_by else None,
        created_at=version.created_at,
    )


def _originals_by_version(
    session: Session, document_id: uuid.UUID
) -> dict[int, list[str]]:
    """Which uploaded originals belong to which version of the page."""
    rows = session.exec(
        select(Attachment)
        .where(
            Attachment.document_id == document_id,
            col(Attachment.source_order).is_not(None),
        )
        .order_by(col(Attachment.source_order))
    ).all()
    by_version: dict[int, list[str]] = {}
    for attachment in rows:
        by_version.setdefault(attachment.source_version or 1, []).append(
            attachment.filename
        )
    return by_version


@router.get("/{document_id}/versions", response_model=DocumentVersionsPublic)
def read_document_versions(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID
) -> Any:
    """Every version of a page, newest first.

    Titles and sizes only: the content of a version is fetched when one is
    chosen, so opening a page with a long history costs nothing extra.
    """
    document, _ = require_document(session, auth.user, document_id, "viewer")
    versions = list_versions(session, document.id)
    originals = _originals_by_version(session, document.id)
    refs = user_refs_by_id(
        session, [v.created_by for v in versions if v.created_by is not None]
    )
    return DocumentVersionsPublic(
        data=[_version_summary(v, document.version, originals, refs) for v in versions],
        count=len(versions),
    )


@router.get("/{document_id}/versions/{version}", response_model=DocumentVersionPublic)
def read_document_version(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID, version: int
) -> Any:
    document, _ = require_document(session, auth.user, document_id, "viewer")
    stored = get_version(session, document.id, version)
    if stored is None:
        raise HTTPException(status_code=404, detail="Version not found")
    originals = _originals_by_version(session, document.id)
    refs = user_refs_by_id(session, [stored.created_by] if stored.created_by else [])
    summary = _version_summary(stored, document.version, originals, refs)
    return DocumentVersionPublic(
        **summary.model_dump(),
        content_html=stored.content_html,
        content_text=stored.content_text,
    )


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


@router.get("/{document_id}/languages", response_model=DocumentLanguages)
def read_document_languages(
    session: SessionDep, auth: AuthDep, document_id: uuid.UUID
) -> Any:
    """What the language picker needs: this page's own language, and the rest.

    `available` is the languages already translated for the version on screen,
    which is what lets the picker show which choices are instant and which will
    take a moment.
    """
    document, _ = require_document(session, auth.user, document_id, "viewer")
    return DocumentLanguages(
        document_id=document.id,
        version=document.version,
        source_language=document.language,
        source_language_name=language_name(document.language),
        available=translated_languages(session, document.id, document.version),
        options=[
            LanguageOption(code=code, name=name) for code, name in LANGUAGES.items()
        ],
    )


@router.post("/{document_id}/translations", response_model=TranslationPublic)
async def translate_document(
    session: SessionDep,
    auth: AuthDep,
    document_id: uuid.UUID,
    body: TranslationRequest,
) -> Any:
    """Read this page in another language.

    The page is not sent from the browser: this takes a language and reads the
    page here. A translation already stored for this exact version comes back
    immediately; anything else is written now and kept for the next reader.

    Reading is enough - translating is not an edit. It leaves the page alone
    and writes a copy beside it.
    """
    document, _ = require_document(session, auth.user, document_id, "viewer")
    code = body.language.strip().lower()
    if not is_supported(code):
        raise HTTPException(status_code=422, detail="That language is not offered")
    # After the stored-translation check below would be kinder, but this runs
    # before it on purpose: a page already translated returns without calling a
    # model, and the check costs two aggregates either way.
    try:
        credits.ensure_credit(session, auth.user)
    except credits.CreditsExhausted as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    version = get_version(session, document.id, document.version)
    if version is None:
        # A page from before the history existed, or one whose oldest versions
        # have been pruned: record where it stands now and translate that.
        version = record_version(session, document)
        session.commit()
        if version is None:  # pragma: no cover - record_version always returns one
            raise HTTPException(status_code=409, detail="Nothing to translate")
        session.refresh(version)

    if not version.content_text.strip():
        raise HTTPException(status_code=422, detail="This page has no text yet")

    try:
        translation = await translate_version(
            session, version, code, requested_by=auth.user.id
        )
    except TranslationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return TranslationPublic(
        document_id=translation.document_id,
        doc_version=translation.doc_version,
        language=translation.language,
        language_name=language_name(translation.language) or translation.language,
        title=translation.title,
        content_html=translation.content_html,
        content_text=translation.content_text,
        model=translation.model,
        created_at=translation.created_at,
    )
