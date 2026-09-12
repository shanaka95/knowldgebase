from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"


# Marks a token that is *not* a session: it only names a login waiting for its
# emailed code. Checked on the way in, so one can never be used as the other.
CHALLENGE_TOKEN_TYPE = "2fa-challenge"


def create_access_token(
    subject: str | Any, expires_delta: timedelta, session_epoch: int = 0
) -> str:
    """A session token, stamped with the epoch it was minted under.

    The epoch is what makes revocation possible. A JWT cannot be withdrawn once
    issued, so the account carries a counter, every token records the value it
    saw, and raising the counter leaves every older token failing its check.
    """
    expire = datetime.now(UTC) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "sev": session_epoch}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_challenge_token(subject: str | Any, expires_delta: timedelta) -> str:
    """Proof that a password was accepted, and nothing more.

    It carries no session epoch and a type of its own, so presenting it as a
    bearer token gets nowhere: the code still has to be answered.
    """
    expire = datetime.now(UTC) + expires_delta
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "typ": CHALLENGE_TOKEN_TYPE,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def read_challenge_token(token: str) -> str | None:
    """The user id inside a challenge token, or None if it is not one."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    if payload.get("typ") != CHALLENGE_TOKEN_TYPE:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def generate_api_key() -> tuple[str, str, str]:
    """Return (plain_key, prefix_for_display, sha256_hash)."""
    import hashlib
    import secrets

    plain = f"{settings.API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = plain[:12]
    digest = hashlib.sha256(plain.encode()).hexdigest()
    return plain, prefix, digest


def hash_api_key(plain: str) -> str:
    import hashlib

    return hashlib.sha256(plain.encode()).hexdigest()
