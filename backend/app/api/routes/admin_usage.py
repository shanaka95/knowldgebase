"""Usage as an administrator sees it: everyone's, and what it cost.

Separate from `/usage/me` on purpose. That router serves people their own
account and must never learn what their questions cost; this one exists to
show exactly that, so its schemas carry `cost_nanos` and its dependency is
superuser-only.

The dependency chains off `SessionUser`, so an API key cannot reach any of
this even when the key belongs to a superuser.

Two endpoints rather than one per breakdown: a summary that answers "how much,
over what, day by day", and a breakdown that answers "by whom" for whichever
dimension is asked for. Both take the same filters, so drilling from a chart
into a table is a change of one query parameter.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.routes.usage import FEATURE_LABELS, resolve
from app.models import (
    AdminUsageBreakdown,
    AdminUsagePoint,
    AdminUsageSummary,
    GroupRef,
    UsageFeature,
    User,
    UserGroup,
)
from app.services import quota, usage

router = APIRouter(
    prefix="/admin/usage",
    tags=["admin_usage"],
    dependencies=[Depends(get_current_active_superuser)],
)

BREAKDOWNS = ("user", "model", "group", "feature")

# Accounts named in a breakdown, at most this many. Ordered by spend, so the
# rows that are cut are the ones nobody is looking for.
MAX_ROWS = 200


def _scope(
    session: Session,
    frm: date | None,
    to: date | None,
    user_id: uuid.UUID | None,
    group_id: str | None,
    feature: UsageFeature | None,
    model: str | None,
) -> usage.Query:
    """The filters, turned into the one object every query here is built from.

    `group_id=none` means the unassigned, matching `/admin/users`. Filtering by
    group resolves to a list of accounts rather than a join, because the
    breakdowns need the same list and a group with no members has to come back
    empty rather than unfiltered.
    """
    rng = resolve(frm, to)
    user_ids: list[uuid.UUID] | None = None

    if user_id is not None:
        user_ids = [user_id]
    elif group_id:
        statement = select(col(User.id))
        if group_id == "none":
            statement = statement.where(col(User.group_id).is_(None))
        else:
            try:
                wanted = uuid.UUID(group_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Not a group id") from exc
            statement = statement.where(User.group_id == wanted)
        user_ids = list(session.exec(statement).all())

    return usage.Query(rng=rng, user_ids=user_ids, feature=feature, model=model)


@router.get("/summary", response_model=AdminUsageSummary)
def read_usage_summary(
    session: SessionDep,
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    user_id: uuid.UUID | None = None,
    group_id: str | None = None,
    feature: UsageFeature | None = None,
    model: str | None = None,
) -> Any:
    """Totals for the range, split by feature and by day."""
    q = _scope(session, frm, to, user_id, group_id, feature, model)
    return AdminUsageSummary(
        range=usage.public_range(q.rng),
        totals=usage.admin_totals(usage.totals(session, q)),
        by_feature=usage.admin_points(
            usage.by_feature(session, q), label=FEATURE_LABELS.get
        ),
        by_day=usage.admin_points(usage.by_day(session, q)),
    )


@router.get("/breakdown", response_model=AdminUsageBreakdown)
def read_usage_breakdown(
    session: SessionDep,
    by: str = Query(default="user"),
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    user_id: uuid.UUID | None = None,
    group_id: str | None = None,
    feature: UsageFeature | None = None,
    model: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_ROWS),
) -> Any:
    """Who or what the spend went on, largest first."""
    if by not in BREAKDOWNS:
        raise HTTPException(
            status_code=422, detail=f"Break down by one of: {', '.join(BREAKDOWNS)}"
        )
    q = _scope(session, frm, to, user_id, group_id, feature, model)

    points: list[AdminUsagePoint]
    if by == "user":
        rows = usage.by_user(session, q)
        # One query for the names and one for the groups, however many rows -
        # the same reason `/admin/users` prefetches rather than serialising
        # account by account.
        accounts = _accounts(session, [key for key, _ in rows])
        groups = quota.load_groups(session)
        points = usage.admin_points(
            rows,
            label=lambda key: _describe(accounts.get(key)),
            group=lambda key: _group_ref(accounts.get(key), groups),
        )
    elif by == "group":
        by_group = usage.by_group(session, q)
        groups = quota.load_groups(session)
        points = usage.admin_points(
            by_group,
            label=lambda key: groups[key].name if key in groups else "No group",
        )
    elif by == "model":
        models = usage.by_model(session, q)
        points = usage.admin_points(
            usage.model_rows(models), label=usage.model_labels(models).get
        )
    else:
        points = usage.admin_points(
            usage.by_feature(session, q), label=FEATURE_LABELS.get
        )

    return AdminUsageBreakdown(
        range=usage.public_range(q.rng),
        by=by,
        totals=usage.admin_totals(usage.totals(session, q)),
        data=points[:limit],
        count=len(points),
    )


@router.get("/models", response_model=list[str])
def read_models_seen(
    session: SessionDep,
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> Any:
    """Which models have actually been used, for the filter control.

    Read from the data rather than from settings: the list has to include a
    model that was retired last month but appears in last month's rows, and
    exclude one that is configured but has never answered anything.
    """
    rng = resolve(frm, to)
    q = usage.Query(rng=rng, kinds=usage.MODEL_KINDS)
    return sorted({model for model, _kind, _counts in usage.by_model(session, q)})


def _accounts(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = session.exec(select(User).where(col(User.id).in_(ids))).all()
    return {user.id: user for user in rows}


def _describe(user: User | None) -> str:
    """An account, as a person reading a spend table would recognise it."""
    if user is None:
        return "Deleted account"
    return user.full_name or user.email


def _group_ref(
    user: User | None, groups: dict[uuid.UUID, UserGroup]
) -> GroupRef | None:
    if user is None or user.group_id is None:
        return None
    group = groups.get(user.group_id)
    return (
        GroupRef(id=group.id, name=group.name, is_default=group.is_default)
        if group
        else None
    )
