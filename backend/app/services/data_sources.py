"""Google Drive as a source of documents, without access to the rest of a Drive.

The scope is `drive.file`, which is the narrow one: it grants the application
nothing at all until the person picks a specific file in Google's own picker,
and then only that file. We cannot list their Drive, search it, or reach
anything they did not hand over - which is both the privacy property worth
having and the reason file selection must go through Google's picker rather
than a browser we build.

Three secrets, three different lifetimes:

  client secret   deployment-wide, entered by an admin, encrypted at rest,
                  never returned by the API and never sent to a browser
  refresh token   per person, the standing grant, encrypted at rest, used only
                  server-side and revoked at Google when they disconnect
  access token    minutes long, never stored, handed to the browser only so
                  Google's picker can authenticate the person to Google

The API key is the exception: the picker needs it in the browser, so it is
public by design and restricted by HTTP referrer at Google's end.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.secretbox import open_credentials, seal_credentials

__all__ = ["open_credentials", "seal_credentials"]
from app.models import (
    DataSourceConfig,
    DataSourceConnection,
    DataSourceType,
    User,
)

logger = logging.getLogger(__name__)

GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_ABOUT = "https://www.googleapis.com/drive/v3/about"

# What an admin has to supply per source. Server-driven so the admin form is
# not a second copy of this list in the frontend.
REQUIRED_FIELDS: dict[DataSourceType, list[str]] = {
    DataSourceType.google_drive: ["client_id", "client_secret", "api_key"],
}

STATE_TTL = timedelta(minutes=15)
HTTP_TIMEOUT = 30.0


class DataSourceError(RuntimeError):
    """Something went wrong talking to the provider, in terms a user can read."""


# ---------------------------------------------------------------------------
# Admin configuration
# ---------------------------------------------------------------------------


def required_fields_for(source: DataSourceType) -> list[str]:
    return list(REQUIRED_FIELDS.get(source, ()))


def redirect_uri(source: DataSourceType = DataSourceType.google_drive) -> str:
    """Where the provider sends the person back.

    Derived rather than configured separately, and surfaced in the admin API so
    it is copied into the Google console instead of retyped - a redirect URI
    that differs by a trailing slash fails with an error that says nothing
    useful about which end is wrong.
    """
    base = (settings.FRONTEND_HOST or "").rstrip("/")
    return f"{base}/api/v1/data-sources/{_slug(source)}/callback"


def _slug(source: DataSourceType) -> str:
    return str(source).replace("_", "-")


def config_for(session: Session, source: DataSourceType) -> DataSourceConfig | None:
    return session.exec(
        select(DataSourceConfig).where(DataSourceConfig.source_type == source)
    ).first()


def credentials_for(session: Session, source: DataSourceType) -> dict[str, str]:
    config = config_for(session, source)
    return open_credentials(config.credentials_encrypted if config else None)


def is_configured(config: DataSourceConfig | None) -> bool:
    if config is None:
        return False
    present = open_credentials(config.credentials_encrypted)
    return all(present.get(field) for field in required_fields_for(config.source_type))


def is_available(session: Session, source: DataSourceType) -> bool:
    """Configured and switched on: what a user is allowed to be offered."""
    config = config_for(session, source)
    return bool(config and config.enabled and is_configured(config))


# ---------------------------------------------------------------------------
# The OAuth handshake
# ---------------------------------------------------------------------------


def _seal_state(user_id: uuid.UUID, verifier: str) -> str:
    """Bind the callback to the person who started it.

    Sealed rather than signed so the browser carries an opaque blob: the PKCE
    verifier rides inside it, which keeps it off the server's own storage
    without ever being readable by whoever holds the URL.
    """
    return seal_credentials(
        {
            "user_id": str(user_id),
            "verifier": verifier,
            "nonce": secrets.token_urlsafe(16),
            "expires_at": (datetime.now(UTC) + STATE_TTL).isoformat(),
        }
    )


def open_state(state: str) -> tuple[uuid.UUID, str]:
    """Recover the user and PKCE verifier, or refuse."""
    data = open_credentials(state)
    if not data:
        raise DataSourceError("This sign-in link is not valid. Start again.")
    try:
        expires_at = datetime.fromisoformat(data["expires_at"])
        user_id = uuid.UUID(data["user_id"])
        verifier = data["verifier"]
    except (KeyError, ValueError) as exc:
        raise DataSourceError("This sign-in link is not valid. Start again.") from exc
    if expires_at < datetime.now(UTC):
        raise DataSourceError("This sign-in link has expired. Start again.")
    return user_id, verifier


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def authorization_url(session: Session, user: User) -> str:
    """Where to send someone to grant access.

    `prompt=consent` with `access_type=offline` because Google returns a refresh
    token only on the first grant otherwise, and an account reconnected after a
    disconnect would come back with no way to refresh.
    """
    creds = credentials_for(session, DataSourceType.google_drive)
    client_id = creds.get("client_id")
    if not client_id:
        raise DataSourceError("Google Drive is not configured on this deployment.")

    verifier, challenge = _pkce()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _seal_state(user.id, verifier),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


@dataclass(frozen=True)
class GrantedTokens:
    refresh_token: str
    access_token: str
    expires_in: int
    scope: str


async def exchange_code(session: Session, *, code: str, verifier: str) -> GrantedTokens:
    creds = credentials_for(session, DataSourceType.google_drive)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": creds.get("client_id", ""),
                "client_secret": creds.get("client_secret", ""),
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
    payload = _json(response, "Google refused the sign-in")
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        # Without one there is no standing grant, and the connection would stop
        # working silently when the access token expires an hour later.
        raise DataSourceError(
            "Google did not return a refresh token. Remove PlusGPT from your "
            "Google account's third-party access and connect again."
        )
    return GrantedTokens(
        refresh_token=refresh_token,
        access_token=payload.get("access_token", ""),
        expires_in=int(payload.get("expires_in", 0) or 0),
        scope=payload.get("scope", ""),
    )


async def access_token_for(
    session: Session, connection: DataSourceConnection
) -> tuple[str, int]:
    """Trade the stored refresh token for a short-lived access token."""
    stored = open_credentials(connection.credentials_encrypted)
    refresh_token = stored.get("refresh_token")
    if not refresh_token:
        raise DataSourceError("This connection is no longer valid. Reconnect it.")
    creds = credentials_for(session, connection.source_type)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "refresh_token": refresh_token,
                "client_id": creds.get("client_id", ""),
                "client_secret": creds.get("client_secret", ""),
                "grant_type": "refresh_token",
            },
        )
    if response.status_code in (400, 401):
        # The person revoked access at Google's end, or an admin rotated the
        # client. Either way the grant is gone and saying so beats retrying.
        raise DataSourceError(
            "Google has withdrawn this connection. Connect Google Drive again."
        )
    payload = _json(response, "Google would not renew this connection")
    return payload.get("access_token", ""), int(payload.get("expires_in", 0) or 0)


async def account_email(access_token: str) -> str | None:
    """Whose Drive this is, for the connection card.

    From Drive's own `about`, which `drive.file` already covers, rather than by
    asking for an extra profile scope just to print an address.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(
            DRIVE_ABOUT,
            params={"fields": "user(emailAddress)"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        return None
    try:
        return (response.json().get("user") or {}).get("emailAddress")
    except ValueError:
        return None


async def revoke(refresh_token: str) -> None:
    """Hand the grant back to Google. Best effort: the row goes either way."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            await client.post(REVOKE_ENDPOINT, data={"token": refresh_token})
    except httpx.HTTPError:
        logger.warning("Could not revoke a Google token; the local record is removed")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    size: int


async def describe_file(access_token: str, file_id: str) -> DriveFile:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(
            f"{DRIVE_FILES}/{file_id}",
            params={"fields": "id,name,mimeType,size", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code in (403, 404):
        # drive.file means we can only see what was picked. A file we cannot
        # read is one this person did not hand over in the picker.
        raise DataSourceError(
            "That file was not shared with PlusGPT. Pick it again in the chooser."
        )
    payload = _json(response, "Google would not describe that file")
    return DriveFile(
        file_id=str(payload.get("id") or file_id),
        name=str(payload.get("name") or "file"),
        mime_type=str(payload.get("mimeType") or "application/octet-stream"),
        size=int(payload.get("size") or 0),
    )


async def download_file(access_token: str, file_id: str, *, max_bytes: int) -> bytes:
    """Fetch the bytes, refusing anything past the import ceiling.

    Streamed and counted as it arrives rather than trusting the size Drive
    reported: the metadata and the download are two different requests, and only
    one of them is the thing we are about to store.
    """
    chunks: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        async with client.stream(
            "GET",
            f"{DRIVE_FILES}/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            if response.status_code in (403, 404):
                raise DataSourceError(
                    "That file was not shared with PlusGPT. Pick it again in "
                    "the chooser."
                )
            if response.status_code != 200:
                raise DataSourceError("Google would not send that file.")
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise DataSourceError(
                        f"That file is larger than the "
                        f"{settings.MAX_IMPORT_SIZE_MB} MB limit."
                    )
                chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


def connection_for(
    session: Session, user: User, source: DataSourceType
) -> DataSourceConnection | None:
    return session.exec(
        select(DataSourceConnection).where(
            col(DataSourceConnection.user_id) == user.id,
            col(DataSourceConnection.source_type) == source,
        )
    ).first()


def save_connection(
    session: Session,
    *,
    user_id: uuid.UUID,
    source: DataSourceType,
    refresh_token: str,
    scope: str,
    email: str | None,
) -> DataSourceConnection:
    """Record the grant, replacing any earlier one for this person and source."""
    existing = session.exec(
        select(DataSourceConnection).where(
            col(DataSourceConnection.user_id) == user_id,
            col(DataSourceConnection.source_type) == source,
        )
    ).first()
    connection = existing or DataSourceConnection(user_id=user_id, source_type=source)
    connection.credentials_encrypted = seal_credentials(
        {"refresh_token": refresh_token}
    )
    connection.scopes = scope
    connection.account_email = (email or None) and email[:320]
    connection.connected_at = datetime.now(UTC)
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def _json(response: httpx.Response, whenever: str) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = body.get("error_description") or body.get("error") or ""
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except ValueError:
            detail = ""
        raise DataSourceError(f"{whenever}: {detail or response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise DataSourceError(f"{whenever}: the reply was not readable") from exc
    return payload if isinstance(payload, dict) else {}
