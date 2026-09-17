"""Credits: one number for work that is priced three different ways.

A knowledge base spends money in three shapes — tokens through a chat model,
calls to an embedding model, calls to a reranker — and a limit expressed in any
one of them is meaningless for the others. A thousand-token limit says nothing
about reranking; a call limit treats a one-line question and a hundred-page
import as the same thing.

So there is one unit:

    1 credit  =  1,000 tokens  =  10 embeddings  =  10 rerank calls

Everything is stored in **milli-credits**, which makes the arithmetic exact and,
pleasingly, makes the rate trivial: **one token is one milli-credit**, and an
embedding or rerank call is a hundred. No floats anywhere near the ledger.

## What an account has

    remaining  =  allowance + live grants − used this month

* **allowance** resolves through the same four tiers as every other limit —
  the account's own override, its group, the default group, a constant — so an
  administrator raises it for one person or a whole class without new
  machinery. See `app/services/quota.py`.
* **grants** are an administrator topping somebody up by hand.
* **used** is read from `usagedaily`, which the meter already writes. There is
  no second ledger to keep in step, and no counter that can drift: the balance
  is a function of rows that were written for another reason entirely.

That last point is what makes this real-time and cheap. Every check is two
aggregates over indexed columns, and it is impossible for the balance to
disagree with the usage page, because they are the same rows.

## Why a grant expires

The allowance renews monthly, so it does not accumulate: an account gets a
thousand credits in March whether or not it spent February's. A grant that
never expired would behave differently — it would sit on the balance for ever,
and tracking how much of it had been consumed would need exactly the stored,
driftable counter this design avoids.

So a grant has an end date, defaulting to the end of the month it was given in,
which is when the allowance renews anyway. A **permanent** raise is a different
thing and has its own tool: the account's `monthly_credits` override.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from app.models import (
    CreditBalance,
    CreditGrant,
    UsageDaily,
    UsageFeature,
    UsageKind,
    User,
    UserGroup,
)
from app.services import quota

logger = logging.getLogger(__name__)

# A credit, in the unit everything is stored in.
MILLI = 1000

# What each kind of work costs, in milli-credits.
#
# One token is one milli-credit, which is the whole reason for the unit. A call
# to an embedding model or a reranker is a tenth of a credit however big it is,
# because those are priced per call rather than per token - a reranker charges
# one search unit whether it scores five documents or fifty.
PER_TOKEN = 1
PER_EMBEDDING_CALL = 100
PER_RERANK_CALL = 100
# Speech to text is priced per second of audio, so it is charged that way.
#
# Twenty milli-credits a second is 1.2 credits a minute, which at the going
# rate for a turbo ASR model is within about a tenth of what a credit's worth
# of tokens costs. That parity is the point: the unit has to mean the same
# thing whichever way the work was spent, or an allowance stops being a budget.
# It also rounds to a sentence somebody can hold - about a credit a minute.
PER_AUDIO_SECOND = 20

# Features grouped the way somebody reading their own balance thinks about it.
ANSWER_FEATURES = (UsageFeature.ask, UsageFeature.agent)
SEARCH_FEATURES = (UsageFeature.search,)
INDEXING_FEATURES = (UsageFeature.import_, UsageFeature.indexing)
# Everything the three buckets above do not name. Spelled as "the rest" rather
# than as a list, so a feature added later lands in the balance by itself
# instead of quietly falling out of the total somebody is shown.
OTHER_FEATURES = tuple(
    feature
    for feature in UsageFeature
    if feature not in ANSWER_FEATURES + SEARCH_FEATURES + INDEXING_FEATURES
)


class CreditsExhausted(Exception):
    """An account has nothing left to spend this month.

    Deliberately not an ``HTTPException``: the worker runs into this too and
    has to fail a job rather than raise into a request. Routes turn it into a
    402, which is the one status that means exactly this.
    """


@dataclass(frozen=True, slots=True)
class Period:
    """A calendar month in UTC - the window an allowance covers."""

    year: int
    month: int

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return date(
            self.year, self.month, calendar.monthrange(self.year, self.month)[1]
        )

    @property
    def ends_at(self) -> datetime:
        """The instant the allowance renews: midnight UTC on the 1st."""
        return datetime.combine(
            self.last_day + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )


def current_period(now: datetime | None = None) -> Period:
    moment = now or datetime.now(UTC)
    return Period(year=moment.year, month=moment.month)


def cost_of(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    embedding_calls: int = 0,
    rerank_calls: int = 0,
    audio_seconds: int = 0,
) -> int:
    """What that work costs, in milli-credits.

    Cached tokens are charged like any other. They are cheaper for us, not free,
    and a limit that moved with how well the provider's cache happened to be
    doing would be impossible for anybody to plan against.
    """
    return (
        (input_tokens + output_tokens) * PER_TOKEN
        + embedding_calls * PER_EMBEDDING_CALL
        + rerank_calls * PER_RERANK_CALL
        + audio_seconds * PER_AUDIO_SECOND
    )


def _spent_expression() -> Any:
    """Milli-credits, summed straight out of the usage rows in SQL.

    Computed here rather than in Python because the alternative is pulling
    every row of a month back to add it up, and this is on the path of every
    metered operation.
    """
    tokens = func.coalesce(func.sum(UsageDaily.input_tokens), 0) + func.coalesce(
        func.sum(UsageDaily.output_tokens), 0
    )
    embeddings = func.coalesce(
        func.sum(
            case(
                (
                    col(UsageDaily.kind) == UsageKind.embedding.value,
                    UsageDaily.requests,
                ),
                else_=0,
            )
        ),
        0,
    )
    reranks = func.coalesce(
        func.sum(
            case(
                (col(UsageDaily.kind) == UsageKind.rerank.value, UsageDaily.requests),
                else_=0,
            )
        ),
        0,
    )
    # Summed over every row rather than filtered by kind: only transcription
    # writes this column, and a sum is cheaper than a CASE that says so.
    audio = func.coalesce(func.sum(UsageDaily.audio_seconds), 0)
    return (
        tokens * PER_TOKEN
        + embeddings * PER_EMBEDDING_CALL
        + reranks * PER_RERANK_CALL
        + audio * PER_AUDIO_SECOND
    )


def spent_milli(
    session: Session,
    user_id: uuid.UUID,
    *,
    period: Period | None = None,
    features: tuple[UsageFeature, ...] | None = None,
) -> int:
    """What this account has spent in the period, in milli-credits."""
    window = period or current_period()
    statement = select(_spent_expression()).where(
        UsageDaily.user_id == user_id,
        col(UsageDaily.day) >= window.first_day,
        col(UsageDaily.day) <= window.last_day,
        # `feature` rows count what a person did, not what was called to do it;
        # charging them would bill the same work twice.
        col(UsageDaily.kind) != UsageKind.feature.value,
    )
    if features is not None:
        statement = statement.where(
            col(UsageDaily.feature).in_([f.value for f in features])
        )
    return int(session.exec(statement).one() or 0)


def granted_milli(
    session: Session, user_id: uuid.UUID, *, now: datetime | None = None
) -> int:
    """One-off credits still live for this account."""
    moment = now or datetime.now(UTC)
    total = session.exec(
        select(func.coalesce(func.sum(CreditGrant.amount_milli), 0)).where(
            CreditGrant.user_id == user_id,
            col(CreditGrant.expires_at) > moment,
        )
    ).one()
    return int(total or 0)


@dataclass(frozen=True, slots=True)
class Balance:
    period: Period
    allowance_milli: int
    granted_milli: int
    used_milli: int

    @property
    def total_milli(self) -> int:
        return self.allowance_milli + self.granted_milli

    @property
    def remaining_milli(self) -> int:
        return self.total_milli - self.used_milli

    @property
    def exhausted(self) -> bool:
        return self.remaining_milli <= 0


def balance_for(
    session: Session,
    user: User,
    *,
    groups: dict[uuid.UUID, UserGroup] | None = None,
    now: datetime | None = None,
) -> Balance:
    """What this account has left, right now.

    Two aggregates over indexed columns and one resolver walk. Cheap enough to
    run before every metered operation, which is the point: a limit checked
    hourly is a limit somebody can drive straight through.
    """
    window = current_period(now)
    limits = quota.resolve_limits(session, user, groups=groups)
    return Balance(
        period=window,
        allowance_milli=max(0, limits.monthly_credits) * MILLI,
        granted_milli=granted_milli(session, user.id, now=now),
        used_milli=spent_milli(session, user.id, period=window),
    )


def ensure_credit(
    session: Session,
    user: User | None,
    *,
    groups: dict[uuid.UUID, UserGroup] | None = None,
) -> None:
    """Refuse the work if there is nothing left to pay for it.

    Checked once at the start of an operation rather than before every call
    inside it. An Ask that runs a few hundred credits past zero on its last
    question is not worth the cost of re-checking mid-flight; what matters is
    that the *next* one is refused, and it is.

    A missing account is not refused: work that belongs to nobody - indexing a
    page whose author was deleted - is not chargeable to anybody either.
    """
    if user is None:
        return
    if user.is_superuser:
        # The operator of the installation is not metered out of their own
        # instance, for the same reason they get a large page allowance.
        return
    balance = balance_for(session, user, groups=groups)
    if balance.exhausted:
        raise CreditsExhausted(message_for(balance))


def message_for(balance: Balance) -> str:
    """What to tell somebody who has run out. Names the number and the date."""
    renews = balance.period.ends_at.strftime("%-d %B")
    return (
        f"You have used all {as_credits(balance.total_milli):g} credits for "
        f"{balance.period.key}. They renew on {renews}; an administrator can "
        "also raise the limit or add credits."
    )


def as_credits(milli: int) -> float:
    """Milli-credits as the number a person is shown, to three decimals."""
    return round(milli / MILLI, 3)


def to_public(balance: Balance, session: Session, user: User) -> CreditBalance:
    """The balance, with the spend broken down by what it went on."""
    window = balance.period
    return CreditBalance(
        period=window.key,
        renews_at=window.ends_at,
        allowance=as_credits(balance.allowance_milli),
        granted=as_credits(balance.granted_milli),
        used=as_credits(balance.used_milli),
        remaining=as_credits(max(0, balance.remaining_milli)),
        used_on_answers=as_credits(
            spent_milli(session, user.id, period=window, features=ANSWER_FEATURES)
        ),
        used_on_search=as_credits(
            spent_milli(session, user.id, period=window, features=SEARCH_FEATURES)
        ),
        used_on_indexing=as_credits(
            spent_milli(session, user.id, period=window, features=INDEXING_FEATURES)
        ),
        used_on_other=as_credits(
            spent_milli(
                session,
                user.id,
                period=window,
                features=OTHER_FEATURES,
            )
        ),
    )


def grant(
    session: Session,
    user: User,
    *,
    credits: int,
    reason: str = "",
    days: int | None = None,
    granted_by: uuid.UUID | None = None,
    now: datetime | None = None,
) -> CreditGrant:
    """Top an account up by hand.

    Ends when the month does unless told otherwise, because that is when the
    allowance renews and a top-up that outlived it would quietly become part of
    the allowance.
    """
    moment = now or datetime.now(UTC)
    expires = moment + timedelta(days=days) if days else current_period(moment).ends_at
    row = CreditGrant(
        user_id=user.id,
        amount_milli=credits * MILLI,
        reason=reason.strip()[:300],
        granted_by=granted_by,
        expires_at=expires,
    )
    session.add(row)
    return row


def grants_for(
    session: Session, user_id: uuid.UUID, *, limit: int = 100
) -> list[CreditGrant]:
    return list(
        session.exec(
            select(CreditGrant)
            .where(CreditGrant.user_id == user_id)
            .order_by(col(CreditGrant.created_at).desc())
            .limit(limit)
        ).all()
    )


def spent_for(
    session: Session, user_ids: list[uuid.UUID], *, period: Period | None = None
) -> dict[uuid.UUID, int]:
    """Milli-credits spent by each of these accounts, in one query.

    The admin table shows a balance per row; without this it would be one
    aggregate per account, which is the shape that made the page slow last time.
    """
    if not user_ids:
        return {}
    window = period or current_period()
    spent = dict.fromkeys(user_ids, 0)
    rows = session.exec(
        select(col(UsageDaily.user_id), _spent_expression())
        .where(
            col(UsageDaily.user_id).in_(user_ids),
            col(UsageDaily.day) >= window.first_day,
            col(UsageDaily.day) <= window.last_day,
            col(UsageDaily.kind) != UsageKind.feature.value,
        )
        .group_by(col(UsageDaily.user_id))
    ).all()
    for user_id, total in rows:
        spent[user_id] = int(total or 0)
    return spent


def granted_for(
    session: Session, user_ids: list[uuid.UUID], *, now: datetime | None = None
) -> dict[uuid.UUID, int]:
    """Live grants for each of these accounts, in one query."""
    if not user_ids:
        return {}
    moment = now or datetime.now(UTC)
    granted = dict.fromkeys(user_ids, 0)
    rows = session.exec(
        select(
            col(CreditGrant.user_id),
            func.coalesce(func.sum(CreditGrant.amount_milli), 0),
        )
        .where(
            col(CreditGrant.user_id).in_(user_ids),
            col(CreditGrant.expires_at) > moment,
        )
        .group_by(col(CreditGrant.user_id))
    ).all()
    for user_id, total in rows:
        granted[user_id] = int(total or 0)
    return granted
