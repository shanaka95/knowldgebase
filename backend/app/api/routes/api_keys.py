import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep, SessionUser
from app.core.security import generate_api_key
from app.models import (
    ApiKey,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyPublic,
    ApiKeysPublic,
    ApiKeyUpdate,
    Message,
)

router = APIRouter(prefix="/api-keys", tags=["api_keys"])


def _own_key(session: SessionDep, user_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
    key = session.get(ApiKey, key_id)
    if key is None or key.user_id != user_id:
        raise HTTPException(status_code=404, detail="API key not found")
    return key


@router.get("/", response_model=ApiKeysPublic)
def read_api_keys(session: SessionDep, current_user: SessionUser) -> Any:
    """Personal API keys of the current user (hashes are never returned)."""
    keys = session.exec(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id)
        .order_by(col(ApiKey.created_at).desc())
    ).all()
    data = [ApiKeyPublic.model_validate(k) for k in keys]
    return ApiKeysPublic(data=data, count=len(data))


@router.post("/", response_model=ApiKeyCreated)
def create_api_key(
    session: SessionDep, current_user: SessionUser, key_in: ApiKeyCreate
) -> Any:
    """Create a key. The plaintext ``key`` is returned once and cannot be recovered."""
    plain, prefix, digest = generate_api_key()
    expires_at = (
        datetime.now(UTC) + timedelta(days=key_in.expires_in_days)
        if key_in.expires_in_days
        else None
    )
    key = ApiKey(
        user_id=current_user.id,
        name=key_in.name,
        key_prefix=prefix,
        key_hash=digest,
        scope=key_in.scope,
        expires_at=expires_at,
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    return ApiKeyCreated(**ApiKeyPublic.model_validate(key).model_dump(), key=plain)


@router.patch("/{key_id}", response_model=ApiKeyPublic)
def update_api_key(
    session: SessionDep,
    current_user: SessionUser,
    key_id: uuid.UUID,
    key_in: ApiKeyUpdate,
) -> Any:
    key = _own_key(session, current_user.id, key_id)
    key.name = key_in.name
    session.add(key)
    session.commit()
    session.refresh(key)
    return key


@router.delete("/{key_id}")
def revoke_api_key(
    session: SessionDep, current_user: SessionUser, key_id: uuid.UUID
) -> Message:
    """Revoke a key (idempotent). Revoked keys are kept for audit."""
    key = _own_key(session, current_user.id, key_id)
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        session.add(key)
        session.commit()
    return Message(message="API key revoked")
