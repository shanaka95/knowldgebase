"""Google Drive: a grant that is per-file, per-person, and never readable back.

The scope is `drive.file`, so the server can reach only what somebody picked.
What these tests hold down is everything around that: the client secret never
comes back out, a callback cannot be forged into a connection on somebody
else's account, and a file that is not a PDF or an image is refused before it
becomes a page.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    DataSourceConfig,
    DataSourceConnection,
    DataSourceType,
    ImportJob,
)
from app.services import data_sources as service
from tests.utils.kb import (
    API,
    create_namespace,
    create_user_with_password,
    login,
)


@pytest.fixture(autouse=True)
def _clean_slate(db: Session, monkeypatch):
    """A Fernet key, and no leftovers from an earlier run.

    The routes commit through their own session, so rows written by one test
    outlive it. A deployment-wide config row is exactly the kind of leftover
    that makes "this cannot be switched on yet" pass against a source some
    earlier test had already finished configuring.
    """
    monkeypatch.setattr(
        settings, "CHANNEL_SECRET_KEY", "hn3mS8p0kq1lZ2xY4vB6wC8dE0fG2hJ4kL6mN8pQ0rM="
    )
    for row in db.exec(select(DataSourceConnection)).all():
        db.delete(row)
    for row in db.exec(select(DataSourceConfig)).all():
        db.delete(row)
    db.commit()


ADMIN = f"{API}/admin/data-sources"
SOURCES = f"{API}/data-sources"
CALLBACK = f"{SOURCES}/google-drive/callback"


def _configure(client: TestClient, headers: dict[str, str], *, enabled: bool = True):
    client.put(
        f"{ADMIN}/google_drive",
        headers=headers,
        json={
            "credentials": {
                "client_id": "cid.apps.googleusercontent.com",
                "client_secret": "the-client-secret",
                "api_key": "the-api-key",
            }
        },
    )
    if enabled:
        client.put(f"{ADMIN}/google_drive", headers=headers, json={"enabled": True})


def _connect(db: Session, user_id: uuid.UUID, refresh: str = "refresh-token") -> None:
    service.save_connection(
        db,
        user_id=user_id,
        source=DataSourceType.google_drive,
        refresh_token=refresh,
        scope=service.GOOGLE_DRIVE_SCOPE,
        email="someone@example.com",
    )


def _jobs_in(db: Session, namespace_id: uuid.UUID) -> list[ImportJob]:
    """Scoped on purpose: other tests in this file queue their own imports."""
    return list(
        db.exec(select(ImportJob).where(ImportJob.namespace_id == namespace_id)).all()
    )


# --- administration ---------------------------------------------------------


def test_only_an_admin_can_configure_a_data_source(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(f"{ADMIN}/", headers=normal_user_token_headers).status_code == 403
    )
    assert (
        client.put(
            f"{ADMIN}/google_drive",
            headers=normal_user_token_headers,
            json={"enabled": True},
        ).status_code
        == 403
    )


def test_the_client_secret_never_comes_back_out(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.put(
        f"{ADMIN}/google_drive",
        headers=superuser_token_headers,
        json={"credentials": {"client_secret": "super-secret-value"}},
    )
    assert response.status_code == 200, response.text
    assert "super-secret-value" not in response.text
    assert "client_secret" in response.json()["present_fields"]
    listing = client.get(f"{ADMIN}/", headers=superuser_token_headers)
    assert "super-secret-value" not in listing.text


def test_credentials_are_encrypted_at_rest(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    client.put(
        f"{ADMIN}/google_drive",
        headers=superuser_token_headers,
        json={"credentials": {"client_secret": "plaintext-would-be-bad"}},
    )
    row = db.exec(
        select(DataSourceConfig).where(
            DataSourceConfig.source_type == DataSourceType.google_drive
        )
    ).first()
    assert row is not None and row.credentials_encrypted
    assert "plaintext-would-be-bad" not in row.credentials_encrypted


def test_a_half_configured_source_cannot_be_switched_on(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Enabled without credentials is a card that fails when somebody clicks it."""
    client.put(
        f"{ADMIN}/google_drive",
        headers=superuser_token_headers,
        json={"credentials": {"client_id": "only-this-one"}},
    )
    response = client.put(
        f"{ADMIN}/google_drive", headers=superuser_token_headers, json={"enabled": True}
    )
    assert response.status_code == 422
    assert "client_secret" in response.text


