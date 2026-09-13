"""Small secrets, encrypted at rest.

Admin platform credentials and users' OAuth refresh tokens are both things the
server must be able to use but must never hand back: the API reports whether a
value is set, never what it is set to, so a stolen admin session cannot be
turned into a stolen Google client secret.

One Fernet key for all of them, from the environment. Shared by channels and
data sources rather than written twice, because two implementations of "keep
this secret" drift, and only one of them gets the fix.
"""

from __future__ import annotations

import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class CredentialSealError(RuntimeError):
    """Raised when credentials cannot be encrypted or decrypted."""


def _fernet():
    from cryptography.fernet import Fernet

    key = (settings.CHANNEL_SECRET_KEY or "").strip()
    if not key:
        raise CredentialSealError(
            "CHANNEL_SECRET_KEY is not set, so credentials cannot be stored. "
            "Generate one with Fernet.generate_key()."
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001 - any malformed key is the same problem
        raise CredentialSealError(
            "CHANNEL_SECRET_KEY is not a valid Fernet key"
        ) from exc


def seal_credentials(values: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def open_credentials(sealed: str | None) -> dict[str, str]:
    """Decrypt stored credentials. An unreadable blob yields nothing, not a crash.

    A rotated or mistyped key must not take the whole admin page down; the
    thing it belongs to simply reads as unconfigured until someone re-enters it.
    """
    if not sealed:
        return {}
    try:
        raw = _fernet().decrypt(sealed.encode())
    except Exception:  # noqa: BLE001 - InvalidToken, bad key, corrupt column
        logger.warning("Stored credentials could not be decrypted")
        return {}
    try:
        data = json.loads(raw.decode())
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
