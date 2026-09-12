"""One tenant must never reach another's data, by any route.

Every other test in this suite asks whether a feature works. These ask the
opposite question: given a valid session belonging to somebody else, can it be
pointed at data it has no claim to? The answer has to be no for every verb on
every resource, and it has to be no for API keys and MCP callers too, because
those are the same endpoints with a different credential.

A note on status codes. "Not found" is the right answer for a resource someone
cannot see: 403 confirms the id exists, which is itself a leak - it turns any
endpoint into an oracle for guessing at other people's data. 403 is reserved for
resources the caller *can* see but may not change.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import ApiKeyScope, NamespaceRole, ShareRole
from tests.utils.kb import (
    API,
    add_member,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
    share_document,
)

DENIED = (401, 403, 404)


@pytest.fixture
def stranger(client: TestClient, db: Session) -> dict[str, str]:
    """Somebody with a perfectly valid session and no business here."""
    user, password = create_user_with_password(db)
    return login(client, user, password)


@pytest.fixture
def owner_world(client: TestClient, db: Session) -> dict[str, Any]:
    """One account with a space, a folder and a page in it."""
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    ns = create_namespace(db, user, "Private space")
    doc = create_document(
        db, ns, user, title="Salary review", html="<p>A confidential number.</p>"
    )
    db.commit()
    return {
        "user": user,
        "password": password,
        "headers": headers,
        "namespace": ns,
        "document": doc,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def test_a_stranger_cannot_read_a_page(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/documents/{owner_world['document'].id}", headers=stranger)
    assert r.status_code == 404
    assert "confidential" not in r.text


def test_a_stranger_cannot_edit_a_page(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.put(
        f"{API}/documents/{owner_world['document'].id}",
        headers=stranger,
        json={"title": "Owned", "content": "<p>Mine now.</p>"},
    )
    assert r.status_code in DENIED


def test_a_stranger_cannot_delete_a_page(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    doc_id = owner_world["document"].id
    r = client.delete(f"{API}/documents/{doc_id}", headers=stranger)
    assert r.status_code in DENIED
    # And it is still there.
    assert (
        client.get(
            f"{API}/documents/{doc_id}", headers=owner_world["headers"]
        ).status_code
        == 200
    )


def test_a_stranger_cannot_move_a_page_into_their_own_space(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    """The most tempting shape of this bug: a move that only checks the target."""
    thief, password = create_user_with_password(db)
    thief_headers = login(client, thief, password)
    thief_space = create_namespace(db, thief, "Thief space")
    db.commit()

    r = client.post(
        f"{API}/documents/{owner_world['document'].id}/move",
        headers=thief_headers,
        json={"namespace_id": str(thief_space.id), "folder_id": None},
    )
    assert r.status_code in DENIED


def test_a_stranger_cannot_list_another_space_s_pages(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.get(
        f"{API}/documents/",
        headers=stranger,
        params={"namespace_id": str(owner_world["namespace"].id)},
    )
    assert r.status_code in DENIED or r.json().get("count") == 0


@pytest.mark.usefixtures("owner_world")
def test_listing_pages_never_includes_another_account_s(
    client: TestClient, stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/documents/", headers=stranger)
    assert r.status_code == 200
    titles = [d["title"] for d in r.json()["data"]]
    assert "Salary review" not in titles


@pytest.mark.usefixtures("owner_world")
def test_recent_pages_never_includes_another_account_s(
    client: TestClient, stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/documents/recent", headers=stranger)
    assert r.status_code == 200
    assert "Salary review" not in [d["title"] for d in r.json()["data"]]


# ---------------------------------------------------------------------------
# Spaces and folders
# ---------------------------------------------------------------------------


def test_a_stranger_cannot_see_another_space(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/namespaces/{owner_world['namespace'].id}", headers=stranger)
    assert r.status_code in DENIED


def test_a_stranger_cannot_browse_another_space_s_tree(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.get(
        f"{API}/namespaces/{owner_world['namespace'].id}/tree", headers=stranger
    )
    assert r.status_code in DENIED
    assert "Salary review" not in r.text


@pytest.mark.usefixtures("owner_world")
def test_listing_spaces_shows_only_your_own(
    client: TestClient, stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/namespaces/", headers=stranger)
    assert r.status_code == 200
    assert "Private space" not in [n["name"] for n in r.json()["data"]]


def test_a_stranger_cannot_add_themselves_to_another_space(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    intruder, password = create_user_with_password(db)
    headers = login(client, intruder, password)
    r = client.post(
        f"{API}/namespaces/{owner_world['namespace'].id}/members",
        headers=headers,
        json={"email": intruder.email, "role": NamespaceRole.admin},
    )
    assert r.status_code in DENIED


def test_a_stranger_cannot_create_a_folder_in_another_space(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.post(
        f"{API}/folders/",
        headers=stranger,
        json={"namespace_id": str(owner_world["namespace"].id), "name": "Intrusion"},
    )
    assert r.status_code in DENIED


def test_a_stranger_cannot_create_a_page_in_another_space(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.post(
        f"{API}/documents/",
        headers=stranger,
        json={
            "namespace_id": str(owner_world["namespace"].id),
            "title": "Planted",
            "content": "<p>Hello.</p>",
        },
    )
    assert r.status_code in DENIED


# ---------------------------------------------------------------------------
# Search, Ask and the AI index
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("owner_world")
def test_search_never_returns_another_account_s_pages(
    client: TestClient, stranger: dict[str, str]
) -> None:
    r = client.get(f"{API}/search/", headers=stranger, params={"q": "confidential"})
    assert r.status_code == 200
    assert "Salary review" not in r.text


def test_a_stranger_cannot_read_the_ai_index_of_another_page(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    """The index holds the summary and every chunk, so it leaks the page itself."""
    r = client.get(
        f"{API}/documents/{owner_world['document'].id}/embeddings", headers=stranger
    )
    assert r.status_code in DENIED


def test_a_stranger_cannot_queue_work_on_another_page(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.post(
        f"{API}/documents/{owner_world['document'].id}/embeddings/regenerate",
        headers=stranger,
    )
    assert r.status_code in DENIED


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def test_a_stranger_cannot_download_another_account_s_file(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    upload = client.post(
        f"{API}/attachments/",
        headers=owner_world["headers"],
        data={"namespace_id": str(owner_world["namespace"].id)},
        files={"file": ("secret.txt", io.BytesIO(b"a private file"), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]

    for path in (
        f"/attachments/{attachment_id}",
        f"/attachments/{attachment_id}/download",
    ):
        r = client.get(f"{API}{path}", headers=stranger)
        assert r.status_code in DENIED, path
        assert b"a private file" not in r.content


def test_a_stranger_cannot_delete_another_account_s_file(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    upload = client.post(
        f"{API}/attachments/",
        headers=owner_world["headers"],
        data={"namespace_id": str(owner_world["namespace"].id)},
        files={"file": ("secret.txt", io.BytesIO(b"private"), "text/plain")},
    )
    attachment_id = upload.json()["id"]
    r = client.delete(f"{API}/attachments/{attachment_id}", headers=stranger)
    assert r.status_code in DENIED


def test_files_cannot_be_listed_for_a_space_you_cannot_see(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    """There is no global file list; every listing is scoped and checked."""
    client.post(
        f"{API}/attachments/",
        headers=owner_world["headers"],
        data={"namespace_id": str(owner_world["namespace"].id)},
        files={"file": ("secret.txt", io.BytesIO(b"private"), "text/plain")},
    )
    scoped = client.get(
        f"{API}/attachments/",
        headers=stranger,
        params={"namespace_id": str(owner_world["namespace"].id)},
    )
    assert scoped.status_code in DENIED
    assert "secret.txt" not in scoped.text

    unscoped = client.get(f"{API}/attachments/", headers=stranger)
    assert unscoped.status_code == 422, "asking for everyone's files is not a query"


# ---------------------------------------------------------------------------
# Sharing grants exactly what it says, and no more
# ---------------------------------------------------------------------------


def test_a_viewer_can_read_but_not_write(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    share_document(db, owner_world["document"], guest, ShareRole.viewer)
    db.commit()
    headers = login(client, guest, password)

    assert (
        client.get(
            f"{API}/documents/{owner_world['document'].id}", headers=headers
        ).status_code
        == 200
    )
    r = client.put(
        f"{API}/documents/{owner_world['document'].id}",
        headers=headers,
        json={"title": "Edited", "content": "<p>No.</p>"},
    )
    assert r.status_code in DENIED


def test_sharing_one_page_does_not_share_the_space(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    """A share is a grant on one page, not a key to everything beside it."""
    guest, password = create_user_with_password(db)
    other = create_document(
        db, owner_world["namespace"], owner_world["user"], title="Not shared"
    )
    share_document(db, owner_world["document"], guest, ShareRole.viewer)
    db.commit()
    headers = login(client, guest, password)

    assert client.get(f"{API}/documents/{other.id}", headers=headers).status_code == 404

    # The space around a shared page is visible, so the interface can show where
    # the page lives - but only as a shell. Its counts must describe what this
    # caller can reach, not what is really in there.
    space = client.get(
        f"{API}/namespaces/{owner_world['namespace'].id}", headers=headers
    )
    assert space.status_code == 200
    body = space.json()
    assert body["my_role"] is None, "a share is not membership"
    assert body["document_count"] == 1, "one shared page, not the whole space"
    assert body["member_count"] is None, "who else is in there is not their business"


def test_a_space_viewer_cannot_write(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    add_member(db, owner_world["namespace"], guest, NamespaceRole.viewer)
    db.commit()
    headers = login(client, guest, password)

    assert (
        client.get(
            f"{API}/documents/{owner_world['document'].id}", headers=headers
        ).status_code
        == 200
    )
    r = client.post(
        f"{API}/documents/",
        headers=headers,
        json={
            "namespace_id": str(owner_world["namespace"].id),
            "title": "Planted",
            "content": "<p>Hello.</p>",
        },
    )
    assert r.status_code in DENIED


def test_a_guest_cannot_re_share_what_they_were_given(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    """Otherwise one share silently becomes unlimited distribution."""
    guest, password = create_user_with_password(db)
    third_party, _ = create_user_with_password(db)
    share_document(db, owner_world["document"], guest, ShareRole.editor)
    db.commit()
    headers = login(client, guest, password)

    r = client.post(
        f"{API}/documents/{owner_world['document'].id}/shares",
        headers=headers,
        json={"email": third_party.email, "role": ShareRole.viewer},
    )
    assert r.status_code in DENIED


def test_revoking_a_share_takes_access_away(
    client: TestClient, db: Session, owner_world: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    share_document(db, owner_world["document"], guest, ShareRole.viewer)
    db.commit()
    headers = login(client, guest, password)
    doc_id = owner_world["document"].id
    assert client.get(f"{API}/documents/{doc_id}", headers=headers).status_code == 200

    revoke = client.delete(
        f"{API}/documents/{doc_id}/shares/{guest.id}",
        headers=owner_world["headers"],
    )
    assert revoke.status_code in (200, 204)
    assert client.get(f"{API}/documents/{doc_id}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# API keys, which is how the MCP server connects
# ---------------------------------------------------------------------------


def make_key(client: TestClient, headers: dict[str, str], scope: str) -> str:
    r = client.post(
        f"{API}/api-keys/",
        headers=headers,
        json={"name": f"test {scope}", "scope": scope},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["key"])


def test_an_api_key_reaches_exactly_its_owner_s_data(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    """The MCP server acts as the key's owner, so this is what scopes an agent."""
    key = make_key(client, stranger, ApiKeyScope.write)
    key_headers = {"Authorization": f"Bearer {key}"}

    r = client.get(f"{API}/documents/{owner_world['document'].id}", headers=key_headers)
    assert r.status_code == 404

    spaces = client.get(f"{API}/namespaces/", headers=key_headers)
    assert spaces.status_code == 200
    assert "Private space" not in spaces.text


