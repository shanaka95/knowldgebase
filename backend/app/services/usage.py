"""What each account spent, by day and by model.

Every response from an OpenAI-compatible provider carries a ``usage`` block,
and OpenRouter's carries a reconciled ``cost`` as well. This module is the only
place that reads them.

The questions asked of that data are always the same three - whose, which day,
which model - so that is the shape of the row. Calls accumulate in a
:class:`UsageMeter` for the length of one request or job, and :meth:`flush`
folds them into daily rows with an UPSERT that *adds* to the counters. That is
atomic per row, so two requests finishing at the same moment cannot lose each
other's numbers; contrast ``quota.lock_user_quota``, which needs an advisory
lock precisely because counting pages is a read-then-write.

Two things this deliberately does not have:

* **No price table.** The provider prices the call and tells us. A price list
  in the repository would be a second source of truth, and a stale one within
  the month. A self-hosted server reports no cost, and 0 is correct there.
* **No rollup and no retention job.** Rows are written at the granularity they
  are read at, and history is kept.

The meter is passed explicitly rather than carried in a ``ContextVar``. A
context set in a FastAPI dependency is gone by the time a ``StreamingResponse``
iterates its body, which is exactly where an Ask answer is generated - the same
reason ``ask.save_answer`` opens a session of its own. Explicit also makes a
meter of ``None`` an ordinary, testable state: unmetered.

**Metering must never break a feature.** :meth:`flush` swallows what it can and
logs; an answer is worth more than its accounting.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, func, select

from app.core.db import engine
from app.models import UsageDaily, UsageFeature, UsageKind, User

logger = logging.getLogger(__name__)

# The counters an UPSERT adds together. Named once so the insert, the conflict
# clause and the aggregate queries cannot drift apart.
COUNTERS: tuple[str, ...] = (
    "requests",
    "failures",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "search_units",
    "cost_nanos",
)

# The kinds that name a model. `feature` rows do not - they count what a person
# did, not what was called to do it.
MODEL_KINDS: tuple[UsageKind, ...] = (
    UsageKind.chat,
    UsageKind.embedding,
    UsageKind.rerank,
)

# US dollars are stored multiplied by this, as an integer. A year of summing
# floats drifts; this does not.
NANOS = 1_000_000_000


def today() -> date:
    """The day a call is attributed to.

    UTC, and the interface says so. Any other choice needs a timezone per
    account, and "today" would then mean different rows for different readers
    of the same admin dashboard.
    """
    return datetime.now(UTC).date()


@dataclass(slots=True)
class Counts:
    """One bucket's worth of numbers, before they reach the database."""

    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    search_units: int = 0
    cost_nanos: int = 0

    def add(self, other: Counts) -> None:
        for name in COUNTERS:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def _int(value: Any) -> int:
    """A provider's number, or 0. Never raises - this is accounting, not logic."""
    try:
        return int(value)
    except TypeError, ValueError:
        return 0


def read_usage(body: Any) -> Counts:
    """Pull the counters out of one provider response.

    Tolerant on purpose: providers differ over which sub-objects they send, and
    a missing ``prompt_tokens_details`` must cost a token count, not an answer.
    """
    counts = Counts(requests=1)
    if not isinstance(body, dict):
        return counts
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return counts

    counts.input_tokens = _int(usage.get("prompt_tokens"))
    counts.output_tokens = _int(usage.get("completion_tokens"))
    counts.search_units = _int(usage.get("search_units"))

    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        counts.cached_tokens = _int(prompt_details.get("cached_tokens"))
        counts.cache_write_tokens = _int(prompt_details.get("cache_write_tokens"))

    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        counts.reasoning_tokens = _int(completion_details.get("reasoning_tokens"))

    cost = usage.get("cost")
    if isinstance(cost, int | float) and not isinstance(cost, bool):
        counts.cost_nanos = round(float(cost) * NANOS)
    return counts


def response_model(body: Any, fallback: str) -> str:
    """Which model actually answered.

    Not the one we asked for. A request carrying a ``models`` array lets the
    provider re-route server-side, so the requested id is a guess and the
    response's is the fact - which is the whole point of metering per model:
    knowing when the expensive fallback served the answer.
    """
    if isinstance(body, dict):
        served = body.get("model")
        if isinstance(served, str) and served:
            return served[:160]
    return fallback[:160]


