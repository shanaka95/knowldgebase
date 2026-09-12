import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anyio import to_thread
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.services.storage import MinioStorage, ObjectStorage
from app.services.vectors import QdrantStore, VectorStore

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"


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

app.include_router(api_router, prefix=settings.API_V1_STR)
if FRONTEND_DIR.exists():
    # SPA: unknown non-API paths must load the app shell so client-side routing works
    app.frontend("/", directory=FRONTEND_DIR, fallback="index.html")
