"""Reading usage back: what a person sees, and what only an administrator does.

The load-bearing claim is the one at the bottom: cost is not merely hidden from
`/usage/me`, it is absent from the schema, so no later edit can put it there by
accident.
"""

import json
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import UsageFeature, UsageKind
from app.services import quota, usage
from tests.utils.kb import API, create_user_with_password, login

ME = f"{API}/usage/me"
SUMMARY = f"{API}/admin/usage/summary"
BREAKDOWN = f"{API}/admin/usage/breakdown"
MODELS = f"{API}/admin/usage/models"

CHAT = {
    "model": "qwen/qwen3.8-flash",
    "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "cost": 2.5e-05,
        "prompt_tokens_details": {"cached_tokens": 400},
    },
}
RERANK = {
    "model": "rerank-v4.0-fast",
    "usage": {"search_units": 1, "cost": 0.002},
}


def _spend(user_id: uuid.UUID, feature: UsageFeature, *, days_ago: int = 0) -> None:
    m = usage.UsageMeter(
        user_id=user_id,
        feature=feature,
        day=usage.today() - timedelta(days=days_ago),
    )
    m.operation()
    m.record(UsageKind.chat, CHAT, model="qwen/qwen3.8-flash")
    m.record(UsageKind.rerank, RERANK, model="cohere/rerank-4-fast")
    m.flush()


# --------------------------------------------------------------- my own usage


