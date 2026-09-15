import logging
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
    to_namespace_publics,
    user_ref,
)
from app.core.config import settings
from app.core.permissions import (
    get_document_role,
    get_namespace_role,
    held_namespace_role,
    joined_namespace_ids,
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
    ShareInvitation,
    ShareInvitationPublic,
    ShareSkipped,
    SpaceShareEmails,
    SpaceShareResult,
    User,
)
from app.services import sharing
from app.services.email import (
    Email,
    EmailError,
    get_email_sender,
    space_invitation_email,
    space_notice_email,
)

logger = logging.getLogger(__name__)

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
    """The spaces this person owns or has been made a member of.

    Administrators included: being able to open every space is not the same as
    working in it, and listing all of them here put other people's spaces in
    somebody's own switcher. `/admin` is where every space is listed.
    """
    ids = joined_namespace_ids(session, auth.user)
    if not ids:
        return NamespacesPublic(data=[], count=0)
    namespaces = session.exec(
        select(Namespace)
        .where(col(Namespace.id).in_(ids))
        .order_by(col(Namespace.name))
    ).all()
    data = to_namespace_publics(session, auth.user, namespaces)
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

    Members (and owners/superusers) get full visibility. A user who only holds
    shares on individual documents gets ``role=None`` plus the list of those
    documents, so the UI can render the space shell around a shared page.

    Two different questions are being asked here. *May this person read it* -
    which an administrator may, of every space - decides visibility. *What are
    they here* is what comes back, because that is what gets shown, and an
    administrator is not a member of a space nobody shared with them.
    """
    if get_namespace_role(session, user, namespace) is not None:
        return namespace, held_namespace_role(session, user, namespace), None
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


async def _deliver_quietly(message: Email) -> None:
    """Tell somebody they were let into a space; never fail the share over it.

    Access has already been granted by the time this runs. A mail outage should
    not be reported back as though it had not.
    """
    try:
        await get_email_sender().send(message)
    except EmailError as exc:
        logger.error("could not send %r: %s", message.subject, exc)


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
    user = crud.get_confirmed_user_by_email(session=session, email=member_in.email)
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


@router.post("/{namespace_id}/members/batch", response_model=SpaceShareResult)
async def add_namespace_members(
    session: SessionDep,
    auth: WriteAuth,
    namespace_id: uuid.UUID,
    body: SpaceShareEmails,
) -> Any:
    """Share a whole space with several addresses at once.

    The same shape as sharing a page, deliberately: addresses that already have
    an account join now and are told by email; addresses that do not are
    invited, and join when that address is confirmed.

    Sharing a space gives access to everything in it, now and later. That is a
    bigger grant than sharing a page, which is why it needs space admin.
    """
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    sharer = sharing.display_name(auth.user)
    link = sharing.space_url(namespace.slug)

    owner = session.get(User, namespace.owner_id)
    limit = owner.max_members_per_space if owner else settings.SHARE_MAX_RECIPIENTS
    used = sharing.member_count(session, namespace.id)

    result = SpaceShareResult(members=used, max_members=limit)
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

        user = crud.get_confirmed_user_by_email(session=session, email=address)
        if user is not None and user.id == namespace.owner_id:
            result.skipped.append(
                ShareSkipped(email=address, reason="The owner already has full access")
            )
            continue

        if used >= limit:
            result.skipped.append(
                ShareSkipped(
                    email=address,
                    reason=(
                        f"This space has reached its limit of {limit} people. "
                        "Remove someone first."
                    ),
                )
            )
            continue

        if user is not None:
            existing = session.exec(
                select(NamespaceMember).where(
                    NamespaceMember.namespace_id == namespace.id,
                    NamespaceMember.user_id == user.id,
                )
            ).first()
            if existing is not None:
                existing.role = body.role
                session.add(existing)
                session.commit()
                session.refresh(existing)
                result.shared.append(_to_member_public(session, existing, namespace))
                continue

            member = NamespaceMember(
                namespace_id=namespace.id,
                user_id=user.id,
                role=body.role,
                created_by=auth.user.id,
            )
            session.add(member)
            session.commit()
            session.refresh(member)
            result.shared.append(_to_member_public(session, member, namespace))
            used += 1
            await _deliver_quietly(
                space_notice_email(
                    user.email,
                    sharer=sharer,
                    space=namespace.name,
                    url=link,
                    role=str(body.role),
                    note=body.message,
                )
            )
            continue

        was_pending = sharing.pending_invitation(
            session, address, namespace_id=namespace.id
        )
        record, token = sharing.invite(
            session,
            namespace=namespace,
            email=address,
            role=str(body.role),
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
                target="space",
            )
        )
        await _deliver_quietly(
            space_invitation_email(
                address,
                sharer=sharer,
                space=namespace.name,
                url=sharing.invitation_url(token),
                role=str(body.role),
                days=settings.SHARE_INVITE_TTL_DAYS,
                note=body.message,
            )
        )

    result.members = used
    return result


@router.get("/{namespace_id}/invitations", response_model=list[ShareInvitationPublic])
def read_namespace_invitations(
    session: SessionDep, auth: AuthDep, namespace_id: uuid.UUID
) -> Any:
    """People invited to this space who have not joined yet."""
    namespace, _ = require_namespace(session, auth.user, namespace_id, "viewer")
    rows = session.exec(
        select(ShareInvitation)
        .where(
            ShareInvitation.namespace_id == namespace.id,
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
            target="space",
        )
        for r in rows
    ]


@router.delete("/{namespace_id}/invitations/{invitation_id}")
def cancel_namespace_invitation(
    session: SessionDep,
    auth: WriteAuth,
    namespace_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> Message:
    """Withdraw an invitation. The emailed link stops working immediately."""
    namespace, _ = require_namespace(session, auth.user, namespace_id, "admin")
    record = session.get(ShareInvitation, invitation_id)
    if record is None or record.namespace_id != namespace.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    session.delete(record)
    session.commit()
    return Message(message="Invitation withdrawn")


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
