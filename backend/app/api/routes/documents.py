import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import col, func, select

from app import crud
from app.api.deps import (
    AuthDep,
    SessionDep,
    WriteAuth,
    get_current_active_superuser,
)
from app.api.serializers import (
    role_for_documents,
    to_document_public,
    to_document_summary,
    to_job_public,
    to_namespace_public,
    user_ref,
)
from app.core.content import normalize_content
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
    CleanupKind,
    CleanupTask,
    Document,
    DocumentChunk,
    DocumentChunkPublic,
    DocumentCreate,
    DocumentEmbeddingsPublic,
    DocumentMove,
    DocumentPublic,
    DocumentShare,
    DocumentShareCreate,
    DocumentSharePublic,
    DocumentSharesPublic,
    DocumentShareUpdate,
    DocumentsPublic,
    DocumentUpdate,
    EmbeddingJob,
    EmbeddingJobPublic,
    EmbeddingStatus,
    EmbeddingSummary,
    Folder,
    JobStatus,
    Message,
    Namespace,
    NamespaceMember,
    SharedWithMe,
    ShareRole,
    User,
)

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
        namespaces=[to_namespace_public(session, auth.user, ns) for ns in member_ns],
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
    html, text = normalize_content(document_in.content, document_in.content_format)
    document = Document(
        namespace_id=namespace.id,
        folder_id=document_in.folder_id,
        title=document_in.title.strip(),
        content_html=html,
        content_text=text,
        version=1,
        created_by=auth.user.id,
        updated_by=auth.user.id,
    )
    session.add(document)
    session.flush()
    crud.enqueue_embedding_job(session=session, document=document)
    session.commit()
    session.refresh(document)
    return to_document_public(session, auth.user, document)


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
    document.updated_by = auth.user.id
    document.updated_at = datetime.now(UTC)
    if changed:
        document.version += 1
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


# --- shares -------------------------------------------------------------------


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
    user = crud.get_user_by_email(session=session, email=share_in.email)
    if user is None:
        raise HTTPException(status_code=404, detail="No user with this email")
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
