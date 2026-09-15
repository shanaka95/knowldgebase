"""Connecting a Google Drive, and importing the files a person picks from it.

Access is granted per file, in Google's own picker, under the `drive.file`
scope: this server can never enumerate somebody's Drive, only fetch what they
handed over. Everything past that point is the ordinary import - the same
validation, the same object store, the same worker - because a PDF is a PDF
whichever door it came through.
"""

import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, col, select

from app.api.deps import AuthDep, SessionDep, SessionUser, StorageDep, WriteAuth
from app.core.config import settings
from app.models import (
    DataSourceConnection,
    DataSourcePublic,
    DataSourcesPublic,
    DataSourceType,
    GoogleDriveImportRequest,
    GoogleDrivePickerConfig,
    ImportJob,
    ImportJobsPublic,
    Message,
    User,
)
from app.services import data_sources as service
from app.services import parsing, quota
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/data-sources", tags=["data_sources"])

SOURCE = DataSourceType.google_drive


def _public(session: Session, user: User, source: DataSourceType) -> DataSourcePublic:
    connection = service.connection_for(session, user, source)
    return DataSourcePublic(
        source_type=source,
        available=service.is_available(session, source),
        connected=connection is not None,
        account_email=connection.account_email if connection else None,
        connected_at=connection.connected_at if connection else None,
    )


@router.get("/", response_model=DataSourcesPublic)
def read_data_sources(session: SessionDep, auth: AuthDep) -> Any:
    """Every source this build supports, and whether you have connected it."""
    return DataSourcesPublic(
        data=[_public(session, auth.user, source) for source in DataSourceType]
    )


@router.post("/google-drive/authorize", response_model=Message)
def authorize_google_drive(session: SessionDep, user: SessionUser) -> Any:
    """Where to send the browser to grant access. Session-only, like a login."""
    if not service.is_available(session, SOURCE):
        raise HTTPException(
            status_code=409,
            detail="Google Drive is not switched on for this deployment.",
        )
    try:
        return Message(message=service.authorization_url(session, user))
    except service.DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/google-drive/callback", include_in_schema=False)
