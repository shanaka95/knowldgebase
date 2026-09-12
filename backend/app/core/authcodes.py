"""Issuing and redeeming the one-time secrets that guard an account.

Three flows share this machinery - confirming an address, confirming a login,
resetting a password - because they need the same guarantees:

* **The secret is never stored.** Only a SHA-256 hash goes to the database, so a
  database copy does not let anyone sign in. There is no key-stretching here and
  none is needed: unlike a password, these secrets are long random values (or
  short-lived six-digit ones with a hard guessing budget), not something a
  person chose and reused elsewhere.
* **Single use.** Redeeming marks the row consumed inside the same transaction.
* **Short life.** Minutes for a login code, hours for an address confirmation.
* **A guessing budget.** Six digits is a million possibilities, which is plenty
  for a code that dies after five wrong answers and ten minutes, and far too few
  for one that does not.
* **One live secret per purpose.** Issuing a new code invalidates the previous
  one, so a mailbox full of old codes is worth nothing.

Lookups are by hash, not by user, so verification never needs to be told which
account it is checking - which in turn means a token in a link identifies its
own account and cannot be pointed at someone else's.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import AuthCode, AuthCodePurpose, User


def _now() -> datetime:
    return datetime.now(UTC)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_numeric_code(length: int | None = None) -> str:
    """A code a person reads from an email and types into a form.

    Leading zeros are kept, so every code is the same length and nobody wonders
    whether they mistyped.
    """
    size = length or settings.TWO_FACTOR_CODE_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(size))


def generate_link_token() -> str:
    """A secret that travels in a URL, long enough that guessing is hopeless."""
    return secrets.token_urlsafe(32)


def mask_email(email: str) -> str:
    """Enough to recognise your own address, not enough to learn someone else's."""
    local, _, domain = email.partition("@")
    if not domain:
        return "•" * len(email)
    if len(local) <= 2:
        shown = local[:1]
        hidden = max(len(local) - 1, 1)
    else:
        shown = local[0]
        hidden = len(local) - 2
    return f"{shown}{'•' * hidden}{local[-1]}@{domain}"


def recent_send_count(
    session: Session, user_id: object, purpose: AuthCodePurpose
) -> int:
    """How many codes of this kind were issued in the rate-limit window."""
    since = _now() - timedelta(minutes=settings.AUTH_CODE_SEND_WINDOW_MINUTES)
    rows = session.exec(
        select(AuthCode).where(
            AuthCode.user_id == user_id,
            AuthCode.purpose == purpose,
            col(AuthCode.created_at) >= since,
        )
    ).all()
    return len(rows)


def issue(
    session: Session,
    user: User,
    purpose: AuthCodePurpose,
    *,
    secret: str,
    ttl: timedelta,
    sent_to: str | None = None,
) -> AuthCode:
    """Store a new secret for this purpose and retire any earlier one.

    The caller supplies the secret so it can also put it in an email; only the
    hash is kept here. Retiring the previous code matters: without it, every
    code ever sent would stay valid until it expired, and an old email would be
    as good as a new one.
    """
    now = _now()
    for stale in session.exec(
        select(AuthCode).where(
            AuthCode.user_id == user.id,
            AuthCode.purpose == purpose,
            col(AuthCode.consumed_at).is_(None),
        )
    ).all():
        stale.consumed_at = now
        session.add(stale)

    code = AuthCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=hash_secret(secret),
        sent_to=sent_to or user.email,
        expires_at=now + ttl,
    )
    session.add(code)
    session.commit()
    session.refresh(code)
    return code


class RedeemResult:
    """Why a redemption failed, in terms the caller can turn into a message."""

    __slots__ = ("code", "reason", "user")

    def __init__(
        self,
        code: AuthCode | None = None,
        user: User | None = None,
        reason: str | None = None,
    ) -> None:
        self.code = code
        self.user = user
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.code is not None and self.user is not None


def redeem(
    session: Session,
    purpose: AuthCodePurpose,
    secret: str,
    *,
    user_id: object | None = None,
) -> RedeemResult:
    """Consume a secret, or explain why it cannot be consumed.

    Pass ``user_id`` when the account is already known - the two-factor step
    knows it from the challenge - so a code issued for one account can never be
    redeemed against another, even in the vanishingly unlikely event of a hash
    collision or a duplicated code.
    """
    digest = hash_secret(secret)
    query = select(AuthCode).where(
        AuthCode.purpose == purpose, AuthCode.code_hash == digest
    )
    if user_id is not None:
        query = query.where(AuthCode.user_id == user_id)
    code = session.exec(query).first()

    if code is None:
        # Burn an attempt on the account's live code, if there is one. Without
        # this, wrong guesses would be free: only correct-but-stale guesses
        # would ever count against the budget.
        if user_id is not None:
            _charge_attempt(session, user_id, purpose)
        return RedeemResult(reason="invalid")
    if code.consumed_at is not None:
        return RedeemResult(reason="used")
    if code.expires_at <= _now():
        return RedeemResult(reason="expired")
    if code.attempts >= settings.AUTH_CODE_MAX_ATTEMPTS:
        return RedeemResult(reason="too_many_attempts")

    user = session.get(User, code.user_id)
    if user is None:
        return RedeemResult(reason="invalid")

    code.consumed_at = _now()
    session.add(code)
    session.commit()
    return RedeemResult(code=code, user=user)


def _charge_attempt(
    session: Session, user_id: object, purpose: AuthCodePurpose
) -> None:
    code = session.exec(
        select(AuthCode).where(
            AuthCode.user_id == user_id,
            AuthCode.purpose == purpose,
            col(AuthCode.consumed_at).is_(None),
        )
    ).first()
    if code is None:
        return
    code.attempts += 1
    if code.attempts >= settings.AUTH_CODE_MAX_ATTEMPTS:
        # Out of guesses. Destroying it rather than merely refusing means a
        # correct guess arriving later is worth nothing either.
        code.consumed_at = _now()
    session.add(code)
    session.commit()


def attempts_remaining(
    session: Session, user_id: object, purpose: AuthCodePurpose
) -> int:
    code = session.exec(
        select(AuthCode).where(
            AuthCode.user_id == user_id,
            AuthCode.purpose == purpose,
            col(AuthCode.consumed_at).is_(None),
        )
    ).first()
    if code is None:
        return 0
    return max(settings.AUTH_CODE_MAX_ATTEMPTS - code.attempts, 0)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
