from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import NamespaceRole, ShareRole
from tests.utils.kb import (
    API,
    add_member,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
    share_document,
)


def test_share_lifecycle(client: TestClient, db: Session) -> None:
    owner, opw = create_user_with_password(db)
    guest, gpw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    oh = login(client, owner, opw)
    gh = login(client, guest, gpw)
    url = f"{API}/documents/{doc.id}"

    assert client.get(url, headers=gh).status_code == 404

    r = client.post(
        f"{url}/shares", headers=oh, json={"email": guest.email, "role": "viewer"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == guest.email
    assert client.get(url, headers=gh).status_code == 200
    assert client.put(url, headers=gh, json={"title": "nope"}).status_code == 403
    # duplicate share
    assert (
        client.post(
            f"{url}/shares", headers=oh, json={"email": guest.email}
        ).status_code
        == 409
    )
    # unknown user
    # An address with no account is no longer a dead end: the batch endpoint
    # invites it. This single-address endpoint says so rather than pretending
    # the page does not exist.
    unknown = client.post(
        f"{url}/shares", headers=oh, json={"email": "ghost@example.com"}
    )
    assert unknown.status_code == 409
    assert "invite" in unknown.json()["detail"]

    r = client.patch(f"{url}/shares/{guest.id}", headers=oh, json={"role": "editor"})
    assert r.status_code == 200 and r.json()["role"] == "editor"
    assert client.put(url, headers=gh, json={"title": "yes"}).status_code == 200

    # a shared editor cannot re-share
    other, _ = create_user_with_password(db)
    assert (
        client.post(
            f"{url}/shares", headers=gh, json={"email": other.email}
        ).status_code
        == 403
    )

    r = client.get(f"{url}/shares", headers=oh)
    assert r.json()["count"] == 1

    assert client.delete(f"{url}/shares/{guest.id}", headers=oh).status_code == 200
    assert client.get(url, headers=gh).status_code == 404
    assert client.delete(f"{url}/shares/{guest.id}", headers=oh).status_code == 404


def test_cannot_share_with_namespace_member(client: TestClient, db: Session) -> None:
    owner, opw = create_user_with_password(db)
    member, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, member, NamespaceRole.viewer)
    doc = create_document(db, ns, owner)
    r = client.post(
        f"{API}/documents/{doc.id}/shares",
        headers=login(client, owner, opw),
        json={"email": member.email},
    )
    assert r.status_code == 409
    assert "space" in r.json()["detail"].lower()


def test_namespace_editor_can_share(client: TestClient, db: Session) -> None:
    owner, _ = create_user_with_password(db)
    editor, epw = create_user_with_password(db)
    guest, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, editor, NamespaceRole.editor)
    doc = create_document(db, ns, owner)
    r = client.post(
        f"{API}/documents/{doc.id}/shares",
        headers=login(client, editor, epw),
        json={"email": guest.email, "role": "viewer"},
    )
    assert r.status_code == 200


def test_shared_viewer_sees_shares_list_but_cannot_edit_them(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    guest, gpw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    share_document(db, doc, guest, ShareRole.viewer)
    gh = login(client, guest, gpw)
    assert client.get(f"{API}/documents/{doc.id}/shares", headers=gh).status_code == 200
    assert (
        client.patch(
            f"{API}/documents/{doc.id}/shares/{guest.id}",
            headers=gh,
            json={"role": "editor"},
        ).status_code
        == 403
    )


def test_shared_only_user_can_read_namespace_shell(
    client: TestClient, db: Session
) -> None:
    """A user with only a document share sees the namespace metadata and a tree
    containing just the shared documents (no folders, no role)."""
    from app.models import Folder

    owner, opw = create_user_with_password(db)
    stranger, spw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    folder = Folder(namespace_id=ns.id, name="Eng", created_by=owner.id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    shared_doc = create_document(
        db, ns, owner, title="Shared page", folder_id=folder.id
    )
    create_document(db, ns, owner, title="Private page")
    headers = login(client, stranger, spw)

    # before sharing: 404 everywhere
    assert (
        client.get(f"{API}/namespaces/by-slug/{ns.slug}", headers=headers).status_code
        == 404
    )
    assert (
        client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers).status_code == 404
    )

    share_document(db, shared_doc, stranger, ShareRole.viewer)

    r = client.get(f"{API}/namespaces/by-slug/{ns.slug}", headers=headers)
    assert r.status_code == 200
    assert r.json()["my_role"] is None
    r = client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers)
    assert r.status_code == 200
    tree = r.json()
    assert tree["folders"] == []
    assert [d["title"] for d in tree["documents"]] == ["Shared page"]
    assert tree["documents"][0]["my_role"] == "viewer"
    assert tree["documents"][0]["namespace_slug"] == ns.slug
    # still no write access to the namespace itself
    assert (
        client.patch(
            f"{API}/namespaces/{ns.id}", headers=headers, json={"name": "x"}
        ).status_code
        == 404
    )
