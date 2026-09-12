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
from app.services.reranking import RerankClient, Reranker
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
    # A session token carries no type. Anything else signed with the same key -
    # above all the challenge handed out after a correct password - must not be
    # usable as a session, or two-factor would be decorative.
    if token_data.typ is not None:
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
    # A token minted before the account's current epoch was revoked - by a
    # password change, a reset, or a deliberate sign-out-everywhere. Treat it as
    # if it had never existed.
    if (token_data.sev or 0) < user.session_epoch:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
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


def get_optional_auth(
    session: SessionDep,
    request: Request,
    _oauth: Annotated[str | None, Depends(reusable_oauth2)] = None,
    _key: Annotated[object | None, Depends(api_key_scheme)] = None,
) -> AuthContext | None:
    """Who is calling, if anyone. For endpoints open to the public that say more
    to somebody signed in - the health report, which keeps its diagnostics for
    people who have an account rather than handing them to the internet.

    A bad credential is treated as no credential rather than an error: this is
    never the thing guarding anything.
    """
    try:
        return get_auth_context(session, request, _oauth, _key)
    except HTTPException:
        return None


OptionalAuth = Annotated[AuthContext | None, Depends(get_optional_auth)]


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


def get_current_active_superuser(current_user: SessionUser) -> User:
    """Administrator endpoints, which are account management by another name.

    Built on ``SessionUser`` rather than ``CurrentUser`` because everything
    behind it can set somebody's password or hand out ``is_superuser``. A key
    that could do that through ``/users/{id}`` would make the refusal on
    ``/users/me/password`` decorative, and a leaked key would be a takeover.
    """
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


_rerank_client: RerankClient | None = None


def get_reranker() -> Reranker | None:
    """The reranker, or None when the deployment has not configured one.

    Returning None rather than raising is deliberate: reranking sharpens
    retrieval, and search has to keep working without it.
    """
    global _rerank_client
    if not settings.rerank_enabled:
        return None
    if _rerank_client is None:
        _rerank_client = RerankClient()
    return _rerank_client


RerankerDep = Annotated[Reranker | None, Depends(get_reranker)]


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
