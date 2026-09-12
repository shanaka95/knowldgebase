from fastapi import APIRouter

from app.api.routes import (
    api_keys,
    ask,
    attachments,
    documents,
    folders,
    health,
    imports,
    login,
    namespaces,
    private,
    search,
    users,
    utils,
    workers,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(health.router)
api_router.include_router(namespaces.router)
api_router.include_router(folders.router)
api_router.include_router(documents.router)
api_router.include_router(attachments.router)
api_router.include_router(imports.router)
api_router.include_router(api_keys.router)
api_router.include_router(search.router)
api_router.include_router(ask.router)
api_router.include_router(workers.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