@dataclass(slots=True)
class UsageMeter:
    """Accumulates one request's or one job's calls, then writes them once.

    A meter with no ``user_id`` records nothing. That is not an error state:
    indexing a page whose author has been deleted is work that belongs to
    nobody, the same reading ``docs/LIMITS.md`` takes of an orphaned page.
    """

    user_id: uuid.UUID | None
    feature: UsageFeature
    day: date = field(default_factory=today)
    buckets: dict[tuple[UsageKind, str], Counts] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.user_id is not None

    def _bucket(self, kind: UsageKind, model: str) -> Counts:
        key = (kind, model[:160])
        counts = self.buckets.get(key)
        if counts is None:
            counts = Counts()
            self.buckets[key] = counts
        return counts

    def operation(self, n: int = 1) -> None:
        """Record that the person did the thing once.

        Separate from the model calls because the two disagree in both
        directions: a cached search makes no call at all, and a call that fell
        through to a fallback model makes several.
        """
        if not self.enabled:
            return
        self._bucket(UsageKind.feature, "").requests += n

    def record(self, kind: UsageKind, body: Any, *, model: str) -> None:
        """Record one successful call from its parsed response body."""
        if not self.enabled:
            return
        self._bucket(kind, response_model(body, model)).add(read_usage(body))

    def record_counts(self, kind: UsageKind, model: str, counts: Counts) -> None:
        """Record a call whose numbers were gathered elsewhere - the SSE tail."""
        if not self.enabled:
            return
        self._bucket(kind, model).add(counts)

    def failure(self, kind: UsageKind, model: str) -> None:
        """Record a call that raised. It returned no usage and cost nothing."""
        if not self.enabled:
            return
        self._bucket(kind, model).failures += 1

    def rows(self) -> list[dict[str, Any]]:
        if self.user_id is None:
            return []
        return [
            {
                "id": uuid.uuid4(),
                "day": self.day,
                "user_id": self.user_id,
                "feature": self.feature.value,
                "kind": kind.value,
                "model": model,
                **{name: getattr(counts, name) for name in COUNTERS},
            }
            for (kind, model), counts in self.buckets.items()
        ]

    def flush(self, session: Session | None = None) -> None:
        """Write what was gathered, and forget it.

        Its own connection by default: the caller's session may be long gone
        (the Ask stream) or mid-transaction with work that has nothing to do
        with accounting. Safe to call twice - the buckets are cleared, so the
        second call writes nothing.
        """
        rows = self.rows()
        self.buckets = {}
        if not rows:
            return
        try:
            if session is not None:
                _upsert(session, rows)
                session.commit()
            else:
                with Session(engine) as own:
                    _upsert(own, rows)
                    own.commit()
        except Exception:  # noqa: BLE001 - accounting must not break a feature
            logger.warning(
                "usage: could not record %d row(s)", len(rows), exc_info=True
            )


def _upsert(session: Session, rows: list[dict[str, Any]]) -> None:
    """Add these numbers to whatever is already there for the same buckets.

    ``col = col + EXCLUDED.col`` is what makes this safe without a lock: the
    row is held only for the duration of its own update, and two requests
    finishing together add rather than overwrite.
    """
    statement = pg_insert(UsageDaily).values(rows)
    columns = statement.table.c
    session.exec(
        statement.on_conflict_do_update(
            constraint="uq_usagedaily_bucket",
            set_={name: columns[name] + statement.excluded[name] for name in COUNTERS}
            | {"updated_at": func.now()},
        )
    )


@contextmanager
def meter(user_id: uuid.UUID | None, feature: UsageFeature) -> Iterator[UsageMeter]:
    """A meter that writes itself out however the block ends.

    Including on the way out of an exception: a question that failed halfway
    still spent whatever it spent before it failed.

    For a sync caller - the worker, and any ``def`` route, which FastAPI runs
    in its threadpool where a blocking write costs nothing.
    """
    m = UsageMeter(user_id=user_id, feature=feature)
    try:
        yield m
    finally:
        m.flush()


@asynccontextmanager
async def ameter(
    user_id: uuid.UUID | None, feature: UsageFeature
) -> AsyncIterator[UsageMeter]:
    """The same, for an ``async def`` route.

    The write goes to a thread. Metering is bookkeeping that happens after the
    useful work, and blocking the event loop on it would make one person's
    accounting everybody else's latency.
    """
    m = UsageMeter(user_id=user_id, feature=feature)
    try:
        yield m
    finally:
        await asyncio.to_thread(m.flush)


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 400


@dataclass(frozen=True, slots=True)
class Range:
    """The days a dashboard is asking about, inclusive at both ends."""

    frm: date
    to: date

    @property
    def days(self) -> int:
        return (self.to - self.frm).days + 1


