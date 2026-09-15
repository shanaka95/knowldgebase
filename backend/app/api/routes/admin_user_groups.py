"""Groups of accounts, and the settings they share - for administrators only.

A group is an administrative device for giving a class of people the same
limits. The people in one are never told: nothing here appears on any schema a
non-administrator can fetch, and the refusal an account sees when it runs out of
pages names its number and not its group.

Same contract as the other admin routers: superuser-only at the router, which
chains off ``SessionUser`` and so cannot be reached with an API key.
"""

import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, func, select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    GroupMembers,
    LimitDefinitionsPublic,
    Message,
    User,
    UserGroup,
    UserGroupCreate,
    UserGroupPublic,
    UserGroupsPublic,
    UserGroupUpdate,
    get_datetime_utc,
)
from app.services import quota

router = APIRouter(
    prefix="/admin/user-groups",
    tags=["admin_user_groups"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _slugify(name: str) -> str:
    from slugify import slugify

    return slugify(name, max_length=120) or "group"


def _to_public(
    session: SessionDep, group: UserGroup, member_count: int = 0
) -> UserGroupPublic:
    """A group, with both what it sets and what its members would actually get.

    Both, because "this group sets nothing" and "this group's members get 100"
    are different facts and the screen needs each: one is what an admin edits,
    the other is the consequence.
    """
    fallback = quota.default_group(session)
    effective: dict[str, int] = {}
    for spec in quota.LIMITS:
        own = getattr(group, spec.key, None)
        if own is not None:
            effective[spec.key] = own
            continue
        inherited = getattr(fallback, spec.key, None) if fallback else None
        effective[spec.key] = inherited if inherited is not None else spec.fallback

    return UserGroupPublic(
        id=group.id,
        slug=group.slug,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        is_system=group.is_system,
        member_count=member_count,
        **{spec.key: getattr(group, spec.key, None) for spec in quota.LIMITS},
        **{f"effective_{key}": value for key, value in effective.items()},
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("/", response_model=UserGroupsPublic)
def read_user_groups(session: SessionDep) -> Any:
    """Every group, default first, with how many accounts are in each."""
    quota.ensure_default_group(session)
    groups = list(
        session.exec(
            select(UserGroup).order_by(
                col(UserGroup.is_default).desc(), col(UserGroup.name)
            )
        ).all()
    )
    counts = quota.member_counts(session, [g.id for g in groups])
    return UserGroupsPublic(
        data=[_to_public(session, g, counts.get(g.id, 0)) for g in groups],
        count=len(groups),
    )


@router.get("/limits", response_model=LimitDefinitionsPublic)
def read_limit_definitions() -> Any:
    """What can be set, described well enough to draw a form from.

    The admin form is generated from this, so a limit added to the registry
    appears in the interface without the interface being changed.
    """
    return LimitDefinitionsPublic(data=quota.limit_definitions())


@router.post("/", response_model=UserGroupPublic)
def create_user_group(session: SessionDep, body: UserGroupCreate) -> Any:
    name = body.name.strip()
    clash = session.exec(
        select(UserGroup).where(func.lower(UserGroup.name) == name.lower())
    ).first()
    if clash is not None:
        raise HTTPException(
            status_code=409, detail="There is already a group with this name"
        )

    slug = _slugify(name)
    if session.exec(select(UserGroup).where(UserGroup.slug == slug)).first():
        slug = f"{slug[:110]}-{secrets.token_hex(2)}"

    group = UserGroup(
        slug=slug,
        name=name,
        description=body.description,
        # From the registry rather than field by field: the docstring in
        # `quota.py` promises a new limit costs four lines, and a route that
        # names each one by hand is a fifth place that silently drops it.
        **{
            spec.key: getattr(body, spec.key, None)
            for spec in quota.LIMITS
            if hasattr(body, spec.key)
        },
    )
    session.add(group)
    session.commit()
    session.refresh(group)
    return _to_public(session, group, 0)


@router.patch("/{group_id}", response_model=UserGroupPublic)
def update_user_group(
    session: SessionDep, group_id: uuid.UUID, body: UserGroupUpdate
) -> Any:
    group = session.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        clash = session.exec(
            select(UserGroup).where(
                func.lower(UserGroup.name) == str(data["name"]).lower(),
                UserGroup.id != group.id,
            )
        ).first()
        if clash is not None:
            raise HTTPException(
                status_code=409, detail="There is already a group with this name"
            )
    group.sqlmodel_update(data)
    group.updated_at = get_datetime_utc()
    session.add(group)
    session.commit()
    session.refresh(group)
    counts = quota.member_counts(session, [group.id])
    return _to_public(session, group, counts.get(group.id, 0))


@router.delete("/{group_id}")
def delete_user_group(session: SessionDep, group_id: uuid.UUID) -> Message:
    """Delete a group; its members fall back to the defaults.

    The default group itself cannot go: it is part of how every limit resolves,
    not content somebody happens to have made.
    """
    group = session.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.is_system:
        raise HTTPException(
            status_code=409,
            detail="The default group cannot be deleted; every account falls back to it.",
        )
    # The foreign key is ON DELETE SET NULL, and a null group already means
    # "the defaults", so the members need no separate step.
    session.delete(group)
    session.commit()
    return Message(message="Group deleted")


@router.post("/{group_id}/members", response_model=UserGroupPublic)
def add_group_members(
    session: SessionDep, group_id: uuid.UUID, body: GroupMembers
) -> Any:
    """Move accounts into this group. Assignment is exclusive - one group each."""
    group = session.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    users = session.exec(select(User).where(col(User.id).in_(body.user_ids))).all()
    for user in users:
        user.group_id = group.id
        session.add(user)
    session.commit()
    counts = quota.member_counts(session, [group.id])
    return _to_public(session, group, counts.get(group.id, 0))


@router.delete("/{group_id}/members/{user_id}", response_model=UserGroupPublic)
def remove_group_member(
    session: SessionDep, group_id: uuid.UUID, user_id: uuid.UUID
) -> Any:
    group = session.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    user = session.get(User, user_id)
    if user is not None and user.group_id == group.id:
        user.group_id = None
        session.add(user)
        session.commit()
    counts = quota.member_counts(session, [group.id])
    return _to_public(session, group, counts.get(group.id, 0))
