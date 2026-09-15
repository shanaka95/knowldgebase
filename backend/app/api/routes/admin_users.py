"""Accounts as an administrator sees them: which group, and which limits.

Separate from `/users` on purpose. That router serves people their own account
and must never learn about groups; this one exists to show the resolution, so
it carries the group, the effective numbers and the tier each came from.

Assignment is one request that does both the group and the overrides, because
they are one decision. `overrides` is a **complete map**, not a patch: a key
that is absent is an override that is not set, which is exactly what an empty
form field produces. That removes the three-way "absent / null / number"
distinction that would otherwise have to survive a round trip through a
browser form.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import col, func, or_, select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    AdminUserPublic,
    AdminUsersPublic,
    GroupRef,
    User,
    UserAssignment,
    UserGroup,
)
from app.services import quota

router = APIRouter(
    prefix="/admin/users",
    tags=["admin_users"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _to_admin_public(
    session: SessionDep,
    user: User,
    groups: dict[uuid.UUID, UserGroup],
    used: dict[uuid.UUID, int] | None = None,
) -> AdminUserPublic:
    limits = quota.resolve_limits(session, user, groups=groups)
    group = groups.get(user.group_id) if user.group_id else None
    return AdminUserPublic(
        **user.model_dump(
            include={
                "email",
                "is_active",
                "is_superuser",
                "full_name",
                "id",
                "created_at",
                "email_verified_at",
            }
        ),
        max_pages=limits.max_pages,
        pages_used=(
            used[user.id] if used is not None else quota.pages_used(session, user.id)
        ),
        max_shares_per_document=limits.max_shares_per_document,
        max_members_per_space=limits.max_members_per_space,
        group=GroupRef(id=group.id, name=group.name, is_default=group.is_default)
        if group
        else None,
        limits=quota.resolve_detail(session, user, groups=groups),
    )


@router.get("/", response_model=AdminUsersPublic)
def read_admin_users(
    session: SessionDep,
    skip: int = 0,
    limit: int = Query(default=100, ge=1, le=1000),
    q: str | None = None,
    group_id: str | None = None,
) -> Any:
    """Accounts, with their group and their effective limits.

    `q` filters by name or address and `group_id` by group - `none` for the
    unassigned - because "who has no group?" is unanswerable from a list that
    stops at the first hundred.
    """
    quota.ensure_default_group(session)
    statement = select(User)
    counter = select(func.count()).select_from(User)

    if q:
        needle = f"%{q.strip().lower()}%"
        clause = or_(
            func.lower(User.email).like(needle),
            func.lower(func.coalesce(User.full_name, "")).like(needle),
        )
        statement = statement.where(clause)
        counter = counter.where(clause)
    if group_id == "none":
        statement = statement.where(col(User.group_id).is_(None))
        counter = counter.where(col(User.group_id).is_(None))
    elif group_id:
        try:
            wanted = uuid.UUID(group_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Not a group id") from exc
        statement = statement.where(User.group_id == wanted)
        counter = counter.where(User.group_id == wanted)

    count = session.exec(counter).one()
    users = session.exec(
        statement.order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    ).all()

    # Both gathered once for the page rather than per row: a thousand accounts
    # would otherwise be a thousand group lookups and two thousand counts.
    groups = quota.load_groups(session)
    used = quota.pages_used_for(session, [u.id for u in users])
    return AdminUsersPublic(
        data=[_to_admin_public(session, u, groups, used) for u in users],
        count=int(count),
    )


@router.put("/{user_id}/assignment", response_model=AdminUserPublic)
def set_user_assignment(
    session: SessionDep, user_id: uuid.UUID, body: UserAssignment
) -> Any:
    """Put an account in a group and set its overrides, in one transaction.

    Moving somebody and setting their numbers is one decision, so it is one
    request - there is no window in which the group has moved and the override
    has not.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if body.group_id is not None:
        group = session.get(UserGroup, body.group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found")
        user.group_id = group.id
    else:
        # No group is not an error state: it resolves against the defaults.
        user.group_id = None

    try:
        quota.apply_overrides(user, body.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.add(user)
    session.commit()
    session.refresh(user)
    return _to_admin_public(session, user, quota.load_groups(session))
