"""Deployment-wide data source setup, for administrators.

Same contract as the channels admin: credentials go in and never come back
out. The API reports which fields are set, never what they are set to, so an
admin session that has been taken over cannot be used to read the Google client
secret back out of the deployment.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    DataSourceConfig,
    DataSourceConfigPublic,
    DataSourceConfigsPublic,
    DataSourceConfigUpdate,
    DataSourceType,
)
from app.services import data_sources as service

router = APIRouter(
    prefix="/admin/data-sources",
    tags=["admin_data_sources"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _to_public(
    source: DataSourceType, config: DataSourceConfig | None
) -> DataSourceConfigPublic:
    present = service.open_credentials(config.credentials_encrypted if config else None)
    return DataSourceConfigPublic(
        source_type=source,
        enabled=bool(config and config.enabled),
        configured=service.is_configured(config),
        required_fields=service.required_fields_for(source),
        present_fields=sorted(k for k, v in present.items() if v),
        redirect_uri=service.redirect_uri(source),
        updated_at=config.updated_at if config else None,
    )


@router.get("/", response_model=DataSourceConfigsPublic)
def read_data_sources(session: SessionDep) -> Any:
    rows = {c.source_type: c for c in session.exec(select(DataSourceConfig)).all()}
    return DataSourceConfigsPublic(
        data=[_to_public(source, rows.get(source)) for source in DataSourceType]
    )


@router.put("/{source_type}", response_model=DataSourceConfigPublic)
def update_data_source(
    session: SessionDep, source_type: DataSourceType, body: DataSourceConfigUpdate
) -> Any:
    config = service.config_for(session, source_type)
    if config is None:
        config = DataSourceConfig(source_type=source_type)
        session.add(config)

    if body.credentials is not None:
        # Merged, not replaced: an admin correcting one field should not have to
        # retype the client secret, which they cannot read back to check.
        merged = service.open_credentials(config.credentials_encrypted)
        for key, value in body.credentials.items():
            cleaned = (value or "").strip()
            if cleaned:
                merged[key] = cleaned
            else:
                merged.pop(key, None)
        config.credentials_encrypted = (
            service.seal_credentials(merged) if merged else None
        )

    if body.enabled is not None:
        if body.enabled and not service.is_configured(config):
            missing = [
                field
                for field in service.required_fields_for(source_type)
                if not service.open_credentials(config.credentials_encrypted).get(field)
            ]
            raise HTTPException(
                status_code=422,
                detail=f"Set {', '.join(missing)} before switching this on.",
            )
        config.enabled = body.enabled

    config.updated_at = None
    session.add(config)
    session.commit()
    session.refresh(config)
    return _to_public(source_type, config)
