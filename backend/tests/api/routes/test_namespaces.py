from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import CleanupKind, CleanupTask, NamespaceRole
from tests.utils.kb import (
    API,
    add_member,
    api_create_document,
    api_create_namespace,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)


def test_create_and_list_namespace(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    ns = api_create_namespace(
        client, normal_user_token_headers, name="Personal Notes", icon="home"
    )
    assert ns["slug"].startswith("personal-notes")
    assert ns["my_role"] == "admin"
    assert ns["member_count"] == 1
    r = client.get(f"{API}/namespaces/", headers=normal_user_token_headers)
    assert r.status_code == 200
    assert any(n["id"] == ns["id"] for n in r.json()["data"])
    r = client.get(
        f"{API}/namespaces/by-slug/{ns['slug']}", headers=normal_user_token_headers
    )
    assert r.status_code == 200
    assert r.json()["id"] == ns["id"]


def test_duplicate_name_conflict(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    api_create_namespace(client, normal_user_token_headers, name="Dupe Space")
    r = client.post(
        f"{API}/namespaces/",
        headers=normal_user_token_headers,
        json={"name": "Dupe Space"},
    )
    assert r.status_code == 409


def test_slug_uniqueness_across_owners(client: TestClient, db: Session) -> None:
    u1, p1 = create_user_with_password(db)
    u2, p2 = create_user_with_password(db)
    a = api_create_namespace(client, login(client, u1, p1), name="Office")
    b = api_create_namespace(client, login(client, u2, p2), name="Office")
    assert a["slug"] != b["slug"]


def test_stranger_cannot_see_namespace(client: TestClient, db: Session) -> None:
    owner, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    stranger, pw = create_user_with_password(db)
    headers = login(client, stranger, pw)
    assert client.get(f"{API}/namespaces/{ns.id}", headers=headers).status_code == 404
    assert (
        client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers).status_code == 404
    )
    assert (
        client.patch(
            f"{API}/namespaces/{ns.id}", headers=headers, json={"name": "x"}
        ).status_code
        == 404
    )


def test_member_roles_and_update_permissions(client: TestClient, db: Session) -> None:
    owner, opw = create_user_with_password(db)
    viewer, vpw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    owner_headers = login(client, owner, opw)

    r = client.post(
        f"{API}/namespaces/{ns.id}/members",
        headers=owner_headers,
        json={"email": viewer.email, "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "viewer"
    # duplicate
    r = client.post(
        f"{API}/namespaces/{ns.id}/members",
        headers=owner_headers,
        json={"email": viewer.email, "role": "editor"},
    )
    assert r.status_code == 409
    # unknown email
    r = client.post(
        f"{API}/namespaces/{ns.id}/members",
        headers=owner_headers,
        json={"email": "nobody@nowhere.example.com", "role": "viewer"},
    )
    assert r.status_code == 404
    # owner cannot be added
    r = client.post(
        f"{API}/namespaces/{ns.id}/members",
        headers=owner_headers,
        json={"email": owner.email, "role": "viewer"},
    )
    assert r.status_code == 409

    viewer_headers = login(client, viewer, vpw)
    r = client.get(f"{API}/namespaces/{ns.id}", headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["my_role"] == "viewer"
    # viewer cannot rename or manage members
    assert (
        client.patch(
            f"{API}/namespaces/{ns.id}", headers=viewer_headers, json={"name": "no"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/namespaces/{ns.id}/members",
            headers=viewer_headers,
            json={"email": owner.email},
        ).status_code
        == 403
    )

    # members list contains owner first as admin
    r = client.get(f"{API}/namespaces/{ns.id}/members", headers=viewer_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data[0]["is_owner"] is True and data[0]["role"] == "admin"
    assert any(m["user"]["email"] == viewer.email for m in data)

    # promote to admin, then admin can rename
    r = client.patch(
        f"{API}/namespaces/{ns.id}/members/{viewer.id}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert r.status_code == 200 and r.json()["role"] == "admin"
    r = client.patch(
        f"{API}/namespaces/{ns.id}", headers=viewer_headers, json={"name": "Renamed"}
    )
    assert (
        r.status_code == 200
        and r.json()["name"] == "Renamed"
        and r.json()["slug"].startswith("renamed")
    )

    # remove member; owner removal refused
    assert (
        client.delete(
            f"{API}/namespaces/{ns.id}/members/{owner.id}", headers=owner_headers
        ).status_code
        == 400
    )
    assert (
        client.delete(
            f"{API}/namespaces/{ns.id}/members/{viewer.id}", headers=owner_headers
        ).status_code
        == 200
    )
    assert (
        client.get(f"{API}/namespaces/{ns.id}", headers=viewer_headers).status_code
        == 404
    )


def test_tree_lists_folders_and_documents(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    r = client.post(
        f"{API}/folders/",
        headers=headers,
        json={"namespace_id": str(ns.id), "name": "Guides"},
    )
    assert r.status_code == 200, r.text
    folder = r.json()
    api_create_document(client, headers, str(ns.id), title="Root doc")
    api_create_document(
        client, headers, str(ns.id), title="Nested doc", folder_id=folder["id"]
    )
    r = client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers)
    assert r.status_code == 200
    tree = r.json()
    assert tree["namespace"]["id"] == str(ns.id)
    assert [f["name"] for f in tree["folders"]] == ["Guides"]
    titles = {d["title"]: d for d in tree["documents"]}
    assert titles["Nested doc"]["folder_id"] == folder["id"]
    assert titles["Root doc"]["folder_id"] is None
    assert titles["Root doc"]["my_role"] == "editor"
    assert titles["Root doc"]["is_stale"] is True  # never embedded yet


def test_delete_namespace_enqueues_cleanup(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    headers = login(client, owner, pw)
    r = client.delete(f"{API}/namespaces/{ns.id}", headers=headers)
    assert r.status_code == 200
    tasks = db.exec(
        select(CleanupTask).where(CleanupTask.kind == CleanupKind.qdrant_document)
    ).all()
    assert any(t.payload.get("document_id") == str(doc.id) for t in tasks)
    assert client.get(f"{API}/namespaces/{ns.id}", headers=headers).status_code == 404


def test_superuser_can_open_everything_without_being_a_member_of_it(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Reading every space is the account; being an admin of one is a relationship.

    Conflating them put an ADMIN badge on spaces belonging to other people that
    had never been shared with anybody.
    """
    owner, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    r = client.get(f"{API}/namespaces/{ns.id}", headers=superuser_token_headers)
    assert r.status_code == 200, "an administrator can still open it"
    assert r.json()["my_role"] is None, "but holds no role in it"


def test_editor_member_can_create_content_but_not_manage(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    editor, epw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, editor, NamespaceRole.editor)
    headers = login(client, editor, epw)
    api_create_document(client, headers, str(ns.id))
    assert (
        client.delete(f"{API}/namespaces/{ns.id}", headers=headers).status_code == 403
    )
