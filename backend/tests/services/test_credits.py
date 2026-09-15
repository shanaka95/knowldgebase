"""Credits: the arithmetic, and the moment somebody is refused.

The claim under test is that the balance is a *function of the usage rows* —
there is no second ledger to keep in step, so the balance can never disagree
with the usage page. Most of these tests therefore write usage and read a
balance, rather than writing a balance at all.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.models import UsageFeature, UsageKind, User
from app.services import credits, quota, usage
from tests.utils.kb import create_user_with_password


def _spend(
    user_id: uuid.UUID,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    embeddings: int = 0,
    reranks: int = 0,
    feature: UsageFeature = UsageFeature.ask,
    day=None,
) -> None:
    """Write usage the way the meter does, so the balance reads real rows."""
    meter = usage.UsageMeter(user_id=user_id, feature=feature, day=day or usage.today())
    if input_tokens or output_tokens:
        meter.record_counts(
            UsageKind.chat,
            "qwen/qwen3.8-flash",
            usage.Counts(
                requests=1, input_tokens=input_tokens, output_tokens=output_tokens
            ),
        )
    for _ in range(embeddings):
        meter.record_counts(UsageKind.embedding, "embed-1", usage.Counts(requests=1))
    for _ in range(reranks):
        meter.record_counts(UsageKind.rerank, "rerank-1", usage.Counts(requests=1))
    meter.flush()


@pytest.fixture
def account(db: Session) -> User:
    user, _ = create_user_with_password(db)
    return user


# ------------------------------------------------------------- the exchange rate


def test_one_credit_is_a_thousand_tokens_or_ten_calls() -> None:
    """The three prices are the same price, which is the point of the unit."""
    a_credit = credits.MILLI
    assert credits.cost_of(input_tokens=1000) == a_credit
    assert credits.cost_of(output_tokens=1000) == a_credit
    assert credits.cost_of(embedding_calls=10) == a_credit
    assert credits.cost_of(rerank_calls=10) == a_credit
    # And a token is exactly a milli-credit, which is why there are no floats.
    assert credits.cost_of(input_tokens=1) == 1


def test_a_month_knows_when_it_ends() -> None:
    period = credits.current_period(datetime(2026, 2, 17, tzinfo=UTC))
    assert period.key == "2026-02"
    assert period.first_day.day == 1
    assert period.last_day.day == 28, "2026 is not a leap year"
    # Renewal is midnight on the 1st, not the last instant of the 28th.
    assert period.ends_at == datetime(2026, 3, 1, tzinfo=UTC)


# ------------------------------------------------------------------- the balance


def test_the_balance_is_read_from_the_usage_rows(db: Session, account: User) -> None:
    before = credits.balance_for(db, account)
    assert before.used_milli == 0
    assert before.allowance_milli == settings.MONTHLY_CREDITS * credits.MILLI

    _spend(account.id, input_tokens=1500, output_tokens=500, embeddings=10, reranks=5)

    after = credits.balance_for(db, account)
    # 2000 tokens = 2 credits; 10 embeddings = 1; 5 reranks = 0.5.
    assert after.used_milli == 3500
    assert after.remaining_milli == after.total_milli - 3500


def test_only_the_current_month_counts(db: Session, account: User) -> None:
    """An allowance that renews is an allowance last month cannot eat."""
    last_month = usage.today().replace(day=1) - timedelta(days=1)
    _spend(account.id, input_tokens=900_000, day=last_month)

    assert credits.balance_for(db, account).used_milli == 0


def test_bookkeeping_rows_are_not_charged(db: Session, account: User) -> None:
    """A `feature` row counts what somebody did, not what was called to do it."""
    meter = usage.UsageMeter(user_id=account.id, feature=UsageFeature.search)
    meter.operation()
    meter.flush()

    assert credits.balance_for(db, account).used_milli == 0


def test_a_grant_adds_to_the_balance_and_then_expires(
    db: Session, account: User
) -> None:
    base = credits.balance_for(db, account).total_milli

    credits.grant(db, account, credits=250, reason="Migration backlog")
    db.commit()
    assert credits.balance_for(db, account).total_milli == base + 250 * credits.MILLI

    # Past its end date it stops counting, without anything having to sweep it.
    later = credits.current_period().ends_at + timedelta(seconds=1)
    assert credits.granted_milli(db, account.id, now=later) == 0


def test_a_grant_ends_with_the_month_unless_told_otherwise(
    db: Session, account: User
) -> None:
    default = credits.grant(db, account, credits=10)
    longer = credits.grant(db, account, credits=10, days=90)
    db.commit()

    assert default.expires_at == credits.current_period().ends_at
    assert longer.expires_at > credits.current_period().ends_at


# ---------------------------------------------------------------- the refusal


def test_an_account_with_nothing_left_is_refused(db: Session, account: User) -> None:
    account.monthly_credits = 1
    db.add(account)
    db.commit()

    credits.ensure_credit(db, account)  # one credit is still one credit

    _spend(account.id, input_tokens=1000)
    with pytest.raises(credits.CreditsExhausted) as refused:
        credits.ensure_credit(db, account)

    # The message names the number and the date, so it can be acted on.
    assert "1 credits" in str(refused.value) or "1 " in str(refused.value)
    assert credits.current_period().key in str(refused.value)


def test_a_grant_buys_more_room(db: Session, account: User) -> None:
    account.monthly_credits = 1
    db.add(account)
    db.commit()
    _spend(account.id, input_tokens=1000)
    with pytest.raises(credits.CreditsExhausted):
        credits.ensure_credit(db, account)

    credits.grant(db, account, credits=5, reason="One-off")
    db.commit()
    credits.ensure_credit(db, account)  # no longer refused


def test_work_belonging_to_nobody_is_never_refused(db: Session) -> None:
    credits.ensure_credit(db, None)


def test_the_operator_is_not_metered_out_of_their_own_instance(
    db: Session, account: User
) -> None:
    account.monthly_credits = 0
    account.is_superuser = True
    db.add(account)
    db.commit()
    credits.ensure_credit(db, account)


def test_the_allowance_resolves_through_the_group(db: Session, account: User) -> None:
    """Same four tiers as every other limit, because it is one of them."""
    assert "monthly_credits" in quota.LIMIT_KEYS

    group = quota.default_group(db)
    assert group is not None
    original = group.monthly_credits
    try:
        group.monthly_credits = 42
        db.add(group)
        db.commit()
        assert credits.balance_for(db, account).allowance_milli == 42 * credits.MILLI

        # An account's own override beats its group.
        account.monthly_credits = 7
        db.add(account)
        db.commit()
        assert credits.balance_for(db, account).allowance_milli == 7 * credits.MILLI
    finally:
        group.monthly_credits = original
        db.add(group)
        db.commit()


# ------------------------------------------------------------------ in batches


def test_balances_for_many_accounts_are_read_in_two_queries(
    db: Session, account: User
) -> None:
    """The admin table shows a balance per row; per-row queries made it slow."""
    other, _ = create_user_with_password(db)
    _spend(account.id, input_tokens=2000)
    credits.grant(db, other, credits=3)
    db.commit()

    ids = [account.id, other.id]
    spent = credits.spent_for(db, ids)
    granted = credits.granted_for(db, ids)

    assert spent[account.id] == 2000
    assert spent[other.id] == 0, "an account with no usage reads as zero, not absent"
    assert granted[other.id] == 3 * credits.MILLI
    assert granted[account.id] == 0