def resolve_range(frm: date | None, to: date | None) -> Range:
    """Fill in whichever end was left out, and refuse an impossible one."""
    end = to or today()
    start = frm or (end - timedelta(days=DEFAULT_RANGE_DAYS - 1))
    if start > end:
        raise ValueError("The start of the range is after its end.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"A range may cover at most {MAX_RANGE_DAYS} days.")
    return Range(frm=start, to=end)


@dataclass(frozen=True, slots=True)
class Query:
    """What a dashboard is asking for, in one object the endpoints pass on."""

    rng: Range
    user_ids: Sequence[uuid.UUID] | None = None
    feature: UsageFeature | None = None
    model: str | None = None
    kinds: Sequence[UsageKind] | None = None

    def only(self, kinds: Sequence[UsageKind]) -> Query:
        """The same question, narrowed to some kinds of call."""
        return Query(
            rng=self.rng,
            user_ids=self.user_ids,
            feature=self.feature,
            model=self.model,
            kinds=self.kinds or kinds,
        )

    def apply(self, statement: Any) -> Any:
        statement = statement.where(
            col(UsageDaily.day) >= self.rng.frm, col(UsageDaily.day) <= self.rng.to
        )
        if self.user_ids is not None:
            statement = statement.where(
                col(UsageDaily.user_id).in_(list(self.user_ids))
            )
        if self.feature is not None:
            statement = statement.where(UsageDaily.feature == self.feature)
        if self.model:
            statement = statement.where(UsageDaily.model == self.model)
        if self.kinds is not None:
            statement = statement.where(
                col(UsageDaily.kind).in_([k.value for k in self.kinds])
            )
        return statement


def _sums() -> list[Any]:
    return [func.coalesce(func.sum(getattr(UsageDaily, name)), 0) for name in COUNTERS]


def _counts_at(row: Sequence[Any], offset: int) -> Counts:
    return Counts(
        **{name: int(row[offset + i] or 0) for i, name in enumerate(COUNTERS)}
    )


def totals(session: Session, q: Query) -> Counts:
    """One row of sums for the whole range."""
    row = session.exec(q.apply(select(*_sums()))).one_or_none()
    return _counts_at(row, 0) if row is not None else Counts()


def _grouped(session: Session, q: Query, *columns: Any) -> list[tuple[Any, ...]]:
    """Sums grouped by whatever columns are asked for.

    One query per breakdown rather than one per row - the same shape as
    ``quota.pages_used_for``, for the same reason.
    """
    statement = q.apply(select(*columns, *_sums())).group_by(*columns)
    return [tuple(row) for row in session.exec(statement).all()]


def _by_spend(rows: list[tuple[Any, ...]], offset: int) -> list[tuple[Any, Counts]]:
    out = [(row[0], _counts_at(row, offset)) for row in rows]
    out.sort(key=lambda r: (r[1].cost_nanos, r[1].requests), reverse=True)
    return out


def by_day(session: Session, q: Query) -> list[tuple[date, Counts]]:
    rows = _grouped(session, q, col(UsageDaily.day))
    return sorted(((r[0], _counts_at(r, 1)) for r in rows), key=lambda r: r[0])


def by_feature(session: Session, q: Query) -> list[tuple[str, Counts]]:
    return _by_spend(_grouped(session, q, col(UsageDaily.feature)), 1)


def by_kind(session: Session, q: Query) -> list[tuple[str, Counts]]:
    return _by_spend(_grouped(session, q, col(UsageDaily.kind)), 1)


def by_model(session: Session, q: Query) -> list[tuple[str, str, Counts]]:
    """Per model and kind, skipping the bookkeeping rows, which name no model."""
    rows = _grouped(
        session, q.only(MODEL_KINDS), col(UsageDaily.model), col(UsageDaily.kind)
    )
    out = [(str(r[0]), str(r[1]), _counts_at(r, 2)) for r in rows]
    out.sort(key=lambda r: (r[2].cost_nanos, r[2].requests), reverse=True)
    return out


def by_user(session: Session, q: Query) -> list[tuple[uuid.UUID, Counts]]:
    return _by_spend(_grouped(session, q, col(UsageDaily.user_id)), 1)


def by_group(session: Session, q: Query) -> list[tuple[uuid.UUID | None, Counts]]:
    """Per group, by joining the account rather than denormalising the group.

    Group membership changes; a denormalised copy would rewrite history every
    time somebody moved between groups.
    """
    statement = (
        q.apply(
            select(col(User.group_id), *_sums()).join(
                User, col(User.id) == col(UsageDaily.user_id)
            )
        )
    ).group_by(col(User.group_id))
    rows = [tuple(row) for row in session.exec(statement).all()]
    return _by_spend(rows, 1)
