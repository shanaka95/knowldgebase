"""An OpenAI-compatible endpoint the hosted agents talk to instead of the provider.

Each agent's profile holds a token for this proxy rather than a provider key.
That matters for three reasons, in descending order of importance:

* **The provider key never lands on a shard.** Thousands of `.env` files each
  holding the real OpenRouter key would turn any single file-disclosure bug into
  a total credential compromise.
* **Revocation is per agent.** Deleting an agent kills its access without
  rotating anything for anybody else.
* **Usage is attributable.** Every call arrives with an agent id, which is what
  per-account limits and tiering will need.

Only the two endpoints an agent actually uses are proxied. A general passthrough
would let a compromised agent reach whatever else the provider exposes.
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import Agent, AgentStatus
from app.services import agents as agent_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-llm", tags=["agent_llm"])

# Bounded so one runaway agent cannot pin a connection indefinitely.
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0)


def _authenticate(request: Request, session: SessionDep) -> Agent:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Not authenticated")
    agent = agent_service.agent_for_llm_token(session, token.strip())
    if agent is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if agent.status == AgentStatus.disabled:
        raise HTTPException(status_code=403, detail="This agent is disabled")
    return agent


def _upstream_headers() -> dict[str, str]:
    key = (settings.LLM_API_KEY or "").strip()
    if not key:
        raise HTTPException(
            status_code=503, detail="No model provider is configured for agents"
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _sanitise(body: dict[str, Any], agent: Agent) -> dict[str, Any]:
    """Pin the model and drop anything that is ours to decide.

    An agent choosing its own model would let a prompt injection pick the most
    expensive one on the menu.
    """
    payload = dict(body)
    payload["model"] = settings.AGENT_LLM_MODEL
    for key in ("api_key", "extra_headers", "user"):
        payload.pop(key, None)
    # Attribute the spend without telling the provider who the human is.
    payload["user"] = f"agent-{agent.id.hex[:16]}"

    # Steer OpenRouter's provider choice. Left to itself it can route to a
    # throttled endpoint and fail the turn while another provider serving the
    # same model is healthy - and, for this model, has four times the context.
    order = [p.strip() for p in settings.AGENT_LLM_PROVIDER_ORDER.split(",") if p.strip()]
    if order:
        payload["provider"] = {"order": order, "allow_fallbacks": True}

    # A model, not the model: the cheapest option is also the most contended,
    # and a 429 partway through a tool loop loses the whole turn. The list is
    # ours, so an injected prompt still cannot choose what it costs.
    fallbacks = [
        m.strip() for m in settings.AGENT_LLM_FALLBACK_MODELS.split(",") if m.strip()
    ]
    if fallbacks:
        payload["models"] = [payload["model"], *fallbacks]
    return payload


async def _proxy(path: str, request: Request, session: SessionDep) -> Any:
    agent = _authenticate(request, session)
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 - any unparsable body is the same error
        raise HTTPException(status_code=400, detail="Expected a JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")

    payload = _sanitise(body, agent)
    url = f"{str(settings.LLM_BASE_URL).rstrip('/')}{path}"
    streaming = bool(payload.get("stream"))

    client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        if not streaming:
            response = await client.post(url, json=payload, headers=_upstream_headers())
            content = response.content
            await client.aclose()
            return JSONResponse(
                status_code=response.status_code,
                content=_safe_json(content),
            )

        # Streamed: hand the bytes straight through, closing the client only
        # once the body is exhausted.
        upstream = client.stream("POST", url, json=payload, headers=_upstream_headers())
        context = await upstream.__aenter__()

        async def _iterate():
            try:
                async for chunk in context.aiter_raw():
                    yield chunk
            finally:
                await upstream.__aexit__(None, None, None)
                await client.aclose()

        return StreamingResponse(
            _iterate(),
            status_code=context.status_code,
            media_type=context.headers.get("content-type", "text/event-stream"),
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("Agent LLM proxy upstream error: %s", exc)
        raise HTTPException(status_code=502, detail="The model provider is unreachable") from exc


def _safe_json(content: bytes) -> Any:
    import json

    try:
        return json.loads(content or b"{}")
    except ValueError:
        return {"error": {"message": "The model provider returned an unreadable response"}}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, session: SessionDep) -> Any:
    return await _proxy("/chat/completions", request, session)


@router.get("/v1/models")
async def list_models(request: Request, session: SessionDep) -> Any:
    """The one model an agent may use.

    Answered locally rather than proxied: the provider's full catalogue is not
    an agent's business, and clients only call this to discover a default.
    """
    _authenticate(request, session)
    return {
        "object": "list",
        "data": [
            {
                "id": settings.AGENT_LLM_MODEL,
                "object": "model",
                "owned_by": "plusgpt",
            }
        ],
    }
