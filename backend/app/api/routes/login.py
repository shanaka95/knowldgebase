"""Signing in, confirming an address, and getting back in after forgetting.

Signing in takes two steps, always. The password buys a *challenge*, not a
session; the session is issued only after a code sent to the account's address
is answered. That makes a stolen or reused password insufficient on its own,
which is the entire point, so there is no opt-out and no "remember this device"
shortcut to erode it.

The endpoints that take an email address - resending a confirmation, asking for
a password reset - always answer the same way whether or not the address is
known. Anything else turns the login page into a tool for discovering who has an
account here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app import crud
from app.api.deps import SessionDep, SessionUser
from app.api.serializers import to_user_public
from app.core import authcodes, security
from app.core.config import settings
from app.models import (
    AuthCodePurpose,
    EmailVerificationConfirm,
    EmailVerificationRequest,
    LoginChallenge,
    Message,
    NewPassword,
    PasswordRecoveryRequest,
    Token,
    TwoFactorResend,
    TwoFactorVerify,
    User,
    UserPublic,
)
from app.services import email as mail
from app.services import sharing

logger = logging.getLogger(__name__)

router = APIRouter(tags=["login"])

# One answer for every "did you send it?" request, regardless of the truth.
NEUTRAL_REPLY = "If that address has an account, we have sent a message to it."


def _now() -> datetime:
    return datetime.now(UTC)


def _frontend(path: str, token: str) -> str:
    return f"{settings.FRONTEND_HOST.rstrip('/')}{path}?token={token}"


async def _deliver(message: mail.Email) -> bool:
    """Send, and report whether it went. Never raise into an auth flow.

    A provider outage must not be reported as "wrong password", and must not
    leave the caller waiting for a message that is never coming either - hence a
    boolean the caller can pass on honestly.
    """
    try:
        await mail.get_email_sender().send(message)
    except mail.EmailError as exc:
        logger.error("could not send %r: %s", message.subject, exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------


def _is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > _now()


def _record_failure(session: Session, user: User) -> None:
    """Count a wrong password, and stop answering after too many.

    The window matters as much as the count: someone who mistypes twice a week
    should never be locked out, while a script trying the top thousand passwords
    should get ten tries and then a wall.
    """
    now = _now()
    window = timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    if user.last_failed_login_at is None or user.last_failed_login_at < now - window:
        user.failed_logins = 0
    user.failed_logins += 1
    user.last_failed_login_at = now
    if user.failed_logins >= settings.LOGIN_MAX_FAILURES:
        user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        user.failed_logins = 0
    session.add(user)
    session.commit()


def _clear_failures(session: Session, user: User) -> None:
    if user.failed_logins or user.locked_until:
        user.failed_logins = 0
        user.locked_until = None
        session.add(user)
        session.commit()


# ---------------------------------------------------------------------------
# Step 1: the password
# ---------------------------------------------------------------------------


@router.post("/login/access-token", response_model=LoginChallenge)
async def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Any:
    """Check the password and email a sign-in code.

    This returns a challenge, never a session. Exchange it for an access token
    at `/login/two-factor` by answering the emailed code.

    Third-party and programmatic callers should use a personal API key instead
    of a password; see the API documentation.
    """
    user = crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        # The account may still exist, so count the failure against it if it
        # does - without telling the caller which case they are in.
        existing = crud.get_user_by_email(session=session, email=form_data.username)
        if existing is not None:
            _record_failure(session, existing)
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if _is_locked(user):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in a few minutes.",
        )
    if user.email_verified_at is None:
        # A specific status, because the interface has something useful to offer
        # here: resend the confirmation.
        raise HTTPException(
            status_code=403,
            detail="Confirm your email address before signing in.",
        )

    _clear_failures(session, user)

    if (
        authcodes.recent_send_count(session, user.id, AuthCodePurpose.two_factor)
        >= settings.AUTH_CODE_MAX_SENDS
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in codes requested. Try again shortly.",
        )

    code = authcodes.generate_numeric_code()
    record = authcodes.issue(
        session,
        user,
        AuthCodePurpose.two_factor,
        secret=code,
        ttl=timedelta(minutes=settings.TWO_FACTOR_TTL_MINUTES),
    )
    delivered = await _deliver(
        mail.two_factor_email(user.email, code, settings.TWO_FACTOR_TTL_MINUTES)
    )
    return LoginChallenge(
        challenge_token=security.create_challenge_token(
            user.id, timedelta(minutes=settings.LOGIN_CHALLENGE_TTL_MINUTES)
        ),
        expires_at=record.expires_at,
        sent_to=authcodes.mask_email(user.email),
        code_length=settings.TWO_FACTOR_CODE_LENGTH,
        delivered=delivered,
    )


# ---------------------------------------------------------------------------
# Step 2: the code
# ---------------------------------------------------------------------------


@router.post("/login/two-factor", response_model=Token)
def verify_two_factor(session: SessionDep, body: TwoFactorVerify) -> Any:
    """Answer the emailed code and receive an access token."""
    user_id = security.read_challenge_token(body.challenge_token)
    if user_id is None:
        raise HTTPException(
            status_code=400, detail="That sign-in attempt has expired. Start again."
        )

    result = authcodes.redeem(
        session,
        AuthCodePurpose.two_factor,
        body.code.strip(),
        user_id=user_id,
    )
    if not result.ok:
        if result.reason == "expired":
            raise HTTPException(
                status_code=400, detail="That code has expired. Ask for a new one."
            )
        if result.reason == "too_many_attempts":
            raise HTTPException(
                status_code=429,
                detail="Too many wrong codes. Ask for a new one.",
            )
        left = authcodes.attempts_remaining(
            session, user_id, AuthCodePurpose.two_factor
        )
        detail = "That code is not right."
        if left:
            detail += f" {left} attempt{'s' if left != 1 else ''} left."
        else:
            detail += " Ask for a new one."
        raise HTTPException(status_code=400, detail=detail)

    user = result.user
    assert user is not None  # ok is True, so both are set
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    _clear_failures(session, user)
    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            session_epoch=user.session_epoch,
        )
    )


@router.post("/login/two-factor/resend", response_model=LoginChallenge)
async def resend_two_factor(session: SessionDep, body: TwoFactorResend) -> Any:
    """Send another sign-in code for a login already in progress."""
    user_id = security.read_challenge_token(body.challenge_token)
    if user_id is None:
        raise HTTPException(
            status_code=400, detail="That sign-in attempt has expired. Start again."
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=400, detail="That sign-in attempt has expired. Start again."
        )
    if (
        authcodes.recent_send_count(session, user.id, AuthCodePurpose.two_factor)
        >= settings.AUTH_CODE_MAX_SENDS
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in codes requested. Try again shortly.",
        )

    code = authcodes.generate_numeric_code()
    record = authcodes.issue(
        session,
        user,
        AuthCodePurpose.two_factor,
        secret=code,
        ttl=timedelta(minutes=settings.TWO_FACTOR_TTL_MINUTES),
    )
    delivered = await _deliver(
        mail.two_factor_email(user.email, code, settings.TWO_FACTOR_TTL_MINUTES)
    )
    return LoginChallenge(
        challenge_token=body.challenge_token,
        expires_at=record.expires_at,
        sent_to=authcodes.mask_email(user.email),
        code_length=settings.TWO_FACTOR_CODE_LENGTH,
        delivered=delivered,
    )


# ---------------------------------------------------------------------------
# Confirming an address
# ---------------------------------------------------------------------------


async def send_verification_email(session: Session, user: User) -> bool:
    """Issue a confirmation link and email it. Shared with sign-up."""
    token = authcodes.generate_link_token()
    authcodes.issue(
        session,
        user,
        AuthCodePurpose.verify_email,
        secret=token,
        ttl=timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS),
        sent_to=user.email,
    )
    return await _deliver(
        mail.verification_email(
            user.email,
            _frontend("/verify-email", token),
            settings.EMAIL_VERIFICATION_TTL_HOURS,
        )
    )


@router.post("/login/verify-email", response_model=Message)
def verify_email(session: SessionDep, body: EmailVerificationConfirm) -> Any:
    """Confirm an address using the link that was emailed to it."""
    result = authcodes.redeem(session, AuthCodePurpose.verify_email, body.token)
    if not result.ok:
        if result.reason == "expired":
            raise HTTPException(
                status_code=400,
                detail="That confirmation link has expired. Ask for a new one.",
            )
        raise HTTPException(
            status_code=400,
            detail="That confirmation link is not valid. Ask for a new one.",
        )
    user = result.user
    code = result.code
    assert user is not None and code is not None

    # The link confirms the address it was sent to. If the account has moved to
    # a different address since, this proves nothing about the current one.
    if code.sent_to.lower() != user.email.lower():
        raise HTTPException(
            status_code=400,
            detail="That link was sent to a different address. Ask for a new one.",
        )

    if user.email_verified_at is None:
        user.email_verified_at = _now()
        session.add(user)
        session.commit()

    # Anything shared with this address before the account existed becomes real
    # access now, and not a moment earlier: confirming the address is what
    # proves the person holding this account is the one it was shared with.
    pages, spaces = sharing.redeem_for(session, user)
    waiting = []
    if pages:
        waiting.append(f"{pages} page{'s' if pages != 1 else ''}")
    if spaces:
        waiting.append(f"{spaces} space{'s' if spaces != 1 else ''}")
    if waiting:
        return Message(
            message=(
                f"Your email address is confirmed, and {' and '.join(waiting)} "
                "shared with you is waiting. You can sign in now."
            )
        )
    return Message(message="Your email address is confirmed. You can sign in now.")


@router.post("/login/verify-email/resend", response_model=Message)
async def resend_verification(
    session: SessionDep, body: EmailVerificationRequest
) -> Any:
    """Send another confirmation link.

    Answers identically whether or not the address has an account.
    """
    user = crud.get_user_by_email(session=session, email=body.email)
    if (
        user is not None
        and user.is_active
        and user.email_verified_at is None
        and authcodes.recent_send_count(session, user.id, AuthCodePurpose.verify_email)
        < settings.AUTH_CODE_MAX_SENDS
    ):
        await send_verification_email(session, user)
    return Message(message=NEUTRAL_REPLY)


# ---------------------------------------------------------------------------
# Forgotten passwords
# ---------------------------------------------------------------------------


@router.post("/login/password-recovery", response_model=Message)
async def recover_password(session: SessionDep, body: PasswordRecoveryRequest) -> Any:
    """Email a link for choosing a new password.

    Answers identically whether or not the address has an account.
    """
    user = crud.get_user_by_email(session=session, email=body.email)
    if (
        user is not None
        and user.is_active
        and authcodes.recent_send_count(
            session, user.id, AuthCodePurpose.password_reset
        )
        < settings.AUTH_CODE_MAX_SENDS
    ):
        token = authcodes.generate_link_token()
        authcodes.issue(
            session,
            user,
            AuthCodePurpose.password_reset,
            secret=token,
            ttl=timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
        )
        await _deliver(
            mail.password_reset_email(
                user.email,
                _frontend("/reset-password", token),
                settings.PASSWORD_RESET_TTL_MINUTES,
            )
        )
    return Message(message=NEUTRAL_REPLY)


@router.post("/login/reset-password", response_model=Message)
async def reset_password(session: SessionDep, body: NewPassword) -> Any:
    """Set a new password using the emailed link, and end every other session."""
    result = authcodes.redeem(session, AuthCodePurpose.password_reset, body.token)
    if not result.ok:
        if result.reason == "expired":
            raise HTTPException(
                status_code=400,
                detail="That reset link has expired. Ask for a new one.",
            )
        raise HTTPException(
            status_code=400,
            detail="That reset link is not valid. Ask for a new one.",
        )
    user = result.user
    assert user is not None
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    user.hashed_password = security.get_password_hash(body.new_password)
    # Whoever asked for this may be locked out by an attacker who knows the old
    # password; every existing session has to go.
    user.session_epoch += 1
    user.failed_logins = 0
    user.locked_until = None
    # Reaching the reset link proves control of the address, which is exactly
    # what verification asks for.
    newly_confirmed = user.email_verified_at is None
    if newly_confirmed:
        user.email_verified_at = _now()
    session.add(user)
    session.commit()
    if newly_confirmed:
        sharing.redeem_for(session, user)

    await _deliver(mail.password_changed_email(user.email))
    return Message(message="Your password has been changed. Sign in with it now.")


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@router.post("/login/test-token", response_model=UserPublic)
def test_token(session: SessionDep, current_user: SessionUser) -> Any:
    """Confirm an access token is still good, and say whose it is."""
    return to_user_public(session, current_user)


@router.post("/login/sign-out-everywhere", response_model=Message)
def sign_out_everywhere(session: SessionDep, current_user: SessionUser) -> Any:
    """End every session for this account, including this one."""
    current_user.session_epoch += 1
    session.add(current_user)
    session.commit()
    return Message(message="Every session has been signed out.")
