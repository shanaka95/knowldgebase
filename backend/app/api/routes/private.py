"""Endpoints that exist only in development.

Mounted from ``app.api.main`` when ``FASTAPI_ENV == "development"``, so none of
this is reachable from a deployed instance. It exists so the end-to-end suite
can set up accounts and read what would have been emailed, without a mail
provider and without weakening any of the real flows.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.api.serializers import to_user_public
from app.core.security import get_password_hash
from app.models import (
    CapturedEmailRow,
    User,
    UserPublic,
    get_datetime_utc,
)
from app.services.email import LoggingEmailSender, get_email_sender

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False


class CapturedEmail(BaseModel):
    """A message the logging sender kept instead of sending."""

    to: str
    subject: str
    text: str


@router.post("/users/", response_model=UserPublic)
def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """
    Create a new user.
    """

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        # A test fixture has no inbox to confirm from, and an unconfirmed
        # account cannot sign in at all.
        email_verified_at=get_datetime_utc() if user_in.is_verified else None,
    )

    session.add(user)
    session.commit()

    return to_user_public(session, user)


@router.get("/emails/", response_model=list[CapturedEmail])
def read_emails(session: SessionDep, to: str | None = None, limit: int = 20) -> Any:
    """Read what would have been emailed, newest first.

    With ``EMAIL_ENABLED=false`` the sender records messages instead of sending
    them; this hands them back so a browser test can follow a confirmation link
    or answer a sign-in code the way a person reading their mail would.

    Two sources, because there are two processes. The API's own sends are in
    memory here; anything the worker sent - a reminder - only exists in the
    table, and that is the whole reason the table exists.
    """
    sender = get_email_sender()
    if not isinstance(sender, LoggingEmailSender):
        raise HTTPException(
            status_code=400,
            detail="Email is enabled, so nothing is captured.",
        )

    in_memory = [
        (message.to, message.subject, message.text)
        for message in sender.sent
        if to is None or message.to.lower() == to.lower()
    ]
    # Oldest first in the list; the table already knows when each arrived.
    combined: list[tuple[datetime, str, str, str]] = [
        (datetime.min.replace(tzinfo=UTC), *m) for m in in_memory
    ]

    statement = select(CapturedEmailRow)
    if to is not None:
        statement = statement.where(func.lower(CapturedEmailRow.to_email) == to.lower())
    for row in session.exec(
        statement.order_by(col(CapturedEmailRow.created_at).desc()).limit(limit)
    ).all():
        combined.append((row.created_at, row.to_email, row.subject, row.text))

    combined.sort(key=lambda item: item[0])
    return [
        CapturedEmail(to=address, subject=subject, text=text)
        for _, address, subject, text in reversed(combined)
    ][:limit]
