import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, col, select

from app import crud
from app.api.deps import AuthDep, SessionDep, WriteAuth
from app.api.serializers import (
    role_for_documents,
    to_document_summary,
    to_namespace_public,
    user_ref,
)
from app.core.permissions import (
    accessible_namespace_ids,
    get_document_role,
    get_namespace_role,
    require_namespace,
)
from app.models import (
    Attachment,
    CleanupKind,
    CleanupTask,
    Document,
    DocumentShare,
    Folder,
    FolderPublic,
    Message,
    Namespace,
    NamespaceCreate,
    NamespaceMember,
    NamespaceMemberCreate,
    NamespaceMemberPublic,
    NamespaceMembersPublic,
    NamespaceMemberUpdate,
    NamespacePublic,
    NamespaceRole,
    NamespacesPublic,
    NamespaceTree,
    NamespaceUpdate,
    User,
)

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


def enqueue_namespace_cleanup(session: Session, namespace_id: uuid.UUID) -> None:
    """Queue vector + object deletions for everything inside a namespace."""
    doc_ids = session.exec(
        select(Document.id).where(Document.namespace_id == namespace_id)
    ).all()
    for doc_id in doc_ids:
        session.add(
            CleanupTask(
                kind=CleanupKind.qdrant_document,
                payload={"document_id": str(doc_id), "namespace_id": str(namespace_id)},
            )
        )
    keys = session.exec(
        select(Attachment.object_key).where(Attachment.namespace_id == namespace_id)
    ).all()
    for key in keys:
        session.add(
            CleanupTask(kind=CleanupKind.minio_object, payload={"object_key": key})
        )


@router.get("/", response_model=NamespacesPublic)
def read_namespaces(session: SessionDep, auth: AuthDep) -> Any:
    """Namespaces the current user owns or is a member of (superusers: all)."""
    ids = accessible_namespace_ids(session, auth.user)
    if not ids:
        return NamespacesPublic(data=[], count=0)
    namespaces = session.exec(
        select(Namespace)
        .where(col(Namespace.id).in_(ids))
        .order_by(col(Namespace.name))
    ).all()
    data = [to_namespace_public(session, auth.user, ns) for ns in namespaces]
    return NamespacesPublic(data=data, count=len(data))


