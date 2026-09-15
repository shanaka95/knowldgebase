"""Credits as an administrator gives them out.

Two different tools, and the difference matters:

* **The allowance** is a limit like any other, so it is set on the Groups
  screen through `monthly_credits` - per group, or per account as an override.
  It renews every month. That is where a *permanent* change belongs.
* **A grant** is a one-off top-up, and lives here. It ends when the month does
  unless a longer life is asked for, because the allowance renews then anyway
  and a top-up that outlived it would quietly become part of the allowance.

Superuser-only at the router level, which also puts it out of reach of an API
key: the dependency chains off `SessionUser`.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    CreditBalance,
    CreditGrant,
    CreditGrantCreate,
    CreditGrantPublic,
    CreditGrantsPublic,
    Message,
    User,
)
from app.services import credits

router = APIRouter(
    prefix="/admin/credits",
    tags=["admin_credits"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _to_public(grant: CreditGrant, *, now: Any = None) -> CreditGrantPublic:
    from datetime import UTC, datetime

    moment = now or datetime.now(UTC)
    return CreditGrantPublic(
        id=grant.id,
        user_id=grant.user_id,
        credits=credits.as_credits(grant.amount_milli),
        reason=grant.reason,
        granted_by=grant.granted_by,
        expires_at=grant.expires_at,
        created_at=grant.created_at,
        expired=grant.expires_at <= moment,
    )


def _account(session: SessionDep, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}", response_model=CreditBalance)
def read_balance(session: SessionDep, user_id: uuid.UUID) -> Any:
    """One account's balance, computed the same way the account sees it."""
    user = _account(session, user_id)
    return credits.to_public(credits.balance_for(session, user), session, user)


@router.get("/{user_id}/grants", response_model=CreditGrantsPublic)
def read_grants(session: SessionDep, user_id: uuid.UUID) -> Any:
    """Every top-up this account has been given, newest first."""
    _account(session, user_id)
    rows = credits.grants_for(session, user_id)
    data = [_to_public(row) for row in rows]
    return CreditGrantsPublic(data=data, count=len(data))


@router.post("/{user_id}/grants", response_model=CreditGrantPublic, status_code=201)
def create_grant(
    session: SessionDep,
    user_id: uuid.UUID,
    body: CreditGrantCreate,
    admin: User = Depends(get_current_active_superuser),
) -> Any:
    """Top an account up.

    Takes effect immediately: the balance is derived, not stored, so the next
    request this account makes already sees it.
    """
    user = _account(session, user_id)
    grant = credits.grant(
        session,
        user,
        credits=body.credits,
        reason=body.reason,
        days=body.days,
        granted_by=admin.id,
    )
    session.commit()
    session.refresh(grant)
    return _to_public(grant)


@router.delete("/{user_id}/grants/{grant_id}", response_model=Message)
def delete_grant(session: SessionDep, user_id: uuid.UUID, grant_id: uuid.UUID) -> Any:
    """Take a top-up back.

    Checked against the account it was given to, so a grant id from elsewhere
    cannot be removed through this path.
    """
    grant = session.get(CreditGrant, grant_id)
    if grant is None or grant.user_id != user_id:
        raise HTTPException(status_code=404, detail="Grant not found")
    session.delete(grant)
    session.commit()
    return Message(message="Grant removed")