def test_the_redirect_uri_is_published_for_the_console(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """It has to match Google's registration exactly, so it is not retyped."""
    body = client.get(f"{ADMIN}/", headers=superuser_token_headers).json()
    drive = next(d for d in body["data"] if d["source_type"] == "google_drive")
    assert drive["redirect_uri"].endswith(
        "/api/v1/data-sources/google-drive/callback"
    )


# --- what a user sees -------------------------------------------------------


def test_a_source_an_admin_has_not_enabled_is_not_offered(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    headers = login(client, user, pw)
    body = client.get(f"{SOURCES}/", headers=headers).json()
    drive = next(d for d in body["data"] if d["source_type"] == "google_drive")
    assert drive["available"] is False
    assert drive["connected"] is False

    # And starting the flow is refused rather than sending somebody to Google
    # with an empty client id.
    assert (
        client.post(f"{SOURCES}/google-drive/authorize", headers=headers).status_code
        == 409
    )


def test_the_picker_needs_an_interactive_session_not_an_api_key(
    client: TestClient, db: Session
) -> None:
    """It hands out a live Google access token; a read-scoped key must not."""
    user, pw = create_user_with_password(db)
    _connect(db, user.id)
    headers = login(client, user, pw)
    key = client.post(
        f"{API}/api-keys/", headers=headers, json={"name": "ro", "scope": "read"}
    ).json()["key"]
    response = client.get(
        f"{SOURCES}/google-drive/picker", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 403


# --- the callback -----------------------------------------------------------


@respx.mock
def test_a_forged_state_is_refused_before_google_is_called(
    client: TestClient, db: Session
) -> None:
    """The state is the only identity the callback has, so a bad one stops here.

    Asserting the token endpoint was never reached, rather than only that no
    row appeared: a callback that got as far as talking to Google and failed
    there would look identical from the database.
    """
    token = respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={})
    )
    before = len(db.exec(select(DataSourceConnection)).all())

    response = client.get(
        CALLBACK,
        params={"code": "anything", "state": "not-a-sealed-state"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "connected=0" in response.headers["location"]
    assert not token.called, "an unreadable state never reaches the exchange"
    assert len(db.exec(select(DataSourceConnection)).all()) == before


@respx.mock
def test_a_state_that_was_not_sealed_by_this_server_is_refused(
    client: TestClient, db: Session
) -> None:
    """The attack the seal exists to stop.

    A state is just a string in a URL. If a well-formed one were trusted,
    anyone could name somebody else's user id in it and have their own Google
    grant recorded against that person's account - or a victim's Drive attached
    to the attacker's. It has to be unforgeable, not merely well-shaped.
    """
    import json

    token = respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "r",
                "access_token": "a",
                "expires_in": 3599,
                "scope": service.GOOGLE_DRIVE_SCOPE,
            },
        )
    )
    victim, _ = create_user_with_password(db)
    forged = json.dumps(
        {
            "user_id": str(victim.id),
            "verifier": "v",
            "nonce": "n",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }
    )

    response = client.get(
        CALLBACK, params={"code": "anything", "state": forged}, follow_redirects=False
    )

    assert "connected=0" in response.headers["location"]
    assert not token.called, "a state we did not seal never reaches the exchange"
    assert service.connection_for(db, victim, DataSourceType.google_drive) is None


@respx.mock
def test_an_expired_state_is_refused_before_google_is_called(
    client: TestClient, db: Session
) -> None:
    """A sealed state stays readable forever; the expiry is what bounds it."""
    token = respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "r",
                "access_token": "a",
                "expires_in": 3599,
                "scope": service.GOOGLE_DRIVE_SCOPE,
            },
        )
    )
    user, _ = create_user_with_password(db)
    stale = service.seal_credentials(
        {
            "user_id": str(user.id),
            "verifier": "v",
            "nonce": "n",
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        }
    )

    response = client.get(
        CALLBACK, params={"code": "anything", "state": stale}, follow_redirects=False
    )

    assert response.status_code == 303
    assert "connected=0" in response.headers["location"]
    assert not token.called, "an expired state never reaches the exchange"
    assert service.connection_for(db, user, DataSourceType.google_drive) is None


@respx.mock
def test_the_connection_is_recorded_for_the_user_named_in_the_state(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _configure(client, superuser_token_headers)
    owner, _ = create_user_with_password(db)
    other, _ = create_user_with_password(db)

    respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "the-refresh-token",
                "access_token": "the-access-token",
                "expires_in": 3599,
                "scope": service.GOOGLE_DRIVE_SCOPE,
            },
        )
    )
    respx.get(service.DRIVE_ABOUT).mock(
        return_value=httpx.Response(
            200, json={"user": {"emailAddress": "owner@example.com"}}
        )
    )

    state = service._seal_state(owner.id, "verifier")
    response = client.get(
        CALLBACK, params={"code": "auth-code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "connected=1" in response.headers["location"]

    connection = service.connection_for(db, owner, DataSourceType.google_drive)
    assert connection is not None
    assert connection.account_email == "owner@example.com"
    assert service.connection_for(db, other, DataSourceType.google_drive) is None
    # And the token that is the whole grant is not sitting in the clear.
    assert "the-refresh-token" not in (connection.credentials_encrypted or "")


@respx.mock
def test_withholding_drive_access_is_not_stored_as_a_connection(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """A consent screen lets people untick the scope. A row stored anyway
    would look connected and fail on first use."""
    _configure(client, superuser_token_headers)
    user, _ = create_user_with_password(db)

    respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "the-refresh-token",
                "access_token": "a",
                "expires_in": 3599,
                "scope": "openid",
            },
        )
    )
    revoked = respx.post(service.REVOKE_ENDPOINT).mock(
        return_value=httpx.Response(200)
    )

    response = client.get(
        CALLBACK,
        params={"code": "auth-code", "state": service._seal_state(user.id, "v")},
        follow_redirects=False,
    )
    assert "connected=0" in response.headers["location"]
    assert service.connection_for(db, user, DataSourceType.google_drive) is None
    assert revoked.called, "the grant we are not keeping is handed back"


