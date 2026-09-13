"""Deployment-wide channel setup, for administrators.

A channel becomes available to users only when an admin has both supplied its
credentials and switched it on. Credentials go in encrypted and never come back
out: the API reports which fields are set, never what they are set to, so a
compromised admin session cannot be used to read the platform tokens back.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    ChannelConfig,
    ChannelConfigPublic,
    ChannelConfigsPublic,
    ChannelConfigUpdate,
    ChannelType,
    Message,
    WhatsAppPairingPublic,
    WhatsAppTransport,
)
from app.services import channels as channel_service

router = APIRouter(
    prefix="/admin/channels",
    tags=["admin_channels"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _to_public(
    channel: ChannelType, config: ChannelConfig | None
) -> ChannelConfigPublic:
    present = channel_service.open_credentials(
        config.credentials_encrypted if config else None
    )
    return ChannelConfigPublic(
        channel_type=channel,
        enabled=bool(config and config.enabled),
        transport=config.transport if config else None,
        public_handle=config.public_handle if config else None,
        configured=channel_service.is_configured(config),
        required_fields=channel_service.required_fields_for(config, channel),
        present_fields=sorted(k for k, v in present.items() if v),
        updated_at=config.updated_at if config else None,
    )


@router.get("/", response_model=ChannelConfigsPublic)
def read_channels(session: SessionDep) -> Any:
    """Every channel this build supports, configured or not."""
    rows = {c.channel_type: c for c in session.exec(select(ChannelConfig)).all()}
    return ChannelConfigsPublic(
        data=[_to_public(channel, rows.get(channel)) for channel in ChannelType]
    )


@router.patch("/{channel_type}", response_model=ChannelConfigPublic)
def update_channel(
    session: SessionDep, channel_type: ChannelType, body: ChannelConfigUpdate
) -> Any:
    config = session.exec(
        select(ChannelConfig).where(ChannelConfig.channel_type == channel_type)
    ).first()
    if config is None:
        config = ChannelConfig(channel_type=channel_type)
        session.add(config)

    if body.transport is not None:
        if channel_type != ChannelType.whatsapp:
            raise HTTPException(
                status_code=400, detail="Only WhatsApp has a transport choice"
            )
        config.transport = body.transport
    elif channel_type == ChannelType.whatsapp and config.transport is None:
        config.transport = WhatsAppTransport.cloud_api

    if body.public_handle is not None:
        config.public_handle = body.public_handle.strip() or None

    if body.credentials is not None:
        # Merge, so an admin can correct one field without retyping the rest.
        merged = channel_service.open_credentials(config.credentials_encrypted)
        for key, value in body.credentials.items():
            if value:
                merged[key] = value
            else:
                merged.pop(key, None)
        try:
            config.credentials_encrypted = (
                channel_service.seal_credentials(merged) if merged else None
            )
        except channel_service.CredentialSealError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if body.enabled is not None:
        if body.enabled and not channel_service.is_configured(config):
            missing = [
                field
                for field in channel_service.required_fields_for(config, channel_type)
                if not channel_service.open_credentials(
                    config.credentials_encrypted
                ).get(field)
            ]
            raise HTTPException(
                status_code=400,
                detail=f"Set {', '.join(missing)} before enabling this channel",
            )
        config.enabled = body.enabled

    from datetime import UTC, datetime

    config.updated_at = datetime.now(UTC)
    session.add(config)
    session.commit()
    session.refresh(config)
    # Push the change out to the shards straight away, so enabling a channel in
    # the dashboard is the whole of enabling it.
    channel_service.apply_to_shards(session)
    return _to_public(channel_type, config)


@router.delete("/{channel_type}")
def clear_channel(session: SessionDep, channel_type: ChannelType) -> Message:
    """Forget a channel's credentials and disable it.

    Existing user connections are left alone: an admin re-entering a token
    should not force everybody to reconnect.
    """
    config = session.exec(
        select(ChannelConfig).where(ChannelConfig.channel_type == channel_type)
    ).first()
    if config is None:
        return Message(message="Nothing to clear")
    config.credentials_encrypted = None
    config.enabled = False
    session.add(config)
    session.commit()
    channel_service.apply_to_shards(session)
    return Message(message="Channel credentials cleared")


# ---------------------------------------------------------------------------
# WhatsApp bridge pairing
#
# The bridge signs in like WhatsApp Web: it shows a QR code and somebody scans
# it with a phone. That is why this exists at all - there is no token an
# administrator could paste in instead.
# ---------------------------------------------------------------------------


def _pairing_shard() -> int:
    """Which shard holds the WhatsApp session.

    One WhatsApp account means one bridge, and the bridge belongs to the shard
    that owns the adapter - shard 0, the same one every platform's shared bot
    runs on.
    """
    return 0


@router.get("/whatsapp/pairing", response_model=WhatsAppPairingPublic)
def read_pairing(session: SessionDep) -> Any:
    """How the current pairing attempt is going.

    The QR comes back as an SVG rather than the raw string the bridge emits, so
    the dashboard can show it without shipping a QR encoder of its own.
    """
    from app.services import agent_provisioning

    status = agent_provisioning.pairing_status(_pairing_shard())
    qr = str(status.get("qr") or "")
    return WhatsAppPairingPublic(
        state=str(status.get("state") or "unknown"),
        detail=str(status.get("detail") or "") or None,
        account=str(status.get("account") or "") or None,
        qr_svg=_qr_svg(qr) if qr else None,
        updated_at=status.get("updated_at"),
    )


@router.post("/whatsapp/pairing", response_model=WhatsAppPairingPublic)
def start_pairing(session: SessionDep) -> Any:
    """Ask the shard to show a QR code."""
    from app.services import agent_provisioning

    config = session.exec(
        select(ChannelConfig).where(ChannelConfig.channel_type == ChannelType.whatsapp)
    ).first()
    if config is None or config.transport != WhatsAppTransport.bridge:
        raise HTTPException(
            status_code=400,
            detail="Pairing applies to the local bridge. The Cloud API uses tokens instead.",
        )
    try:
        agent_provisioning.request_pairing(_pairing_shard())
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="The gateway's storage is not reachable, so pairing cannot start.",
        ) from exc
    return read_pairing(session)


@router.delete("/whatsapp/pairing")
def stop_pairing(session: SessionDep, forget: bool = False) -> Message:
    """Cancel the attempt, or sign the account out entirely.

    ``forget`` deletes the session, which is the only way to sign out: the
    bridge has no logout that survives a restart.
    """
    from app.services import agent_provisioning

    if forget:
        agent_provisioning.request_pairing(_pairing_shard(), action="unpair")
        return Message(message="Signing out of WhatsApp")
    agent_provisioning.cancel_pairing(_pairing_shard())
    return Message(message="Pairing cancelled")


def _qr_svg(payload: str) -> str:
    """Render the bridge's QR string as an inline SVG."""
    import io

    import qrcode
    import qrcode.image.svg

    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()
