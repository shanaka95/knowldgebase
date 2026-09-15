"""Credits at the edges: who is refused, who can top somebody up, and the sum.

`tests/services/test_credits.py` proves the arithmetic. This proves it is
actually wired into the paths that spend money — the part that can silently not
be, because a missing check looks exactly like a working one until somebody
runs out.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import UsageFeature, UsageKind, User
from app.services import credits, usage
from tests.utils.kb import API, create_namespace, create_user_with_password, login

ME = f"{API}/usage/me/credits"
ADMIN = f"{API}/admin/credits"


def _drain(user: User, db: Session) -> None:
    """Leave the account with nothing to spend, through real usage rows."""
    user.monthly_credits = 1
    db.add(user)
    db.commit()
    meter = usage.UsageMeter(user_id=user.id, feature=UsageFeature.ask)
    meter.record_counts(
        UsageKind.chat,
        "qwen/qwen3.8-flash",
        usage.Counts(requests=1, input_tokens=5000),
    )
    meter.flush()


# ------------------------------------------------------------------ my balance


def test_my_balance_says_what_is_left_and_where_it_went(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)

    meter = usage.UsageMeter(user_id=user.id, feature=UsageFeature.search)
    meter.record_counts(UsageKind.embedding, "embed-1", usage.Counts(requests=10))
    meter.flush()

    body = client.get(ME, headers=headers).json()
    assert body["period"] == credits.current_period().key
    assert body["allowance"] > 0
    assert body["used"] == 1.0, "ten embeddings is one credit"
    assert body["used_on_search"] == 1.0
    assert body["used_on_answers"] == 0
    assert body["remaining"] == body["allowance"] + body["granted"] - 1.0


def test_a_balance_never_mentions_money(client: TestClient, db: Session) -> None:
    """A credit is what you may spend, not what it cost us."""
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    raw = client.get(ME, headers=headers).text
    assert "cost" not in raw.lower()
    assert "nanos" not in raw.lower()


def test_a_balance_needs_a_login(client: TestClient) -> None:
    assert client.get(ME).status_code == 401


# ------------------------------------------------------------------- refusals


def test_asking_is_refused_when_there_is_nothing_left(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _drain(user, db)

    r = client.post(f"{API}/ask/", headers=headers, json={"q": "anything at all"})
    # 402 is the one status that means exactly this.
    assert r.status_code == 402, r.text
    assert "credits" in r.text


def test_searching_is_refused_when_there_is_nothing_left(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _drain(user, db)

    r = client.get(f"{API}/search/retrieve", headers=headers, params={"q": "vpn"})
    assert r.status_code == 402, r.text


def test_plain_keyword_search_still_works_with_no_credits(
    client: TestClient, db: Session
) -> None:
    """It calls no model, so there is nothing to pay for and nothing to refuse."""
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _drain(user, db)

    r = client.get(f"{API}/search/", headers=headers, params={"q": "vpn"})
    assert r.status_code == 200, r.text


def test_reading_a_page_is_never_refused(client: TestClient, db: Session) -> None:
    """Running out stops you spending, not reading what you already have."""
    user, pw = create_user_with_password(db)
    ns = create_namespace(db, user)
    headers = login(client, user, pw)
    _drain(user, db)

    assert client.get(f"{API}/namespaces/{ns.id}", headers=headers).status_code == 200
    assert client.get(f"{API}/documents/", headers=headers).status_code == 200


# --------------------------------------------------------------------- grants


def test_an_administrator_can_top_an_account_up(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _drain(user, db)
    assert (
        client.post(f"{API}/ask/", headers=headers, json={"q": "hello"}).status_code
        == 402
    )

    given = client.post(
        f"{ADMIN}/{user.id}/grants",
        headers=superuser_token_headers,
        json={"credits": 500, "reason": "Onboarding"},
    )
    assert given.status_code == 201, given.text
    assert given.json()["credits"] == 500.0
    assert given.json()["expired"] is False

    # Immediate, because the balance is derived rather than stored.
    after = client.get(ME, headers=headers).json()
    assert after["granted"] == 500.0
    assert after["remaining"] > 0


def test_a_grant_can_be_taken_back(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    grant = client.post(
        f"{ADMIN}/{user.id}/grants",
        headers=superuser_token_headers,
        json={"credits": 100},
    ).json()

    removed = client.delete(
        f"{ADMIN}/{user.id}/grants/{grant['id']}", headers=superuser_token_headers
    )
    assert removed.status_code == 200, removed.text
    listed = client.get(
        f"{ADMIN}/{user.id}/grants", headers=superuser_token_headers
    ).json()
    assert listed["count"] == 0


def test_a_grant_cannot_be_removed_through_another_account(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    one, _ = create_user_with_password(db)
    two, _ = create_user_with_password(db)
    grant = client.post(
        f"{ADMIN}/{one.id}/grants",
        headers=superuser_token_headers,
        json={"credits": 100},
    ).json()

    r = client.delete(
        f"{ADMIN}/{two.id}/grants/{grant['id']}", headers=superuser_token_headers
    )
    assert r.status_code == 404


def test_only_an_administrator_may_grant_credits(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)

    for r in (
        client.post(f"{ADMIN}/{user.id}/grants", headers=headers, json={"credits": 1}),
        client.get(f"{ADMIN}/{user.id}/grants", headers=headers),
        client.get(f"{ADMIN}/{user.id}", headers=headers),
    ):
        assert r.status_code == 403, r.text


def test_a_grant_for_an_unknown_account_is_refused(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{ADMIN}/{uuid.uuid4()}/grants",
        headers=superuser_token_headers,
        json={"credits": 10},
    )
    assert r.status_code == 404


def test_a_nonsense_grant_is_refused(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    for body in ({"credits": 0}, {"credits": -5}, {"credits": 10, "days": 0}):
        r = client.post(
            f"{ADMIN}/{user.id}/grants", headers=superuser_token_headers, json=body
        )
        assert r.status_code == 422, f"{body} was accepted"


# ------------------------------------------------------------- administration


def test_the_allowance_is_administered_like_every_other_limit(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """It is in the registry, so the admin form draws itself."""
    r = client.get(
        f"{API}/admin/user-groups/limits", headers=superuser_token_headers
    )
    assert r.status_code == 200, r.text
    keys = {limit["key"] for limit in r.json()["data"]}
    assert "monthly_credits" in keys


def test_a_group_can_be_given_its_own_allowance(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    made = client.post(
        f"{API}/admin/user-groups/",
        headers=superuser_token_headers,
        json={"name": f"Heavy {uuid.uuid4().hex[:6]}", "monthly_credits": 50_000},
    )
    assert made.status_code in (200, 201), made.text
    group_id = made.json()["id"]

    user, _ = create_user_with_password(db)
    moved = client.put(
        f"{API}/admin/users/{user.id}/assignment",
        headers=superuser_token_headers,
        json={"group_id": group_id, "overrides": {}},
    )
    assert moved.status_code == 200, moved.text

    db.refresh(user)
    balance = credits.balance_for(db, user)
    assert balance.allowance_milli == 50_000 * credits.MILLI
