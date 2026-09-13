"""The control plane a gateway shard talks to.

One endpoint matters: given a platform identity, whose agent should this message
go to? The gateway asks on every inbound message it cannot already answer from
its cache, and drops the message if we say nobody.

This is the whole of end-user authentication for the channel side, because
Hermes has none of its own - its own design notes say so plainly: *"multiplexing
isolates profiles; it does not authenticate or authorize end users."* So the
rules live here:

* An identity we have never seen resolves to nobody, and nobody is not a
  fallback. Answering "the default profile" would drop a stranger's message
  into somebody's agent.
* A message may *become* a link if it carries a valid one-time code, which is
  why the gateway passes the text along. That is the only way an unknown sender
  ever becomes a known one.
* Nothing here is exposed to users. The shard authenticates with a shared
  secret, and a deployment that forgets to set one gets no route resolution at
  all rather than an open one.
"""

import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import Agent, ChannelType
from app.services import channels as channel_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-control", tags=["agent_control"])


def require_shard(request: Request) -> None:
    """Authenticate a gateway shard by shared secret.

    Fails closed when unset: an unconfigured deployment must not expose an
    endpoint that maps phone numbers to accounts.
    """
    expected = (settings.AGENT_CONTROL_TOKEN or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Agent control is not configured")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(status_code=401, detail="Not authenticated")


class _RouteRequest(dict):
    pass


@router.post("/route", dependencies=[Depends(require_shard)])
def resolve_route(session: SessionDep, body: dict[str, Any]) -> dict[str, Any]:
    """Which profile, if any, an inbound sender belongs to.

    Always 200 with ``{"profile": null}`` for an unknown sender rather than 404,
    so a transport error and a genuine "nobody" stay distinguishable to the
    caller - it drops the message on both, but only one is worth alerting on.
    """
    platform = str(body.get("platform") or "").strip().lower()
    chat_id = str(body.get("chat_id") or "").strip()
    message_text = body.get("message_text")
    display_name = body.get("display_name")

    if not platform or not chat_id:
        return {"profile": None}
    try:
        channel = ChannelType(platform)
    except ValueError:
        # A platform we do not offer. Nobody can be linked on it by definition.
        return {"profile": None}

    connection = channel_service.find_connection(
        session, channel=channel, platform_identity=chat_id
    )

    if connection is None and message_text:
        candidate = channel_service.find_code_in(str(message_text))
        if candidate:
            result = channel_service.redeem_code(
                session,
                code=candidate,
                channel=channel,
                platform_identity=chat_id,
                display_name=str(display_name) if display_name else None,
            )
            if result.connection is not None:
                connection = result.connection
                session.commit()
                logger.info("Linked a %s identity to agent %s", platform, connection.agent_id)
            else:
                session.rollback()
                logger.info("Rejected a %s link attempt: %s", platform, result.reason)

    if connection is None:
        return {"profile": None}

    agent = session.get(Agent, connection.agent_id)
    if agent is None:
        return {"profile": None}

    _touch(session, connection)
    return {"profile": agent.profile_name, "agent_id": str(agent.id)}


def _touch(session: Session, connection: Any) -> None:
    """Record that this identity is live, for the dashboard.

    Best effort: failing to update a timestamp must never cost someone their
    reply, so an error here is swallowed rather than raised.
    """
    try:
        connection.last_seen_at = datetime.now(UTC)
        session.add(connection)
        session.commit()
    except Exception:  # noqa: BLE001 - bookkeeping only
        session.rollback()
        logger.debug("Could not update last_seen_at", exc_info=True)


@router.get("/health", dependencies=[Depends(require_shard)])
def control_health(session: SessionDep) -> dict[str, Any]:
    """Lets a shard confirm its token works before it starts taking traffic."""
    count = len(session.exec(select(Agent.id)).all())
    return {"status": "ok", "agents": count}
