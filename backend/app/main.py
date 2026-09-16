import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anyio import to_thread
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.main import api_router
from app.core.config import settings
from app.services.storage import MinioStorage, ObjectStorage
from app.services.vectors import QdrantStore, VectorStore

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"

ASSET_PREFIX = "/assets/"
# A response that actually carries the file. Everything else is a failure to
# serve one, however it is spelled.
SERVED = frozenset({200, 206, 304})

# CORS headers, stripped from asset responses. A built asset is same-origin, and
# a same-origin request passes the CORS check whatever its mode, so these grant
# nothing - they only make the response depend on who asked.
CORS_RESPONSE_HEADERS = frozenset(
    {b"access-control-allow-origin", b"access-control-allow-credentials"}
)


def vary_without_origin(value: bytes) -> bytes:
    """`value` with `Origin` removed, keeping the rest of the list intact."""
    kept = [part.strip() for part in value.split(b",") if part.strip()]
    return b", ".join(part for part in kept if part.lower() != b"origin")


class AssetCacheHeaders:
    """Cache a built asset for ever; never cache a failure to serve one.

    Asset filenames carry a content hash, so a URL that answers with a file can
    be cached indefinitely, and `immutable` saves the revalidation round trip on
    every repeat visit.

    The same header on a *failure* is a trap. A 404 during a deploy, or a 502
    from a container that is still starting, is then cached for a year on the
    same terms - and `immutable` means the browser will not revalidate it even
    when somebody reloads. Chunk filenames are content hashes, so they are stable
    when their content is: 124 of 166 were identical across two consecutive
    builds here. One poisoned entry therefore keeps breaking every later build,
    which is how /search became permanently unloadable for one person while
    every one of its fifty-six chunks returned 200 to everybody else.

    It also strips the CORS headers, and `Origin` from `Vary`. Those made a
    second, independent copy of every asset in the CDN: browsers fetch the
    module graph in CORS mode, because Vite marks the entry `crossorigin`, so
    the copy they get is the `Origin` one, while curl, uptime checks and
    `Cache-Purge` by URL all see the other. When one `Vary: Origin` entry
    cached a 502 it stayed unreachable by every check that said the file was
    fine - 200 to everyone measuring, 502 to everyone browsing. Assets are
    same-origin, so the CORS headers grant nothing; dropping them leaves one
    copy, which is the one the checks look at.

    Raw ASGI rather than `@app.middleware("http")`, which is
    `BaseHTTPMiddleware`: that wraps the response body and gets in the way of
    the server-sent events an answer streams over.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(ASSET_PREFIX):
            await self.app(scope, receive, send)
            return

        async def send_with_cache_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                served = message["status"] in SERVED
                headers = []
                for key, value in message["headers"]:
                    lowered = key.lower()
                    if lowered == b"cache-control" or lowered in CORS_RESPONSE_HEADERS:
                        continue
                    if lowered == b"vary":
                        value = vary_without_origin(value)
                        if not value:
                            continue
                    headers.append((key, value))
                headers.append(
                    (
                        b"cache-control",
                        b"public, max-age=31536000, immutable"
                        if served
                        else b"no-store",
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cache_header)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


def build_storage() -> ObjectStorage:
    return MinioStorage()


def build_vector_store() -> VectorStore:
    return QdrantStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tests may pre-populate app.state with fakes before the lifespan runs.
    storage: ObjectStorage = getattr(app.state, "storage", None) or build_storage()
    vectors: VectorStore = getattr(app.state, "vectors", None) or build_vector_store()
    app.state.storage = storage
    app.state.vectors = vectors
    # Idempotent; tolerate unavailable services so the API still serves documents.
    try:
        await to_thread.run_sync(storage.ensure_bucket)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO bucket check failed: %s", exc)
    try:
        await vectors.ensure_collection()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant collection check failed: %s", exc)
    try:
        yield
    finally:
        await vectors.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last, so it is the outermost layer and sees the finished response -
# including the CORS headers, which it strips from assets. Added before
# CORSMiddleware it would run underneath it and they would be stamped back on.
app.add_middleware(AssetCacheHeaders)

app.include_router(api_router, prefix=settings.API_V1_STR)
if FRONTEND_DIR.exists():
    # SPA: unknown non-API paths must load the app shell so client-side routing works
    app.frontend("/", directory=FRONTEND_DIR, fallback="index.html")