@router.post("/", response_model=NamespacePublic)
def create_namespace(
    session: SessionDep, auth: WriteAuth, namespace_in: NamespaceCreate
) -> Any:
    existing = session.exec(
        select(Namespace).where(
            Namespace.owner_id == auth.user.id, Namespace.name == namespace_in.name
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="You already have a space with this name"
        )
    namespace = Namespace.model_validate(
        namespace_in,
        update={
            "owner_id": auth.user.id,
            "slug": crud.unique_namespace_slug(session=session, name=namespace_in.name),
        },
    )
    session.add(namespace)
    session.commit()
    session.refresh(namespace)
    return to_namespace_public(session, auth.user, namespace)


def _namespace_for_reader(
    session: Session, user: User, namespace: Namespace
) -> tuple[Namespace, NamespaceRole | None, list[Document] | None]:
    """Resolve read access to a namespace.

    Members (and owners/superusers) get their role and full visibility. A user who
    only holds shares on individual documents gets ``role=None`` plus the list of
    those documents, so the UI can render the space shell around a shared page.
    """
    role = get_namespace_role(session, user, namespace)
    if role is not None:
        return namespace, role, None
    shared_docs = session.exec(
        select(Document)
        .join(DocumentShare, col(DocumentShare.document_id) == col(Document.id))
        .where(
            Document.namespace_id == namespace.id,
            DocumentShare.user_id == user.id,
        )
        .order_by(col(Document.title))
    ).all()
    if not shared_docs:
        raise HTTPException(status_code=404, detail="Namespace not found")
    return namespace, None, list(shared_docs)


@router.get("/by-slug/{slug}", response_model=NamespacePublic)
def read_namespace_by_slug(session: SessionDep, auth: AuthDep, slug: str) -> Any:
    namespace = session.exec(select(Namespace).where(Namespace.slug == slug)).first()
    if namespace is None:
        raise HTTPException(status_code=404, detail="Namespace not found")
    namespace, role, _ = _namespace_for_reader(session, auth.user, namespace)
    return to_namespace_public(session, auth.user, namespace, role)


@router.get("/{namespace_id}", response_model=NamespacePublic)
def read_namespace(session: SessionDep, auth: AuthDep, namespace_id: uuid.UUID) -> Any:
    namespace = session.get(Namespace, namespace_id)
    if namespace is None:
        raise HTTPException(status_code=404, detail="Namespace not found")
    namespace, role, _ = _namespace_for_reader(session, auth.user, namespace)
    return to_namespace_public(session, auth.user, namespace, role)


@router.patch("/{namespace_id}", response_model=NamespacePublic)
def update_namespace(
    session: SessionDep,
    auth: WriteAuth,
    namespace_id: uuid.UUID,
    namespace_in: NamespaceUpdate,
) -> Any:
    namespace, role = require_namespace(session, auth.user, namespace_id, "admin")
    data = namespace_in.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != namespace.name:
        clash = session.exec(
            select(Namespace).where(
                Namespace.owner_id == namespace.owner_id,
                Namespace.name == data["name"],
                Namespace.id != namespace.id,
            )
        ).first()
        if clash:
            raise HTTPException(
                status_code=409, detail="A space with this name already exists"
            )
        data["slug"] = crud.unique_namespace_slug(
            session=session, name=data["name"], exclude_id=namespace.id
        )
    namespace.sqlmodel_update(data)
    namespace.updated_at = datetime.now(UTC)
    session.add(namespace)
    session.commit()
    session.refresh(namespace)
    return to_namespace_public(session, auth.user, namespace, role)


@router.delete("/{namespace_id}")
def delete_namespace(
    session: SessionDep, auth: WriteAuth, namespace_id: uuid.UUID
) -> Message:
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    enqueue_namespace_cleanup(session, namespace.id)
    session.delete(namespace)
    session.commit()
    return Message(message="Namespace deleted successfully")


@router.get("/{namespace_id}/tree", response_model=NamespaceTree)
def read_namespace_tree(
    session: SessionDep, auth: AuthDep, namespace_id: uuid.UUID
) -> Any:
    """All folders and documents (metadata only) of a namespace, for the sidebar tree.

    Users without a namespace role but with document shares get only their shared
    documents (and no folders).
    """
    namespace = session.get(Namespace, namespace_id)
    if namespace is None:
        raise HTTPException(status_code=404, detail="Namespace not found")
    namespace, role, shared_docs = _namespace_for_reader(session, auth.user, namespace)
    if shared_docs is not None:
        return NamespaceTree(
            namespace=to_namespace_public(session, auth.user, namespace, role),
            folders=[],
            documents=[
                to_document_summary(d, get_document_role(session, auth.user, d))
                for d in shared_docs
            ],
        )
    folders = session.exec(
        select(Folder)
        .where(Folder.namespace_id == namespace.id)
        .order_by(col(Folder.name))
    ).all()
    documents = session.exec(
        select(Document)
        .where(Document.namespace_id == namespace.id)
        .order_by(col(Document.title))
    ).all()
    doc_role = role_for_documents(session, auth.user, namespace)
    return NamespaceTree(
        namespace=to_namespace_public(session, auth.user, namespace, role),
        folders=[FolderPublic.model_validate(f) for f in folders],
        documents=[to_document_summary(d, doc_role) for d in documents],
    )


# --- members -----------------------------------------------------------------


def _to_member_public(
    session: Session, member: NamespaceMember, namespace: Namespace
) -> NamespaceMemberPublic:
    user = session.get(User, member.user_id)
    ref = user_ref(user)
    assert ref is not None
    return NamespaceMemberPublic(
        id=member.id,
        namespace_id=member.namespace_id,
        user=ref,
        role=member.role,
        is_owner=namespace.owner_id == member.user_id,
        created_at=member.created_at,
    )


@router.get("/{namespace_id}/members", response_model=NamespaceMembersPublic)
def read_namespace_members(
    session: SessionDep, auth: AuthDep, namespace_id: uuid.UUID
) -> Any:
    """Members of a namespace. The owner is listed first as an implicit admin."""
    namespace, _ = require_namespace(session, auth.user, namespace_id, "viewer")
    owner = session.get(User, namespace.owner_id)
    data: list[NamespaceMemberPublic] = []
    if owner is not None:
        owner_ref = user_ref(owner)
        assert owner_ref is not None
        data.append(
            NamespaceMemberPublic(
                id=namespace.id,  # synthetic row for the owner
                namespace_id=namespace.id,
                user=owner_ref,
                role=NamespaceRole.admin,
                is_owner=True,
                created_at=namespace.created_at,
            )
        )
    members = session.exec(
        select(NamespaceMember)
        .where(NamespaceMember.namespace_id == namespace.id)
        .order_by(col(NamespaceMember.created_at))
    ).all()
    data.extend(_to_member_public(session, m, namespace) for m in members)
    return NamespaceMembersPublic(data=data, count=len(data))


@router.post("/{namespace_id}/members", response_model=NamespaceMemberPublic)
def add_namespace_member(
    session: SessionDep,
    auth: WriteAuth,
    namespace_id: uuid.UUID,
    member_in: NamespaceMemberCreate,
) -> Any:
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    user = crud.get_user_by_email(session=session, email=member_in.email)
    if user is None:
        raise HTTPException(status_code=404, detail="No user with this email")
    if user.id == namespace.owner_id:
        raise HTTPException(status_code=409, detail="The owner already has full access")
    existing = session.exec(
        select(NamespaceMember).where(
            NamespaceMember.namespace_id == namespace.id,
            NamespaceMember.user_id == user.id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")
    member = NamespaceMember(
        namespace_id=namespace.id,
        user_id=user.id,
        role=member_in.role,
        created_by=auth.user.id,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    return _to_member_public(session, member, namespace)


@router.patch("/{namespace_id}/members/{user_id}", response_model=NamespaceMemberPublic)
def update_namespace_member(
    session: SessionDep,
    auth: WriteAuth,
    namespace_id: uuid.UUID,
    user_id: uuid.UUID,
    member_in: NamespaceMemberUpdate,
) -> Any:
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    member = session.exec(
        select(NamespaceMember).where(
            NamespaceMember.namespace_id == namespace.id,
            NamespaceMember.user_id == user_id,
        )
    ).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    member.role = member_in.role
    session.add(member)
    session.commit()
    session.refresh(member)
    return _to_member_public(session, member, namespace)


@router.delete("/{namespace_id}/members/{user_id}")
def remove_namespace_member(
    session: SessionDep, auth: WriteAuth, namespace_id: uuid.UUID, user_id: uuid.UUID
) -> Message:
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    if user_id == namespace.owner_id:
        raise HTTPException(status_code=400, detail="The owner cannot be removed")
    member = session.exec(
        select(NamespaceMember).where(
            NamespaceMember.namespace_id == namespace.id,
            NamespaceMember.user_id == user_id,
        )
    ).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    session.delete(member)
    session.commit()
    return Message(message="Member removed")