def test_my_usage_reports_what_i_did(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _spend(user.id, UsageFeature.ask)
    _spend(user.id, UsageFeature.search)

    r = client.get(ME, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["range"]["days"] == usage.DEFAULT_RANGE_DAYS
    assert body["totals"]["input_tokens"] == 2000
    assert body["totals"]["cached_tokens"] == 800

    features = {p["key"]: p for p in body["by_feature"]}
    assert set(features) == {"ask", "search"}
    assert features["ask"]["label"] == "Questions"

    assert len(body["by_day"]) == 1
    assert {p["key"] for p in body["by_model"]} == {
        "qwen/qwen3.8-flash",
        "rerank-v4.0-fast",
    }
    # The kind is the label, so a row with no tokens explains itself.
    models = {p["key"]: p["label"] for p in body["by_model"]}
    assert models["rerank-v4.0-fast"] == "rerank"


def test_my_usage_is_only_ever_mine(client: TestClient, db: Session) -> None:
    mine, pw = create_user_with_password(db)
    theirs, _ = create_user_with_password(db)
    headers = login(client, mine, pw)
    _spend(theirs.id, UsageFeature.ask)

    body = client.get(ME, headers=headers).json()
    assert body["totals"]["requests"] == 0
    assert body["by_feature"] == []


def test_a_range_can_be_asked_for_and_a_silly_one_refused(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _spend(user.id, UsageFeature.ask, days_ago=100)

    today = usage.today().isoformat()
    assert client.get(ME, headers=headers).json()["totals"]["requests"] == 0

    old = (usage.today() - timedelta(days=120)).isoformat()
    wide = client.get(ME, headers=headers, params={"from": old, "to": today})
    assert wide.json()["totals"]["requests"] > 0

    backwards = client.get(ME, headers=headers, params={"from": today, "to": old})
    assert backwards.status_code == 422, "the start is after the end"
    assert "after its end" in backwards.text

    huge = client.get(ME, headers=headers, params={"from": "2000-01-01", "to": today})
    assert huge.status_code == 422


def test_my_usage_needs_a_login(client: TestClient) -> None:
    assert client.get(ME).status_code == 401


# ----------------------------------------------------------------- admin side


def test_only_an_administrator_sees_the_bill(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    for url in (SUMMARY, BREAKDOWN, MODELS):
        assert client.get(url, headers=headers).status_code == 403, url
        assert client.get(url, headers=superuser_token_headers).status_code == 200, url


def test_the_summary_totals_everyone(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Two accounts, one figure - which is the whole point of the admin view.

    On a day of its own: this endpoint deliberately covers every account, and
    the suite truncates once per session, so anything on today's rows would be
    counted too.
    """
    one, _ = create_user_with_password(db)
    two, _ = create_user_with_password(db)
    _spend(one.id, UsageFeature.ask, days_ago=201)
    _spend(two.id, UsageFeature.import_, days_ago=201)

    day = (usage.today() - timedelta(days=201)).isoformat()
    body = client.get(
        SUMMARY, headers=superuser_token_headers, params={"from": day, "to": day}
    ).json()
    # Each account made one chat call at 2.5e-05 and one rerank at 0.002.
    assert body["totals"]["cost_nanos"] == 2 * (25_000 + 2_000_000)
    assert {p["key"] for p in body["by_feature"]} == {"ask", "import"}


def test_a_breakdown_names_the_account_and_its_group(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    spender, _ = create_user_with_password(db)
    spender.full_name = "Big Spender"
    db.add(spender)
    db.commit()
    _spend(spender.id, UsageFeature.ask)

    body = client.get(
        BREAKDOWN, headers=superuser_token_headers, params={"by": "user"}
    ).json()
    row = next(p for p in body["data"] if p["key"] == str(spender.id))
    assert row["label"] == "Big Spender"
    assert row["totals"]["cost_nanos"] > 0
    # No group is assigned, which resolves to the defaults rather than an error.
    assert row["group"] is None


def test_a_breakdown_can_be_scoped_to_one_group(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    inside, _ = create_user_with_password(db)
    outside, _ = create_user_with_password(db)
    inside.group_id = quota.default_group(db).id
    db.add(inside)
    db.commit()
    _spend(inside.id, UsageFeature.ask)
    _spend(outside.id, UsageFeature.ask)

    scoped = client.get(
        BREAKDOWN,
        headers=superuser_token_headers,
        params={"by": "user", "group_id": str(quota.default_group(db).id)},
    ).json()
    keys = {p["key"] for p in scoped["data"]}
    assert str(inside.id) in keys
    assert str(outside.id) not in keys

    unassigned = client.get(
        BREAKDOWN,
        headers=superuser_token_headers,
        params={"by": "user", "group_id": "none"},
    ).json()
    assert str(outside.id) in {p["key"] for p in unassigned["data"]}


def test_a_breakdown_by_model_puts_the_expensive_one_first(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    _spend(user.id, UsageFeature.search)

    body = client.get(
        BREAKDOWN, headers=superuser_token_headers, params={"by": "model"}
    ).json()
    assert body["data"][0]["key"] == "rerank-v4.0-fast", "0.002 beats 2.5e-05"


def test_an_unknown_breakdown_is_refused(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(BREAKDOWN, headers=superuser_token_headers, params={"by": "wat"})
    assert r.status_code == 422
    assert "user" in r.text


def test_the_model_filter_lists_what_has_actually_answered(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    user, _ = create_user_with_password(db)
    _spend(user.id, UsageFeature.ask)

    models = client.get(MODELS, headers=superuser_token_headers).json()
    assert "qwen/qwen3.8-flash" in models
    assert "rerank-v4.0-fast" in models


# --------------------------------------------------------------------- privacy


def test_cost_cannot_reach_the_person_who_spent_it(
    client: TestClient, db: Session
) -> None:
    """Not hidden - unrepresentable. `MyUsage` has no field to put it in."""
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    _spend(user.id, UsageFeature.ask)

    raw = client.get(ME, headers=headers).text
    assert "cost" not in raw.lower()
    assert "nanos" not in raw.lower()

    body = json.loads(raw)
    everywhere = [body["totals"], *(p["totals"] for p in body["by_feature"])]
    for totals in everywhere:
        assert "cost_nanos" not in totals


def test_a_group_name_never_reaches_a_member(client: TestClient, db: Session) -> None:
    """Groups are administrative, and `/usage/me` is not the place they leak."""
    user, pw = create_user_with_password(db)
    user.group_id = quota.default_group(db).id
    db.add(user)
    db.commit()
    headers = login(client, user, pw)
    _spend(user.id, UsageFeature.ask)

    assert (
        quota.default_group(db).name.lower()
        not in client.get(ME, headers=headers).text.lower()
    )


def test_an_api_key_cannot_read_the_bill(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """The superuser dependency chains off a session, so a key is not enough."""
    made = client.post(
        f"{API}/api-keys/",
        headers=superuser_token_headers,
        json={"name": "reader", "scope": "read"},
    )
    assert made.status_code in (200, 201), made.text
    key = made.json()["key"]
    r = client.get(SUMMARY, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403
