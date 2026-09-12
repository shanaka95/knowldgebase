from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import ApiKey, ApiKeyScope, TokenPayload, User
from app.services.embeddings import EmbeddingClient
from app.services.storage import ObjectStorage
from app.services.vectors import VectorStore

# Keeps the "Authorize" button in /docs working with email + password
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)
# Documents the alternative scheme (personal API key) in OpenAPI
api_key_scheme = HTTPBearer(auto_error=False, scheme_name="ApiKey")


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


@dataclass(slots=True)
class AuthContext:
    user: User
    api_key: ApiKey | None
    scopes: frozenset[str]

    @property
    def is_api_key(self) -> bool:
        return self.api_key is not None

    @property
    def can_write(self) -> bool:
        return ApiKeyScope.write in self.scopes


def _extract_bearer(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _user_from_api_key(session: Session, token: str) -> AuthContext:
    key = session.exec(
        select(ApiKey).where(ApiKey.key_hash == security.hash_api_key(token))
    ).first()
    now = datetime.now(UTC)
    if key is None or key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )
    if key.expires_at is not None and key.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="API key has expired"
        )
    user = session.get(User, key.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # throttle last_used_at writes to at most once a minute
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
        session.add(key)
        session.commit()
    scopes = (
        frozenset({ApiKeyScope.read, ApiKeyScope.write})
        if key.scope == ApiKeyScope.write
        else frozenset({ApiKeyScope.read})
    )
    return AuthContext(user=user, api_key=key, scopes=scopes)


def _user_from_jwt(session: Session, token: str) -> AuthContext:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return AuthContext(
        user=user,
        api_key=None,
        scopes=frozenset({ApiKeyScope.read, ApiKeyScope.write}),
    )


def get_auth_context(
    session: SessionDep,
    request: Request,
    _oauth: Annotated[str | None, Depends(reusable_oauth2)] = None,
    _key: Annotated[object | None, Depends(api_key_scheme)] = None,
) -> AuthContext:
    """Authenticate with either a JWT (web UI) or a personal API key (3rd party)."""
    token = _extract_bearer(request)
    if token.startswith(settings.API_KEY_PREFIX):
        return _user_from_api_key(session, token)
    return _user_from_jwt(session, token)


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


def get_current_user(ctx: AuthDep) -> User:
    return ctx.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_write(ctx: AuthDep) -> AuthContext:
    if not ctx.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key lacks write scope",
        )
    return ctx


WriteAuth = Annotated[AuthContext, Depends(require_write)]


def require_session_auth(ctx: AuthDep) -> User:
    """Account management is only allowed with an interactive (JWT) session."""
    if ctx.is_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint cannot be used with an API key",
        )
    return ctx.user


SessionUser = Annotated[User, Depends(require_session_auth)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


_embedding_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Shared embedding client so one HTTP connection pool serves every request."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client


EmbeddingsDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]


def get_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage | None = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Object storage not configured")
    return storage


StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


def get_vector_store(request: Request) -> VectorStore:
    vectors: VectorStore | None = getattr(request.app.state, "vectors", None)
    if vectors is None:
        raise HTTPException(status_code=503, detail="Vector store not configured")
    return vectors


VectorsDep = Annotated[VectorStore, Depends(get_vector_store)]
