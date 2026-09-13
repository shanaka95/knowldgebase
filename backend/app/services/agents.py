"""Creating, updating and destroying an agent, credentials included.

An agent owns two secrets: a knowledge-base API key scoped to its owner, and a
token for the LLM proxy. Both are minted here and written into the profile's
`.env`, and both are revoked here when the agent goes away.

Order matters on the way out. Credentials are revoked *before* the profile
directory is removed, so a delete that fails halfway leaves an inert directory
rather than a live key sitting on a shard with nothing tracking it.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.security import generate_api_key
from app.models import (
    Agent,
    AgentStatus,
    ApiKey,
    ApiKeyScope,
    ChannelConnection,
    ChannelConnectionPublic,
    AgentPublic,
)
from app.services import agent_provisioning as provisioning

logger = logging.getLogger(__name__)

LLM_TOKEN_PREFIX = "agl_"


def generate_llm_token() -> tuple[str, str]:
    plain = f"{LLM_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return plain, hashlib.sha256(plain.encode()).hexdigest()


def hash_llm_token(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def mask_identity(channel: str, identity: str) -> str:
    """Enough of a platform id to recognise, not enough to republish.

    A phone number is personal data and the dashboard is only confirming which
    account is connected, so the middle goes.
    """
    value = str(identity or "")
    if len(value) <= 4:
        return "•" * len(value)
    return f"{value[:2]}{'•' * max(3, len(value) - 6)}{value[-3:]}"


def to_public(agent: Agent, connections: list[ChannelConnection]) -> AgentPublic:
    return AgentPublic(
        id=agent.id,
        name=agent.name,
        persona=agent.persona,
        status=agent.status,
        status_detail=agent.status_detail,
        created_at=agent.created_at,
        connections=[
            ChannelConnectionPublic(
                id=c.id,
                channel_type=c.channel_type,
                identity_hint=mask_identity(c.channel_type, c.platform_identity),
                display_name=c.display_name,
                created_at=c.created_at,
            )
            for c in connections
        ],
    )


def connections_for(session: Session, agent_id: uuid.UUID) -> list[ChannelConnection]:
    return list(
        session.exec(
            select(ChannelConnection)
            .where(ChannelConnection.agent_id == agent_id)
            .order_by(col(ChannelConnection.created_at).asc())
        ).all()
    )


def create_agent(
    session: Session, *, user_id: uuid.UUID, name: str, persona: str | None
) -> Agent:
    """Create the row, mint credentials, and lay down the profile directory."""
    agent_id = uuid.uuid4()
    profile_name = provisioning.profile_name_for(agent_id)
    shard_id = provisioning.shard_for(agent_id)

    # The agent writes to the knowledge base - filing documents is half the
    # point - so it needs a write-scoped key.
    plain_key, prefix, digest = generate_api_key()
    api_key = ApiKey(
        user_id=user_id,
        name=f"Agent: {name}",
        key_prefix=prefix,
        key_hash=digest,
        scope=ApiKeyScope.write,
    )
    session.add(api_key)
    session.flush()

    plain_llm, llm_hash = generate_llm_token()

    agent = Agent(
        id=agent_id,
        user_id=user_id,
        name=name,
        persona=persona,
        profile_name=profile_name,
        shard_id=shard_id,
        status=AgentStatus.provisioning,
        api_key_id=api_key.id,
        llm_token_hash=llm_hash,
    )
    session.add(agent)
    session.flush()

    try:
        provisioning.write_profile(
            shard_id=shard_id,
            profile_name=profile_name,
            agent_name=name,
            persona=persona,
            api_key=plain_key,
            llm_token=plain_llm,
        )
    except OSError as exc:
        # The row stays, marked failed, so the user sees what happened and the
        # agent can be retried rather than silently not existing.
        logger.exception("Could not provision profile for agent %s", agent_id)
        agent.status = AgentStatus.failed
        agent.status_detail = "The agent could not be set up. Try again shortly."
        session.add(agent)
        return agent

    agent.status = AgentStatus.ready
    agent.status_detail = None
    session.add(agent)
    return agent


def update_agent(
    session: Session, agent: Agent, *, name: str | None, persona: str | None
) -> Agent:
    """Rename or re-persona an agent, rewriting the profile files it affects.

    Credentials are left alone: the profile name never changes, so there is
    nothing to reissue, and reissuing would break a conversation mid-flight.
    """
    if name is not None:
        agent.name = name
    if persona is not None:
        agent.persona = persona or None
    agent.updated_at = datetime.now(UTC)

    try:
        provisioning.write_profile(
            shard_id=agent.shard_id,
            profile_name=agent.profile_name,
            agent_name=agent.name,
            persona=agent.persona,
            api_key=None,
            llm_token=None,
        )
    except OSError:
        logger.exception("Could not rewrite profile for agent %s", agent.id)
        agent.status = AgentStatus.failed
        agent.status_detail = "The agent's settings could not be applied."
    else:
        if agent.status == AgentStatus.failed:
            agent.status = AgentStatus.ready
            agent.status_detail = None
    session.add(agent)
    return agent


def delete_agent(session: Session, agent: Agent) -> None:
    """Revoke first, then remove. A half-done delete must not leave a live key."""
    if agent.api_key_id is not None:
        key = session.get(ApiKey, agent.api_key_id)
        if key is not None and key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            session.add(key)
    agent.llm_token_hash = None
    session.add(agent)
    session.flush()

    provisioning.remove_profile(agent.shard_id, agent.profile_name)
    session.delete(agent)


def agent_for_llm_token(session: Session, token: str) -> Agent | None:
    if not token or not token.startswith(LLM_TOKEN_PREFIX):
        return None
    return session.exec(
        select(Agent).where(Agent.llm_token_hash == hash_llm_token(token))
    ).first()
