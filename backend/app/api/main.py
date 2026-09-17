from fastapi import APIRouter

from app.api.routes import (
    admin_channels,
    admin_credits,
    admin_data_sources,
    admin_usage,
    admin_user_groups,
    admin_users,
    agent_control,
    agent_llm,
    agents,
    api_keys,
    ask,
    attachments,
    data_sources,
    documents,
    folders,
    health,
    imports,
    login,
    namespaces,
    notes,
    private,
    public,
    search,
    usage,
    user_notes,
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
api_router.include_router(notes.router)
api_router.include_router(user_notes.router)
api_router.include_router(attachments.router)
api_router.include_router(imports.router)
api_router.include_router(api_keys.router)
api_router.include_router(search.router)
api_router.include_router(ask.router)
api_router.include_router(usage.router)
api_router.include_router(workers.router)
api_router.include_router(agents.router)
api_router.include_router(data_sources.router)
api_router.include_router(admin_channels.router)
api_router.include_router(admin_data_sources.router)
api_router.include_router(admin_user_groups.router)
api_router.include_router(admin_credits.router)
api_router.include_router(admin_usage.router)
api_router.include_router(admin_users.router)
# Machine-to-machine, both of them. The gateway shards authenticate with a
# shared secret; agents authenticate with their own per-agent token.
api_router.include_router(agent_control.router)
api_router.include_router(agent_llm.router)
# Answers without a credential, by design: pages shared by link, and the
# facts of an invitation. See app/api/routes/public.py.
api_router.include_router(public.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
