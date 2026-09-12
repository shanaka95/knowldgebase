"""Endpoints that exist only in development.

Mounted from ``app.api.main`` when ``FASTAPI_ENV == "development"``, so none of
this is reachable from a deployed instance. It exists so the end-to-end suite
can set up accounts and read what would have been emailed, without a mail
provider and without weakening any of the real flows.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.core.security import get_password_hash
from app.models import (
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

    return user


@router.get("/emails/", response_model=list[CapturedEmail])
def read_emails(to: str | None = None, limit: int = 20) -> Any:
    """Read what would have been emailed, newest first.

    With ``EMAIL_ENABLED=false`` the sender records messages instead of sending
    them; this hands them back so a browser test can follow a confirmation link
    or answer a sign-in code the way a person reading their mail would.
    """
    sender = get_email_sender()
    if not isinstance(sender, LoggingEmailSender):
        raise HTTPException(
            status_code=400,
            detail="Email is enabled, so nothing is captured.",
        )
    messages = [
        CapturedEmail(to=message.to, subject=message.subject, text=message.text)
        for message in sender.sent
        if to is None or message.to.lower() == to.lower()
    ]
    return list(reversed(messages))[:limit]
