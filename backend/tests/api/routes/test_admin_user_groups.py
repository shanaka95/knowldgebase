"""Groups, the limits they carry, and the fact that nobody in one is told.

The privacy requirement is the interesting half: an account may be told its own
number, because that is actionable, and must never be told where the number came
from, because that is administration.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.services import quota
from tests.utils.kb import API, create_user_with_password, login

GROUPS = f"{API}/admin/user-groups/"
ADMIN_USERS = f"{API}/admin/users/"


def _create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    body.setdefault("name", f"Group {uuid.uuid4().hex[:8]}")
    r = client.post(GROUPS, headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------- access


def test_only_an_administrator_can_see_the_groups(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    ordinary, pw = create_user_with_password(db)
    assert client.get(GROUPS, headers=superuser_token_headers).status_code == 200
    assert client.get(GROUPS, headers=login(client, ordinary, pw)).status_code == 403


def test_an_api_key_cannot_reach_the_admin_routes(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """The dependency chains off a session, so a key is not enough even for an
    administrator - these endpoints change what everyone is allowed."""
    key = client.post(
        f"{API}/api-keys/",
        headers=superuser_token_headers,
        json={"name": "admin key", "scope": "write"},
    ).json()
    refused = client.get(GROUPS, headers={"Authorization": f"Bearer {key['key']}"})
    assert refused.status_code in (401, 403)


# -------------------------------------------------------------------- groups


def test_the_default_group_is_there_and_says_what_everyone_gets(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    listed = client.get(GROUPS, headers=superuser_token_headers).json()
    default = next(g for g in listed["data"] if g["is_default"])
    assert default["effective_max_pages"] == 100
    assert default["is_system"] is True


def test_the_default_group_cannot_be_deleted(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    listed = client.get(GROUPS, headers=superuser_token_headers).json()
    default = next(g for g in listed["data"] if g["is_default"])
    refused = client.delete(f"{GROUPS}{default['id']}", headers=superuser_token_headers)
    assert refused.status_code == 409


def test_a_group_that_sets_nothing_reports_what_its_members_would_get(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    group = _create(client, superuser_token_headers)
    assert group["max_pages"] is None, "it sets nothing"
    assert group["effective_max_pages"] == 100, "and its members still get a number"


def test_two_groups_cannot_share_a_name(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    group = _create(client, superuser_token_headers)
    clash = client.post(
        GROUPS, headers=superuser_token_headers, json={"name": group["name"].lower()}
    )
    assert clash.status_code == 409


# --------------------------------------------------------------- assignment


def test_moving_an_account_into_a_group_changes_what_it_may_do(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    group = _create(client, superuser_token_headers, max_pages=7)

    moved = client.post(
        f"{GROUPS}{group['id']}/members",
        headers=superuser_token_headers,
        json={"user_ids": [str(user.id)]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["member_count"] == 1

    db.refresh(user)
    assert quota.resolve_limits(db, user).max_pages == 7


def test_an_override_beats_the_group_and_says_so(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    group = _create(client, superuser_token_headers, max_pages=7)

    assigned = client.put(
        f"{ADMIN_USERS}{user.id}/assignment",
        headers=superuser_token_headers,
        json={"group_id": group["id"], "overrides": {"max_pages": 500}},
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["max_pages"] == 500

    pages = next(limit for limit in body["limits"] if limit["key"] == "max_pages")
    assert pages["source"] == "user"
    assert pages["override"] == 500
    assert pages["group_value"] == 7, "the whole chain, so nothing is a mystery"
    assert pages["default_value"] == 100


def test_sending_no_overrides_clears_them(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A complete map, not a patch: an absent key is an override that is unset."""
    user, _ = create_user_with_password(db)
    group = _create(client, superuser_token_headers, max_pages=7)
    client.put(
        f"{ADMIN_USERS}{user.id}/assignment",
        headers=superuser_token_headers,
        json={"group_id": group["id"], "overrides": {"max_pages": 500}},
    )

    cleared = client.put(
        f"{ADMIN_USERS}{user.id}/assignment",
        headers=superuser_token_headers,
        json={"group_id": group["id"], "overrides": {}},
    ).json()
    assert cleared["max_pages"] == 7
    pages = next(limit for limit in cleared["limits"] if limit["key"] == "max_pages")
    assert pages["source"] == "group" and pages["override"] is None


def test_an_unknown_limit_is_refused(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    refused = client.put(
        f"{ADMIN_USERS}{user.id}/assignment",
        headers=superuser_token_headers,
        json={"group_id": None, "overrides": {"max_bananas": 3}},
    )
    assert refused.status_code == 422


def test_deleting_a_group_returns_its_members_to_the_defaults(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    group = _create(client, superuser_token_headers, max_pages=7)
    client.post(
        f"{GROUPS}{group['id']}/members",
        headers=superuser_token_headers,
        json={"user_ids": [str(user.id)]},
    )
    assert (
        client.delete(
            f"{GROUPS}{group['id']}", headers=superuser_token_headers
        ).status_code
        == 200
    )
    db.refresh(user)
    assert user.group_id is None
    assert quota.resolve_limits(db, user).max_pages == 100


def test_the_admin_list_can_find_the_unassigned(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Unanswerable from a list that stops at the first hundred."""
    user, _ = create_user_with_password(db)
    listed = client.get(
        ADMIN_USERS,
        headers=superuser_token_headers,
        params={"group_id": "none", "q": user.email},
    ).json()
    assert [row["email"] for row in listed["data"]] == [user.email]
    assert listed["data"][0]["group"] is None


# -------------------------------------------------------------------- privacy


def test_nothing_a_member_can_fetch_mentions_their_group(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The sentinel is endpoint-agnostic on purpose, so it survives new routes."""
    sentinel = f"ZZGRP{uuid.uuid4().hex[:10]}"
    group = _create(client, superuser_token_headers, name=sentinel, max_pages=42)

    user, pw = create_user_with_password(db)
    client.post(
        f"{GROUPS}{group['id']}/members",
        headers=superuser_token_headers,
        json={"user_ids": [str(user.id)]},
    )
    headers = login(client, user, pw)

    for path in (
        f"{API}/users/me",
        f"{API}/users/{user.id}",
        f"{API}/login/test-token",
        f"{API}/namespaces/",
    ):
        response = (
            client.post(path, headers=headers)
            if path.endswith("test-token")
            else client.get(path, headers=headers)
        )
        assert response.status_code == 200, path
        body = response.text
        assert sentinel not in body, f"{path} leaked the group's name"
        assert '"group' not in body, f"{path} leaked a group field"

    # The number itself is theirs to know - it is what they have to act on.
    assert client.get(f"{API}/users/me", headers=headers).json()["max_pages"] == 42
    # And the administration of it is not.
    assert client.get(GROUPS, headers=headers).status_code == 403
