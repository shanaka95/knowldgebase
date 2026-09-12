from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import CleanupTask, Document, NamespaceRole
from tests.utils.kb import (
    API,
    add_member,
    api_create_document,
    create_namespace,
    create_user_with_password,
    login,
)


def _mk_folder(
    client: TestClient,
    headers: dict[str, str],
    ns_id: str,
    name: str,
    parent: str | None = None,
) -> dict:
    r = client.post(
        f"{API}/folders/",
        headers=headers,
        json={"namespace_id": ns_id, "name": name, "parent_id": parent},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_folder_tree_operations(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    root = _mk_folder(client, h, str(ns.id), "Root")
    child = _mk_folder(client, h, str(ns.id), "Child", root["id"])
    grandchild = _mk_folder(client, h, str(ns.id), "Grandchild", child["id"])
    doc = api_create_document(client, h, str(ns.id), folder_id=grandchild["id"])

    r = client.get(f"{API}/folders/{child['id']}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [f["name"] for f in body["folders"]] == ["Grandchild"]
    assert [f["name"] for f in body["path"]] == ["Root"]

    r = client.get(f"{API}/folders/{grandchild['id']}", headers=h)
    assert [d["id"] for d in r.json()["documents"]] == [doc["id"]]
    assert [f["name"] for f in r.json()["path"]] == ["Root", "Child"]

    # rename
    r = client.patch(f"{API}/folders/{child['id']}", headers=h, json={"name": "Kid"})
    assert r.status_code == 200 and r.json()["name"] == "Kid"
    # cycle: move Root under Grandchild
    r = client.patch(
        f"{API}/folders/{root['id']}", headers=h, json={"parent_id": grandchild["id"]}
    )
    assert r.status_code == 400
    # self parent
    r = client.patch(
        f"{API}/folders/{root['id']}", headers=h, json={"parent_id": root["id"]}
    )
    assert r.status_code == 400
    # move grandchild to root level
    r = client.patch(
        f"{API}/folders/{grandchild['id']}", headers=h, json={"move_to_root": True}
    )
    assert r.status_code == 200 and r.json()["parent_id"] is None
    # and back under Root
    r = client.patch(
        f"{API}/folders/{grandchild['id']}", headers=h, json={"parent_id": root["id"]}
    )
    assert r.status_code == 200 and r.json()["parent_id"] == root["id"]

    # delete Root cascades to grandchild + its document, and queues cleanup
    r = client.delete(f"{API}/folders/{root['id']}", headers=h)
    assert r.status_code == 200
    assert (
        db.get(Document, doc["id"]) is None
        or db.exec(select(Document).where(Document.id == doc["id"])).first() is None
    )
    tasks = db.exec(select(CleanupTask)).all()
    assert any(t.payload.get("document_id") == doc["id"] for t in tasks)
    assert client.get(f"{API}/folders/{grandchild['id']}", headers=h).status_code == 404


def test_folder_parent_must_be_same_namespace(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns1 = create_namespace(db, owner)
    ns2 = create_namespace(db, owner)
    h = login(client, owner, pw)
    other = _mk_folder(client, h, str(ns2.id), "Other")
    r = client.post(
        f"{API}/folders/",
        headers=h,
        json={"namespace_id": str(ns1.id), "name": "Bad", "parent_id": other["id"]},
    )
    assert r.status_code == 400


def test_folder_permissions(client: TestClient, db: Session) -> None:
    owner, _ = create_user_with_password(db)
    viewer, vpw = create_user_with_password(db)
    editor, epw = create_user_with_password(db)
    stranger, spw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    add_member(db, ns, editor, NamespaceRole.editor)

    body = {"namespace_id": str(ns.id), "name": "F"}
    assert (
        client.post(
            f"{API}/folders/", headers=login(client, viewer, vpw), json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/folders/", headers=login(client, stranger, spw), json=body
        ).status_code
        == 404
    )
    r = client.post(f"{API}/folders/", headers=login(client, editor, epw), json=body)
    assert r.status_code == 200
    # viewer can read
    assert (
        client.get(
            f"{API}/folders/{r.json()['id']}", headers=login(client, viewer, vpw)
        ).status_code
        == 200
    )
