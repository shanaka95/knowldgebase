"""Agents a user owns, and the channels they can be reached on."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep, SessionUser
from app.models import (
    Agent,
    AgentCreate,
    AgentPublic,
    AgentsPublic,
    AgentUpdate,
    AvailableChannel,
    AvailableChannelsPublic,
    ChannelConnection,
    ChannelLinkCodeCreate,
    ChannelLinkCodePublic,
    ChannelType,
    Message,
)
from app.services import agents as agent_service
from app.services import channels as channel_service

router = APIRouter(prefix="/agents", tags=["agents"])

# How a person actually completes the handshake, per platform. Written here
# rather than in the frontend so the copy stays next to the mechanism.
_INSTRUCTIONS = {
    ChannelType.whatsapp: "Send this code as a WhatsApp message to {handle}.",
    ChannelType.telegram: "Send this code to {handle} on Telegram.",
    ChannelType.slack: "Send this code to {handle} as a direct message in Slack.",
    ChannelType.discord: "Send this code to {handle} as a direct message on Discord.",
}


def _own_agent(session: SessionDep, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None or agent.user_id != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/", response_model=AgentsPublic)
def read_agents(session: SessionDep, current_user: SessionUser) -> Any:
    rows = session.exec(
        select(Agent)
        .where(Agent.user_id == current_user.id)
        .order_by(col(Agent.created_at).asc())
    ).all()
    data = [
        agent_service.to_public(a, agent_service.connections_for(session, a.id))
        for a in rows
    ]
    return AgentsPublic(data=data, count=len(data))


@router.post("/", response_model=AgentPublic)
def create_agent(
    session: SessionDep, current_user: SessionUser, agent_in: AgentCreate
) -> Any:
    existing = session.exec(
        select(Agent).where(
            Agent.user_id == current_user.id, Agent.name == agent_in.name
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="You already have an agent with that name"
        )
    agent = agent_service.create_agent(
        session, user_id=current_user.id, name=agent_in.name, persona=agent_in.persona
    )
    session.commit()
    session.refresh(agent)
    return agent_service.to_public(agent, [])


@router.get("/{agent_id}", response_model=AgentPublic)
def read_agent(
    session: SessionDep, current_user: SessionUser, agent_id: uuid.UUID
) -> Any:
    agent = _own_agent(session, current_user.id, agent_id)
    return agent_service.to_public(
        agent, agent_service.connections_for(session, agent.id)
    )


@router.patch("/{agent_id}", response_model=AgentPublic)
def update_agent(
    session: SessionDep,
    current_user: SessionUser,
    agent_id: uuid.UUID,
    agent_in: AgentUpdate,
) -> Any:
    agent = _own_agent(session, current_user.id, agent_id)
    if agent_in.name and agent_in.name != agent.name:
        clash = session.exec(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.name == agent_in.name,
                Agent.id != agent.id,
            )
        ).first()
        if clash is not None:
            raise HTTPException(
                status_code=409, detail="You already have an agent with that name"
            )
    agent_service.update_agent(
        session, agent, name=agent_in.name, persona=agent_in.persona
    )
    session.commit()
    session.refresh(agent)
    return agent_service.to_public(
        agent, agent_service.connections_for(session, agent.id)
    )


@router.delete("/{agent_id}")
def delete_agent(
    session: SessionDep, current_user: SessionUser, agent_id: uuid.UUID
) -> Message:
    agent = _own_agent(session, current_user.id, agent_id)
    agent_service.delete_agent(session, agent)
    session.commit()
    return Message(message="Agent deleted")


@router.get("/{agent_id}/channels", response_model=AvailableChannelsPublic)
def read_agent_channels(
    session: SessionDep, current_user: SessionUser, agent_id: uuid.UUID
) -> Any:
    """Channels this agent can use: the ones an admin has enabled, plus status."""
    agent = _own_agent(session, current_user.id, agent_id)
    connected = {
        c.channel_type for c in agent_service.connections_for(session, agent.id)
    }
    data = [
        AvailableChannel(
            channel_type=config.channel_type,
            public_handle=config.public_handle,
            connected=config.channel_type in connected,
        )
        for config in channel_service.enabled_channels(session)
    ]
    return AvailableChannelsPublic(data=data)


@router.post("/{agent_id}/channels/link-code", response_model=ChannelLinkCodePublic)
def create_link_code(
    session: SessionDep,
    current_user: SessionUser,
    agent_id: uuid.UUID,
    body: ChannelLinkCodeCreate,
) -> Any:
    """Issue a one-time code proving this account owns a channel identity.

    The plaintext is returned once. Sending it from the channel is what binds
    the two together; until then the channel account is a stranger to us.
    """
    agent = _own_agent(session, current_user.id, agent_id)

    configs = {c.channel_type: c for c in channel_service.enabled_channels(session)}
    config = configs.get(body.channel_type)
    if config is None:
        raise HTTPException(
            status_code=400, detail="That channel is not available on this deployment"
        )

    already = session.exec(
        select(ChannelConnection).where(
            ChannelConnection.agent_id == agent.id,
            ChannelConnection.channel_type == body.channel_type,
        )
    ).first()
    if already is not None:
        raise HTTPException(
            status_code=409,
            detail="That channel is already connected to this agent",
        )

    try:
        plain, row = channel_service.issue_code(
            session, agent_id=agent.id, channel=body.channel_type
        )
    except channel_service.LinkCodeLimit as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    session.commit()

    handle = config.public_handle or "our bot"
    deep_link = None
    if body.channel_type == ChannelType.whatsapp and config.public_handle:
        number = "".join(ch for ch in config.public_handle if ch.isdigit())
        if number:
            deep_link = f"https://wa.me/{number}?text={plain}"
    elif body.channel_type == ChannelType.telegram and config.public_handle:
        deep_link = f"https://t.me/{config.public_handle.lstrip('@')}?text={plain}"

    return ChannelLinkCodePublic(
        code=plain,
        channel_type=body.channel_type,
        expires_at=row.expires_at,
        deep_link=deep_link,
        instructions=_INSTRUCTIONS[body.channel_type].format(handle=handle),
    )


@router.delete("/{agent_id}/channels/{connection_id}")
def delete_connection(
    session: SessionDep,
    current_user: SessionUser,
    agent_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> Message:
    agent = _own_agent(session, current_user.id, agent_id)
    connection = session.get(ChannelConnection, connection_id)
    if connection is None or connection.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    session.delete(connection)
    session.commit()
    return Message(message="Channel disconnected")
