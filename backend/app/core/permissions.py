"""Authorization helpers for namespaces, folders and documents.

Role model
----------
* Namespace: owner and superusers are implicit ``admin``; other users get the role
  of their ``NamespaceMember`` row (``viewer`` < ``editor`` < ``admin``).
* Document: a namespace role of ``editor``+ grants ``editor`` on every document,
  ``viewer`` grants ``viewer``. Without a namespace role a ``DocumentShare`` row
  grants ``viewer`` or ``editor`` on that single document.
"""

import uuid
from collections.abc import Sequence
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_, true
from sqlmodel import Session, col, select

from app.models import (
    ROLE_RANK,
    Document,
    DocumentShare,
    Folder,
    Namespace,
    NamespaceMember,
    NamespaceRole,
    ShareRole,
    User,
)

MinRole = Literal["viewer", "editor", "admin"]


def get_namespace_role(
    session: Session, user: User, namespace: Namespace
) -> NamespaceRole | None:
    """What this user may do here - including by being an administrator.

    This is the authorization question, so a superuser answers ``admin`` for
    every space. It is *not* the question the interface asks when it labels a
    space: see `held_namespace_role`.
    """
    if user.is_superuser:
        return NamespaceRole.admin
    return held_namespace_role(session, user, namespace)


def held_namespace_role(
    session: Session, user: User, namespace: Namespace
) -> NamespaceRole | None:
    """The role this user holds here by owning it or being a member of it.

    Being an administrator is deliberately not counted. An administrator can
    open every space in the installation, and calling that "admin on this
    space" put an ADMIN badge on spaces belonging to other people that had
    never been shared with anybody - which reads as a claim about the
    relationship rather than about the account.
    """
    if namespace.owner_id == user.id:
        return NamespaceRole.admin
    member = session.exec(
        select(NamespaceMember).where(
            NamespaceMember.namespace_id == namespace.id,
            NamespaceMember.user_id == user.id,
        )
    ).first()
    return member.role if member else None


def has_min_role(role: NamespaceRole | ShareRole | None, min_role: MinRole) -> bool:
    if role is None:
        return False
    return ROLE_RANK[str(role)] >= ROLE_RANK[min_role]


def get_document_role(
    session: Session,
    user: User,
    document: Document,
    namespace: Namespace | None = None,
) -> ShareRole | None:
    namespace = namespace or session.get(Namespace, document.namespace_id)
    if namespace is not None:
        ns_role = get_namespace_role(session, user, namespace)
        if ns_role is not None:
            return (
                ShareRole.editor
                if has_min_role(ns_role, "editor")
                else ShareRole.viewer
            )
    share = session.exec(
        select(DocumentShare).where(
            DocumentShare.document_id == document.id,
            DocumentShare.user_id == user.id,
        )
    ).first()
    return share.role if share else None


def can_read_document(session: Session, user: User, document: Document) -> bool:
    return get_document_role(session, user, document) is not None


def can_write_document(session: Session, user: User, document: Document) -> bool:
    return has_min_role(get_document_role(session, user, document), "editor")


def can_share_document(session: Session, user: User, document: Document) -> bool:
    """Only namespace editors/admins may share; shared-only editors cannot re-share."""
    namespace = session.get(Namespace, document.namespace_id)
    if namespace is None:
        return False
    return has_min_role(get_namespace_role(session, user, namespace), "editor")


def can_delete_document(session: Session, user: User, document: Document) -> bool:
    namespace = session.get(Namespace, document.namespace_id)
    if namespace is None:
        return False
    if has_min_role(get_namespace_role(session, user, namespace), "editor"):
        return True
    return document.created_by == user.id


def require_namespace(
    session: Session, user: User, namespace_id: uuid.UUID, min_role: MinRole
) -> tuple[Namespace, NamespaceRole]:
    namespace = session.get(Namespace, namespace_id)
    if namespace is None:
        raise HTTPException(status_code=404, detail="Namespace not found")
    role = get_namespace_role(session, user, namespace)
    if role is None:
        # hide existence from strangers
        raise HTTPException(status_code=404, detail="Namespace not found")
    if not has_min_role(role, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    return namespace, role


def require_folder(
    session: Session, user: User, folder_id: uuid.UUID, min_role: MinRole
) -> tuple[Folder, Namespace, NamespaceRole]:
    folder = session.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    namespace, role = require_namespace(session, user, folder.namespace_id, min_role)
    return folder, namespace, role


def require_document(
    session: Session,
    user: User,
    document_id: uuid.UUID,
    min_role: Literal["viewer", "editor"],
) -> tuple[Document, ShareRole]:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    role = get_document_role(session, user, document)
    if role is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not has_min_role(role, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    return document, role


def accessible_namespace_ids(session: Session, user: User) -> Sequence[uuid.UUID]:
    """Every space this user may read - an administrator may read all of them.

    This is the authorization question. For the list a person thinks of as
    "my spaces", see `joined_namespace_ids`.
    """
    if user.is_superuser:
        return session.exec(select(Namespace.id)).all()
    return joined_namespace_ids(session, user)


def joined_namespace_ids(session: Session, user: User) -> list[uuid.UUID]:
    """The spaces this user owns or has been made a member of.

    Deliberately not "everything an administrator can open". The space
    switcher is a list of the reader's own working spaces, and filling it with
    every space in the installation buried their own among strangers' - and
    made a space that had never been shared with anybody look shared.
    """
    owned = select(Namespace.id).where(Namespace.owner_id == user.id)
    member = select(NamespaceMember.namespace_id).where(
        NamespaceMember.user_id == user.id
    )
    ids = set(session.exec(owned).all()) | set(session.exec(member).all())
    return list(ids)


def accessible_documents_filter(
    session: Session,  # noqa: ARG001 - kept for symmetry with the other helpers
    user: User,
) -> ColumnElement[bool]:
    """SQL predicate restricting ``Document`` rows to what ``user`` may read."""
    if user.is_superuser:
        return true()
    owned_ns = select(Namespace.id).where(Namespace.owner_id == user.id)
    member_ns = select(NamespaceMember.namespace_id).where(
        NamespaceMember.user_id == user.id
    )
    shared_docs = select(DocumentShare.document_id).where(
        DocumentShare.user_id == user.id
    )
    return or_(
        col(Document.namespace_id).in_(owned_ns),
        col(Document.namespace_id).in_(member_ns),
        col(Document.id).in_(shared_docs),
    )
