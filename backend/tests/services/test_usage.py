"""Metering: what is read off a response, and how it lands in a daily row.

The payloads here are copied from live OpenRouter responses rather than
invented, because the shape of `usage` is the whole contract this module has
with the outside world.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import UsageDaily, UsageFeature, UsageKind, User
from app.services import usage
from tests.utils.kb import create_user_with_password

# A real chat completion, trimmed to the parts this module reads.
CHAT_BODY = {
    "id": "gen-1789482048-0NJ5G7yugqnf9KbMTAns",
    "model": "qwen/qwen3.8-flash",
    "provider": "Alibaba",
    "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
    "usage": {
        "prompt_tokens": 31,
        "completion_tokens": 1,
        "total_tokens": 32,
        "cost": 5.12e-06,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": 4, "cache_write_tokens": 7},
        "completion_tokens_details": {"reasoning_tokens": 2},
    },
}

# A real rerank response: billed per search unit, with no tokens at all.
RERANK_BODY = {
    "id": "gen-rerank-1789482080-CJZy8TXbWbOXnJmxFkCd",
    "model": "rerank-v4.0-fast",
    "results": [],
    "usage": {"search_units": 1, "cost": 0.002},
    "provider": "Cohere",
}


def _rows(user_id: uuid.UUID) -> list[UsageDaily]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(UsageDaily)
                .where(UsageDaily.user_id == user_id)
                .order_by(col(UsageDaily.kind), col(UsageDaily.model))
            ).all()
        )


@pytest.fixture
def user(db: Session) -> User:
    account, _ = create_user_with_password(db)
    return account


# --------------------------------------------------------------- reading it


def test_every_counter_is_read_off_a_real_response() -> None:
    counts = usage.read_usage(CHAT_BODY)
    assert counts.requests == 1
    assert counts.input_tokens == 31
    assert counts.output_tokens == 1
    assert counts.cached_tokens == 4
    assert counts.cache_write_tokens == 7
    assert counts.reasoning_tokens == 2
    # Dollars, as an integer number of nanos.
    assert counts.cost_nanos == 5120


def test_rerank_is_billed_in_search_units_and_has_no_tokens() -> None:
    counts = usage.read_usage(RERANK_BODY)
    assert counts.search_units == 1
    assert counts.cost_nanos == 2_000_000
    assert counts.input_tokens == 0


def test_a_response_without_a_usage_block_still_counts_as_a_call() -> None:
    """A local server reports no usage, and the call still happened."""
    counts = usage.read_usage({"choices": [{"message": {"content": "hi"}}]})
    assert counts.requests == 1
    assert counts.cost_nanos == 0


def test_a_missing_details_object_costs_a_number_not_an_answer() -> None:
    body = {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    counts = usage.read_usage(body)
    assert (counts.input_tokens, counts.cached_tokens) == (10, 0)


def test_the_model_recorded_is_the_one_that_answered() -> None:
    """The requested id is a guess when the provider may re-route."""
    assert usage.response_model(CHAT_BODY, "qwen/qwen3.7-flash") == "qwen/qwen3.8-flash"
    assert usage.response_model({}, "qwen/qwen3.7-flash") == "qwen/qwen3.7-flash"


# --------------------------------------------------------------- writing it


def test_calls_in_one_request_become_one_row_per_model(user: User) -> None:
    with usage.meter(user.id, UsageFeature.ask) as m:
        m.operation()
        m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")
        m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")
        m.record(UsageKind.rerank, RERANK_BODY, model="cohere/rerank-4-fast")

    rows = _rows(user.id)
    assert len(rows) == 3, "one bookkeeping row, one chat model, one reranker"
    chat = next(r for r in rows if r.kind == UsageKind.chat)
    assert chat.requests == 2
    assert chat.input_tokens == 62
    assert chat.cost_nanos == 10_240

    marker = next(r for r in rows if r.kind == UsageKind.feature)
    assert marker.requests == 1
    assert marker.model == "", "a feature row names no model"


def test_a_second_request_adds_to_the_same_day(user: User) -> None:
    """The property the whole design rests on: the UPSERT adds, never replaces."""
    for _ in range(3):
        with usage.meter(user.id, UsageFeature.ask) as m:
            m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")

    rows = _rows(user.id)
    assert len(rows) == 1
    assert rows[0].requests == 3
    assert rows[0].cost_nanos == 15_360


def test_two_sessions_writing_at_once_do_not_lose_each_other(user: User) -> None:
    """Interleaved, uncommitted, then committed - no read-modify-write anywhere."""
    first = usage.UsageMeter(user_id=user.id, feature=UsageFeature.search)
    second = usage.UsageMeter(user_id=user.id, feature=UsageFeature.search)
    first.record(UsageKind.embedding, CHAT_BODY, model="qwen/qwen3.8-flash")
    second.record(UsageKind.embedding, CHAT_BODY, model="qwen/qwen3.8-flash")

    with Session(engine) as a, Session(engine) as b:
        usage._upsert(a, first.rows())
        a.commit()
        usage._upsert(b, second.rows())
        b.commit()

    rows = _rows(user.id)
    assert len(rows) == 1
    assert rows[0].requests == 2


def test_a_failed_call_records_a_failure_and_no_tokens(user: User) -> None:
    with usage.meter(user.id, UsageFeature.translation) as m:
        m.failure(UsageKind.chat, "qwen/qwen3.7-flash")

    rows = _rows(user.id)
    assert len(rows) == 1
    assert (rows[0].failures, rows[0].requests, rows[0].cost_nanos) == (1, 0, 0)


def test_work_belonging_to_nobody_is_not_recorded() -> None:
    """Indexing a page whose author was deleted is attributed to no account."""
    with usage.meter(None, UsageFeature.import_) as m:
        m.operation()
        m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")
        assert m.rows() == []


def test_metering_never_breaks_the_thing_it_is_measuring(user: User) -> None:
    """A row that cannot be written is a log line, not an exception.

    A request's rows go in as one statement, so one bad bucket loses the lot.
    That is the right trade: `_bucket` truncates the model name, so reaching
    here at all means something unforeseen, and an answer is worth more than
    its accounting.
    """
    m = usage.UsageMeter(user_id=user.id, feature=UsageFeature.ask)
    m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")
    m.buckets[(UsageKind.chat, "x" * 400)] = usage.Counts(requests=1)
    m.flush()  # the over-long model name fails the insert
    assert _rows(user.id) == [], "the whole statement rolled back"
    assert m.buckets == {}, "and it does not hold on to what it could not write"


def test_flushing_twice_writes_once(user: User) -> None:
    m = usage.UsageMeter(user_id=user.id, feature=UsageFeature.ask)
    m.operation()
    m.flush()
    m.flush()
    assert _rows(user.id)[0].requests == 1


# --------------------------------------------------------------- reading back


def test_a_range_is_inclusive_at_both_ends_and_bounded() -> None:
    rng = usage.resolve_range(date(2026, 9, 1), date(2026, 9, 30))
    assert rng.days == 30
    with pytest.raises(ValueError):
        usage.resolve_range(date(2026, 9, 30), date(2026, 9, 1))
    with pytest.raises(ValueError):
        usage.resolve_range(date(2020, 1, 1), date(2026, 9, 1))


def test_an_open_range_ends_today() -> None:
    rng = usage.resolve_range(None, None)
    assert rng.to == usage.today()
    assert rng.days == usage.DEFAULT_RANGE_DAYS


def test_breakdowns_group_what_was_recorded(db: Session, user: User) -> None:
    with usage.meter(user.id, UsageFeature.ask) as m:
        m.operation()
        m.record(UsageKind.chat, CHAT_BODY, model="qwen/qwen3.8-flash")
    with usage.meter(user.id, UsageFeature.search) as m:
        m.operation()
        m.record(UsageKind.rerank, RERANK_BODY, model="cohere/rerank-4-fast")

    q = usage.Query(rng=usage.resolve_range(None, None), user_ids=[user.id])
    assert usage.totals(db, q).cost_nanos == 5120 + 2_000_000

    features = dict(usage.by_feature(db, q))
    assert set(features) == {"ask", "search"}
    assert features["ask"].input_tokens == 31

    models = usage.by_model(db, q)
    assert {m[0] for m in models} == {"qwen/qwen3.8-flash", "rerank-v4.0-fast"}
    assert models[0][0] == "rerank-v4.0-fast", "largest spend first"

    days = usage.by_day(db, q)
    assert len(days) == 1 and days[0][0] == usage.today()


def test_a_range_excludes_days_outside_it(db: Session, user: User) -> None:
    old = usage.UsageMeter(
        user_id=user.id,
        feature=UsageFeature.ask,
        day=usage.today() - timedelta(days=90),
    )
    old.operation()
    old.flush()

    recent = usage.Query(rng=usage.resolve_range(None, None), user_ids=[user.id])
    assert usage.totals(db, recent).requests == 0

    wide = usage.Query(
        rng=usage.resolve_range(usage.today() - timedelta(days=100), None),
        user_ids=[user.id],
    )
    assert usage.totals(db, wide).requests == 1


def test_usage_dies_with_the_account(db: Session) -> None:
    account, _ = create_user_with_password(db)
    account_id = account.id
    with usage.meter(account_id, UsageFeature.ask) as m:
        m.operation()
    assert _rows(account_id)

    db.delete(account)
    db.commit()
    assert _rows(account_id) == []