def test_a_read_only_key_cannot_write_anything(client: TestClient, db: Session) -> None:
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    ns = create_namespace(db, user)
    db.commit()
    key = make_key(client, headers, ApiKeyScope.read)
    key_headers = {"Authorization": f"Bearer {key}"}

    assert client.get(f"{API}/namespaces/", headers=key_headers).status_code == 200
    r = client.post(
        f"{API}/documents/",
        headers=key_headers,
        json={
            "namespace_id": str(ns.id),
            "title": "Written by a read key",
            "content": "<p>No.</p>",
        },
    )
    assert r.status_code == 403


def test_a_revoked_key_stops_working(client: TestClient, db: Session) -> None:
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    created = client.post(
        f"{API}/api-keys/", headers=headers, json={"name": "temp", "scope": "read"}
    ).json()
    key_headers = {"Authorization": f"Bearer {created['key']}"}
    assert client.get(f"{API}/namespaces/", headers=key_headers).status_code == 200

    client.delete(f"{API}/api-keys/{created['id']}", headers=headers)
    assert client.get(f"{API}/namespaces/", headers=key_headers).status_code == 403


def test_api_keys_are_not_visible_to_other_accounts(
    client: TestClient, db: Session, stranger: dict[str, str]
) -> None:
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    created = client.post(
        f"{API}/api-keys/", headers=headers, json={"name": "mine", "scope": "read"}
    ).json()

    listed = client.get(f"{API}/api-keys/", headers=stranger)
    assert listed.status_code == 200
    assert created["id"] not in [k["id"] for k in listed.json()["data"]]

    r = client.delete(f"{API}/api-keys/{created['id']}", headers=stranger)
    assert r.status_code in DENIED


