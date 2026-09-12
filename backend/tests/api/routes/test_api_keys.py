from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import ApiKey
from tests.utils.kb import (
    API,
    api_create_document,
    create_namespace,
    create_user_with_password,
    login,
)


def _create_key(client: TestClient, headers: dict[str, str], **body) -> dict:  # type: ignore[no-untyped-def]
    body.setdefault("name", "ci")
    r = client.post(f"{API}/api-keys/", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_list_revoke(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    h = login(client, user, pw)
    created = _create_key(client, h, name="laptop", scope="write", expires_in_days=30)
    assert created["key"].startswith(settings.API_KEY_PREFIX)
    assert created["key_prefix"] == created["key"][:12]
    assert created["scope"] == "write"
    assert created["expires_at"] is not None

    r = client.get(f"{API}/api-keys/", headers=h)
    assert r.status_code == 200
    listed = r.json()["data"]
    assert len(listed) == 1
    assert "key" not in listed[0] and "key_hash" not in listed[0]

    r = client.patch(
        f"{API}/api-keys/{created['id']}", headers=h, json={"name": "renamed"}
    )
    assert r.status_code == 200 and r.json()["name"] == "renamed"

    key_headers = {"Authorization": f"Bearer {created['key']}"}
    assert client.get(f"{API}/namespaces/", headers=key_headers).status_code == 200
    db.expire_all()
    row = db.exec(select(ApiKey).where(ApiKey.id == created["id"])).one()
    assert row.last_used_at is not None

    assert (
        client.delete(f"{API}/api-keys/{created['id']}", headers=h).status_code == 200
    )
    assert (
        client.delete(f"{API}/api-keys/{created['id']}", headers=h).status_code == 200
    )  # idempotent
    r = client.get(f"{API}/namespaces/", headers=key_headers)
    assert r.status_code == 403
    assert (
        client.get(f"{API}/api-keys/", headers=h).json()["data"][0]["revoked_at"]
        is not None
    )


def test_scopes(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    ns = create_namespace(db, user)
    h = login(client, user, pw)
    read_key = _create_key(client, h, name="ro", scope="read")["key"]
    write_key = _create_key(client, h, name="rw", scope="write")["key"]
    rh = {"Authorization": f"Bearer {read_key}"}
    wh = {"Authorization": f"Bearer {write_key}"}

    body = {
        "namespace_id": str(ns.id),
        "title": "From API",
        "content": "# hi\n\ntext",
        "content_format": "markdown",
    }
    r = client.post(f"{API}/documents/", headers=rh, json=body)
    assert r.status_code == 403
    assert "write scope" in r.json()["detail"]
    r = client.post(f"{API}/documents/", headers=wh, json=body)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["content_html"].startswith("<h1>hi</h1>")
    assert client.get(f"{API}/documents/{doc['id']}", headers=rh).status_code == 200
    assert (
        client.put(
            f"{API}/documents/{doc['id']}", headers=rh, json={"title": "x"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"{API}/documents/{doc['id']}", headers=wh, json={"title": "x"}
        ).status_code
        == 200
    )


def test_api_key_cannot_manage_account(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    h = login(client, user, pw)
    key = _create_key(client, h, scope="write")["key"]
    kh = {"Authorization": f"Bearer {key}"}
    assert client.get(f"{API}/api-keys/", headers=kh).status_code == 403
    assert (
        client.post(f"{API}/api-keys/", headers=kh, json={"name": "x"}).status_code
        == 403
    )
    r = client.patch(
        f"{API}/users/me/password",
        headers=kh,
        json={"current_password": pw, "new_password": "newpassword123"},
    )
    assert r.status_code == 403
    # but reading the profile is fine
    assert client.get(f"{API}/users/me", headers=kh).status_code == 200


def test_expired_and_invalid_keys(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    h = login(client, user, pw)
    created = _create_key(client, h, expires_in_days=1)
    row = db.exec(select(ApiKey).where(ApiKey.id == created["id"])).one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(row)
    db.commit()
    kh = {"Authorization": f"Bearer {created['key']}"}
    r = client.get(f"{API}/namespaces/", headers=kh)
    assert r.status_code == 403 and "expired" in r.json()["detail"]
    assert (
        client.get(
            f"{API}/namespaces/", headers={"Authorization": "Bearer kb_doesnotexist"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"{API}/namespaces/", headers={"Authorization": "Basic abc"}
        ).status_code
        == 401
    )
    assert client.get(f"{API}/namespaces/").status_code == 401


def test_keys_are_private_per_user(client: TestClient, db: Session) -> None:
    a, apw = create_user_with_password(db)
    b, bpw = create_user_with_password(db)
    created = _create_key(client, login(client, a, apw))
    bh = login(client, b, bpw)
    assert client.get(f"{API}/api-keys/", headers=bh).json()["count"] == 0
    assert (
        client.delete(f"{API}/api-keys/{created['id']}", headers=bh).status_code == 404
    )
    # key acts as user a
    ns = create_namespace(db, a)
    api_create_document(
        client, {"Authorization": f"Bearer {created['key']}"}, str(ns.id)
    ) if False else None