async def google_drive_callback(
    session: SessionDep,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    """Where Google sends the person back.

    Unauthenticated by necessity - the browser arrives from Google carrying no
    session header - so the sealed `state` is the whole of the identity check.
    It names the user, cannot be read or forged without the server's key, and
    expires; a callback that fails it never touches the database.
    """
    destination = f"{(settings.FRONTEND_HOST or '').rstrip('/')}/data-sources"

    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{destination}?{urlencode(params)}", status_code=303)

    if error:
        return back(connected="0", reason=error[:120])
    if not code or not state:
        return back(connected="0", reason="missing_code")

    try:
        user_id, verifier = service.open_state(state)
        granted = await service.exchange_code(session, code=code, verifier=verifier)
    except service.DataSourceError as exc:
        return back(connected="0", reason=str(exc)[:160])

    if service.GOOGLE_DRIVE_SCOPE not in granted.scope.split():
        # Consent screens let people withhold a scope. Storing the grant anyway
        # would leave a connection that looks fine and fails on first use.
        await service.revoke(granted.refresh_token)
        return back(connected="0", reason="drive_access_not_granted")

    email = await service.account_email(granted.access_token)
    service.save_connection(
        session,
        user_id=user_id,
        source=SOURCE,
        refresh_token=granted.refresh_token,
        scope=granted.scope,
        email=email,
    )
    return back(connected="1")


@router.get("/google-drive/picker", response_model=GoogleDrivePickerConfig)
async def google_drive_picker(session: SessionDep, user: SessionUser) -> Any:
    """What the browser needs to open Google's picker.

    Session-only, and deliberately: this hands out a live access token for
    somebody's Google account, which is not something an API key with read
    scope should be able to ask for.
    """
    connection = service.connection_for(session, user, SOURCE)
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Google Drive first.")
    creds = service.credentials_for(session, SOURCE)
    try:
        access_token, expires_in = await service.access_token_for(session, connection)
    except service.DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GoogleDrivePickerConfig(
        client_id=creds.get("client_id", ""),
        api_key=creds.get("api_key", ""),
        access_token=access_token,
        expires_in=expires_in,
    )


@router.delete("/google-drive/connection", response_model=Message)
async def disconnect_google_drive(session: SessionDep, user: SessionUser) -> Any:
    """Hand the grant back to Google, then forget it here."""
    connection = service.connection_for(session, user, SOURCE)
    if connection is None:
        return Message(message="Google Drive was not connected.")
    stored = service.open_credentials(connection.credentials_encrypted)
    refresh_token = stored.get("refresh_token")
    session.delete(connection)
    session.commit()
    if refresh_token:
        # After the row is gone: a revoke that fails must not leave a
        # connection the person has already been told is disconnected.
        await service.revoke(refresh_token)
    return Message(message="Google Drive disconnected.")


@router.post("/google-drive/import", response_model=ImportJobsPublic)
async def import_from_google_drive(
    session: SessionDep,
    auth: WriteAuth,
    storage: StorageDep,
    body: GoogleDriveImportRequest,
) -> Any:
    """Fetch the files someone picked and queue them as ordinary imports."""
    from app.api.routes.imports import _check_destination, _import_key

    _check_destination(session, auth.user, body.namespace_id, body.folder_id)
    # Before a byte is fetched from Google. Each picked file becomes one page,
    # and downloading twenty of them only to refuse them would waste the
    # transfer and leave objects in storage behind.
    try:
        quota.ensure_page_capacity(session, auth.user.id, wanted=len(body.files))
    except quota.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    connection = session.exec(
        select(DataSourceConnection).where(
            col(DataSourceConnection.user_id) == auth.user.id,
            col(DataSourceConnection.source_type) == SOURCE,
        )
    ).first()
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Google Drive first.")

    try:
        access_token, _ = await service.access_token_for(session, connection)
    except service.DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    max_bytes = settings.MAX_IMPORT_SIZE_MB * 1024 * 1024
    jobs: list[ImportJob] = []
    for picked in body.files:
        described = await _describe(access_token, picked.file_id)
        if not parsing.is_supported(described.mime_type, described.name):
            raise HTTPException(
                status_code=415,
                detail=(
                    f"{described.name} is not a PDF or an image, so it cannot "
                    "be turned into a page."
                ),
            )
        data = await _download(access_token, described.file_id, max_bytes=max_bytes)
        job_id = uuid.uuid4()
        object_key = _store_bytes(
            storage,
            data,
            key=_import_key(body.namespace_id, job_id),
            filename=described.name,
            content_type=described.mime_type,
        )
        jobs.append(
            ImportJob(
                id=job_id,
                namespace_id=body.namespace_id,
                folder_id=body.folder_id,
                created_by=auth.user.id,
                title=None,
                doc_type=(body.doc_type or "").strip()[:100] or None,
                prompt=(body.prompt or "").strip() or None,
                filename=described.name,
                content_type=described.mime_type[:127],
                size=len(data),
                object_key=object_key,
                max_attempts=3,
            )
        )

    for job in jobs:
        session.add(job)
    session.commit()
    for job in jobs:
        session.refresh(job)

    from app.api.routes.imports import to_import_job_public

    return ImportJobsPublic(
        data=[to_import_job_public(session, job) for job in jobs], count=len(jobs)
    )


async def _describe(access_token: str, file_id: str) -> service.DriveFile:
    try:
        return await service.describe_file(access_token, file_id)
    except service.DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _download(access_token: str, file_id: str, *, max_bytes: int) -> bytes:
    try:
        return await service.download_file(access_token, file_id, max_bytes=max_bytes)
    except service.DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _store_bytes(
    storage: ObjectStorage,
    data: bytes,
    *,
    key: str,
    filename: str,
    content_type: str,
) -> str:
    from io import BytesIO
    from pathlib import PurePosixPath

    suffix = PurePosixPath(filename).suffix.lower()[:16]
    object_key = f"{key}{suffix}"
    storage.put(object_key, BytesIO(data), len(data), content_type)
    return object_key