def test_an_api_key_cannot_be_used_to_manage_the_account(
    client: TestClient, db: Session
) -> None:
    """A leaked key must not be able to change the password or mint more keys."""
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    key = make_key(client, headers, ApiKeyScope.write)
    key_headers = {"Authorization": f"Bearer {key}"}

    minting = client.post(
        f"{API}/api-keys/", headers=key_headers, json={"name": "more", "scope": "write"}
    )
    assert minting.status_code in DENIED

    change = client.patch(
        f"{API}/users/me/password",
        headers=key_headers,
        json={"current_password": password, "new_password": "a-new-password"},
    )
    assert change.status_code in DENIED


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_an_ordinary_account_cannot_list_everyone(
    client: TestClient, stranger: dict[str, str]
) -> None:
    assert client.get(f"{API}/users/", headers=stranger).status_code in DENIED


def test_an_ordinary_account_cannot_edit_another(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.patch(
        f"{API}/users/{owner_world['user'].id}",
        headers=stranger,
        json={"is_superuser": True},
    )
    assert r.status_code in DENIED


def test_an_ordinary_account_cannot_delete_another(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    r = client.delete(f"{API}/users/{owner_world['user'].id}", headers=stranger)
    assert r.status_code in DENIED


def test_nobody_can_promote_themselves(client: TestClient, db: Session) -> None:
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    client.patch(f"{API}/users/me", headers=headers, json={"is_superuser": True})
    db.refresh(user)
    assert user.is_superuser is False


# ---------------------------------------------------------------------------
# Guessing
# ---------------------------------------------------------------------------


def test_an_unknown_id_looks_the_same_as_a_forbidden_one(
    client: TestClient, owner_world: dict[str, Any], stranger: dict[str, str]
) -> None:
    """Otherwise the API tells you which ids exist, one request at a time."""
    forbidden = client.get(
        f"{API}/documents/{owner_world['document'].id}", headers=stranger
    )
    missing = client.get(f"{API}/documents/{uuid.uuid4()}", headers=stranger)
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


def test_no_endpoint_accepts_a_session_that_was_never_issued(
    client: TestClient, owner_world: dict[str, Any]
) -> None:
    forged = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.not-a-signature"}
    for path in (
        "/users/me",
        "/namespaces/",
        "/documents/",
        f"/documents/{owner_world['document'].id}",
        "/api-keys/",
    ):
        assert client.get(f"{API}{path}", headers=forged).status_code in DENIED, path


def test_the_private_test_api_is_off_outside_development() -> None:
    """It creates users without a password check, so it must never ship enabled."""
    from app.api.main import api_router

    private_routes = [
        r for r in api_router.routes if "/private/" in getattr(r, "path", "")
    ]
    if settings.FASTAPI_ENV != "development":
        assert not private_routes
