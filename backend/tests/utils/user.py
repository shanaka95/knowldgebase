import re

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, UserUpdate, get_datetime_utc
from app.services.email import LoggingEmailSender, get_email_sender
from tests.utils.utils import random_email, random_lower_string


def last_email_code() -> str:
    """The six-digit code from the most recent message.

    Tests run with ``EMAIL_ENABLED=false``, so messages are collected in memory
    rather than sent, which is what makes the real two-step login testable
    without a mail provider.
    """
    sender = get_email_sender()
    assert isinstance(sender, LoggingEmailSender), (
        "tests must run with EMAIL_ENABLED=false so codes can be read back"
    )
    for message in reversed(sender.sent):
        found = re.search(r"\b(\d{4,10})\b", message.text)
        if found:
            return found.group(1)
    raise AssertionError("no code was emailed")


def last_email_link_token() -> str:
    """The token from the most recent link, for verification and reset flows."""
    sender = get_email_sender()
    assert isinstance(sender, LoggingEmailSender)
    for message in reversed(sender.sent):
        found = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.text)
        if found:
            return found.group(1)
    raise AssertionError("no link was emailed")


def verify_email(db: Session, user: User) -> User:
    """Mark an address confirmed, as clicking the emailed link would."""
    user.email_verified_at = get_datetime_utc()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def user_authentication_headers(
    *, client: TestClient, email: str, password: str
) -> dict[str, str]:
    """Sign in the way the product does: password, then the emailed code."""
    data = {"username": email, "password": password}

    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=data)
    assert r.status_code == 200, r.text
    challenge = r.json()["challenge_token"]

    r = client.post(
        f"{settings.API_V1_STR}/login/two-factor",
        json={"challenge_token": challenge, "code": last_email_code()},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def create_random_user(db: Session) -> User:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    return verify_email(db, user)


def authentication_token_from_email(
    *, client: TestClient, email: str, db: Session
) -> dict[str, str]:
    """
    Return a valid token for the user with given email.

    If the user doesn't exist it is created first.
    """
    password = random_lower_string()
    user = crud.get_user_by_email(session=db, email=email)
    if not user:
        user_in_create = UserCreate(email=email, password=password)
        user = crud.create_user(session=db, user_create=user_in_create)
        verify_email(db, user)
    else:
        user_in_update = UserUpdate(password=password)
        if not user.id:
            raise Exception("User id not set")
        user = crud.update_user(session=db, db_user=user, user_in=user_in_update)
        verify_email(db, user)

    return user_authentication_headers(client=client, email=email, password=password)
