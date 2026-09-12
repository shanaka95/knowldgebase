import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.permissions import (
    accessible_documents_filter,
    accessible_namespace_ids,
    can_delete_document,
    can_read_document,
    can_share_document,
    can_write_document,
    get_document_role,
    get_namespace_role,
    require_document,
    require_namespace,
)
from app.models import Document, NamespaceRole, ShareRole, UserCreate
from tests.utils.kb import (
    add_member,
    create_document,
    create_namespace,
    create_user_with_password,
    share_document,
)
from tests.utils.utils import random_email, random_lower_string


def test_role_matrix(db: Session) -> None:
    owner, _ = create_user_with_password(db)
    admin, _ = create_user_with_password(db)
    editor, _ = create_user_with_password(db)
    viewer, _ = create_user_with_password(db)
    shared_v, _ = create_user_with_password(db)
    shared_e, _ = create_user_with_password(db)
    stranger, _ = create_user_with_password(db)
    superuser = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string(), is_superuser=True
        ),
    )
    ns = create_namespace(db, owner)
    add_member(db, ns, admin, NamespaceRole.admin)
    add_member(db, ns, editor, NamespaceRole.editor)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    doc = create_document(db, ns, owner)
    share_document(db, doc, shared_v, ShareRole.viewer)
    share_document(db, doc, shared_e, ShareRole.editor)

    assert get_namespace_role(db, owner, ns) == NamespaceRole.admin
    assert get_namespace_role(db, superuser, ns) == NamespaceRole.admin
    assert get_namespace_role(db, admin, ns) == NamespaceRole.admin
    assert get_namespace_role(db, editor, ns) == NamespaceRole.editor
    assert get_namespace_role(db, viewer, ns) == NamespaceRole.viewer
    assert get_namespace_role(db, shared_v, ns) is None
    assert get_namespace_role(db, stranger, ns) is None

    expected = [
        (owner, (ShareRole.editor, True, True, True)),
        (superuser, (ShareRole.editor, True, True, True)),
        (admin, (ShareRole.editor, True, True, True)),
        (editor, (ShareRole.editor, True, True, True)),
        (viewer, (ShareRole.viewer, False, False, False)),
        (shared_v, (ShareRole.viewer, False, False, False)),
        (shared_e, (ShareRole.editor, True, False, False)),
        (stranger, (None, False, False, False)),
    ]
    for user, (role, write, share, delete) in expected:
        assert get_document_role(db, user, doc) == role, user.email
        assert can_read_document(db, user, doc) is (role is not None), user.email
        assert can_write_document(db, user, doc) is write, user.email
        assert can_share_document(db, user, doc) is share, user.email
        assert can_delete_document(db, user, doc) is delete, user.email

    # accessible namespaces / documents
    assert set(accessible_namespace_ids(db, viewer)) == {ns.id}
    assert ns.id in set(accessible_namespace_ids(db, superuser))
    assert accessible_namespace_ids(db, shared_v) == []
    for user, visible in [
        (shared_v, True),
        (viewer, True),
        (stranger, False),
        (superuser, True),
    ]:
        rows = db.exec(
            select(Document).where(
                accessible_documents_filter(db, user), Document.id == doc.id
            )
        ).all()
        assert bool(rows) is visible, user.email


def test_require_helpers_raise(db: Session) -> None:
    owner, _ = create_user_with_password(db)
    viewer, _ = create_user_with_password(db)
    stranger, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    doc = create_document(db, ns, owner)

    with pytest.raises(HTTPException) as e:
        require_namespace(db, stranger, ns.id, "viewer")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        require_namespace(db, viewer, ns.id, "editor")
    assert e.value.status_code == 403
    assert require_namespace(db, viewer, ns.id, "viewer")[1] == NamespaceRole.viewer
    with pytest.raises(HTTPException) as e:
        require_document(db, viewer, doc.id, "editor")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        require_document(db, stranger, doc.id, "viewer")
    assert e.value.status_code == 404
    assert require_document(db, owner, doc.id, "editor")[1] == ShareRole.editor
