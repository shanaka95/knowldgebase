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

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import Agent, AgentStatus, UsageFeature, UsageKind, User
from app.services import agents as agent_service
from app.services import credits, usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-llm", tags=["agent_llm"])

# Bounded so one runaway agent cannot pin a connection indefinitely.
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0)

# Enough of the stream's end to hold the final frame, which is where the usage
# block is. Generous: a long tool-call chunk before it must not push it out.
_USAGE_TAIL_BYTES = 16_384


def _record_stream(meter: usage.UsageMeter, tail: bytes, model: str) -> None:
    """Read what a streamed turn cost out of the last frame that carries it."""
    text = tail.decode("utf-8", errors="ignore")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue  # a frame cut in half by the tail window
        if isinstance(chunk, dict) and chunk.get("usage"):
            meter.record(UsageKind.chat, chunk, model=model)
            return
    # Nothing said what it cost, but a call was still made and paid for.
    meter.record_counts(UsageKind.chat, model, usage.Counts(requests=1))


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
    """Pin the model, bound the cost, and drop anything that is ours to decide.

    An agent choosing its own model would let a prompt injection pick the most
    expensive one on the menu. The same reasoning applies to *how much* of it:
    a shard runs somebody's prompt, so it is the least trusted thing here that
    can spend money, and the knobs that multiply a bill are ours to set.
    """
    payload = dict(body)
    payload["model"] = settings.AGENT_LLM_MODEL
    for key in ("api_key", "extra_headers", "user"):
        payload.pop(key, None)

    # `n` asks the provider for several completions and bills for each. There
    # is no use for it here, and it is the cheapest possible amplification.
    payload.pop("n", None)
    payload.pop("best_of", None)

    # A turn may be long, but not unbounded: left alone this is whatever the
    # caller asked for, up to the model's ceiling, on every single request.
    ceiling = settings.AGENT_LLM_MAX_OUTPUT_TOKENS
    asked = payload.get("max_tokens")
    payload["max_tokens"] = (
        min(int(asked), ceiling) if isinstance(asked, int) and asked > 0 else ceiling
    )
    # Attribute the spend without telling the provider who the human is.
    payload["user"] = f"agent-{agent.id.hex[:16]}"

    # Steer OpenRouter's provider choice. Left to itself it can route to a
    # throttled endpoint and fail the turn while another provider serving the
    # same model is healthy - and, for this model, has four times the context.
    order = [
        p.strip() for p in settings.AGENT_LLM_PROVIDER_ORDER.split(",") if p.strip()
    ]
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
    raw = await request.body()
    if len(raw) > settings.AGENT_LLM_MAX_BODY_BYTES:
        # Read before parsing: a refusal after json.loads has already walked a
        # hundred megabytes has not saved anything.
        raise HTTPException(status_code=413, detail="That request is too large")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Expected a JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")

    # Whose bill this is. An agent is not an account, but it belongs to one,
    # and that account's limit is the ceiling on what its agents can spend.
    owner = session.get(User, agent.user_id)
    try:
        credits.ensure_credit(session, owner)
    except credits.CreditsExhausted as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    payload = _sanitise(body, agent)
    url = f"{str(settings.LLM_BASE_URL).rstrip('/')}{path}"
    streaming = bool(payload.get("stream"))
    # An agent is not an account, but it belongs to one, and its spend is on
    # the same bill as everything else that account does.
    meter = usage.UsageMeter(user_id=agent.user_id, feature=UsageFeature.agent)
    meter.operation()
    model = str(payload.get("model") or settings.AGENT_LLM_MODEL)

    client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        if not streaming:
            response = await client.post(url, json=payload, headers=_upstream_headers())
            content = response.content
            await client.aclose()
            parsed = _safe_json(content)
            if response.status_code >= 400:
                meter.failure(UsageKind.chat, model)
            else:
                meter.record(UsageKind.chat, parsed, model=model)
            await asyncio.to_thread(meter.flush)
            return JSONResponse(
                status_code=response.status_code,
                content=parsed,
            )

        # Streamed: hand the bytes straight through, closing the client only
        # once the body is exhausted.
        upstream = client.stream("POST", url, json=payload, headers=_upstream_headers())
        context = await upstream.__aenter__()

        async def _iterate() -> AsyncIterator[bytes]:
            # The bytes are still passed through untouched; only the tail is
            # kept, because the usage block rides on the last data: frame and
            # parsing the whole stream to find it would cost more than it is
            # worth on a path whose job is to be transparent.
            tail = b""
            try:
                async for chunk in context.aiter_raw():
                    tail = (tail + chunk)[-_USAGE_TAIL_BYTES:]
                    yield chunk
            finally:
                _record_stream(meter, tail, model)
                await upstream.__aexit__(None, None, None)
                await client.aclose()
                await asyncio.to_thread(meter.flush)

        return StreamingResponse(
            _iterate(),
            status_code=context.status_code,
            media_type=context.headers.get("content-type", "text/event-stream"),
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        meter.failure(UsageKind.chat, model)
        await asyncio.to_thread(meter.flush)
        logger.warning("Agent LLM proxy upstream error: %s", exc)
        raise HTTPException(
            status_code=502, detail="The model provider is unreachable"
        ) from exc


def _safe_json(content: bytes) -> Any:
    try:
        return json.loads(content or b"{}")
    except ValueError:
        return {
            "error": {"message": "The model provider returned an unreadable response"}
        }


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