# --- importing --------------------------------------------------------------


@respx.mock
def test_only_pdfs_and_images_become_pages(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _configure(client, superuser_token_headers)
    user, pw = create_user_with_password(db)
    ns = create_namespace(db, user)
    _connect(db, user.id)
    headers = login(client, user, pw)

    respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
    )
    respx.get(f"{service.DRIVE_FILES}/sheet1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "sheet1",
                "name": "Budget.xlsx",
                "mimeType": (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                "size": "10",
            },
        )
    )

    response = client.post(
        f"{SOURCES}/google-drive/import",
        headers=headers,
        json={
            "files": [{"file_id": "sheet1", "name": "Budget.xlsx"}],
            "namespace_id": str(ns.id),
        },
    )
    assert response.status_code == 415, response.text
    assert _jobs_in(db, ns.id) == [], "nothing queued from a refused file"


@respx.mock
def test_a_picked_pdf_becomes_an_ordinary_import(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _configure(client, superuser_token_headers)
    user, pw = create_user_with_password(db)
    ns = create_namespace(db, user)
    _connect(db, user.id)
    headers = login(client, user, pw)

    respx.post(service.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
    )
    respx.get(f"{service.DRIVE_FILES}/pdf1").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "id": "pdf1",
                    "name": "Tenancy agreement.pdf",
                    "mimeType": "application/pdf",
                    "size": "8",
                },
            ),
            httpx.Response(200, content=b"%PDF-1.4"),
        ]
    )

    response = client.post(
        f"{SOURCES}/google-drive/import",
        headers=headers,
        json={
            "files": [{"file_id": "pdf1", "name": "Tenancy agreement.pdf"}],
            "namespace_id": str(ns.id),
            "doc_type": "Contract",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    job = db.exec(select(ImportJob)).one()
    assert job.filename == "Tenancy agreement.pdf"
    assert job.namespace_id == ns.id
    assert job.created_by == user.id
    assert job.doc_type == "Contract"
    # Filed under the space that owns it, like every other import.
    assert job.object_key.startswith(f"ns/{ns.id}/imports/")


@respx.mock
def test_files_cannot_be_imported_into_someone_elses_space(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _configure(client, superuser_token_headers)
    owner, _ = create_user_with_password(db)
    stranger, stranger_pw = create_user_with_password(db)
    theirs = create_namespace(db, owner)
    _connect(db, stranger.id)
    headers = login(client, stranger, stranger_pw)

    response = client.post(
        f"{SOURCES}/google-drive/import",
        headers=headers,
        json={
            "files": [{"file_id": "pdf1", "name": "x.pdf"}],
            "namespace_id": str(theirs.id),
        },
    )
    assert response.status_code in (403, 404)
    assert _jobs_in(db, theirs.id) == [], "nothing landed in the owner's space"


def test_importing_without_a_connection_is_refused(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _configure(client, superuser_token_headers)
    user, pw = create_user_with_password(db)
    ns = create_namespace(db, user)
    headers = login(client, user, pw)

    response = client.post(
        f"{SOURCES}/google-drive/import",
        headers=headers,
        json={
            "files": [{"file_id": "pdf1", "name": "x.pdf"}],
            "namespace_id": str(ns.id),
        },
    )
    assert response.status_code == 409


# --- disconnecting ----------------------------------------------------------


@respx.mock
def test_disconnecting_revokes_the_grant_at_google(
    client: TestClient, db: Session
) -> None:
    user, pw = create_user_with_password(db)
    _connect(db, user.id, refresh="token-to-revoke")
    headers = login(client, user, pw)
    revoked = respx.post(service.REVOKE_ENDPOINT).mock(
        return_value=httpx.Response(200)
    )

    response = client.delete(f"{SOURCES}/google-drive/connection", headers=headers)
    assert response.status_code == 200
    assert service.connection_for(db, user, DataSourceType.google_drive) is None
    assert revoked.called, "a grant nobody can see is still a grant"


def test_one_persons_connection_is_not_anothers(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    other, other_pw = create_user_with_password(db)
    _connect(db, owner.id)
    headers = login(client, other, other_pw)

    body = client.get(f"{SOURCES}/", headers=headers).json()
    drive = next(d for d in body["data"] if d["source_type"] == "google_drive")
    assert drive["connected"] is False
    assert drive["account_email"] is None
