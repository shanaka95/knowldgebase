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


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


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
