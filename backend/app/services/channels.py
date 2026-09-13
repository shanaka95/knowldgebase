"""Channel configuration, and the handshake that binds a channel to an account.

Everyone talks to the same bot. A WhatsApp message carries a phone number, and
a phone number is a claim, not a credential - anyone can put any number in front
of us, and anyone can message our number. So an inbound identity is worth
nothing until its owner has proved they also hold the PlusGPT account.

The proof is a one-time code: the dashboard issues it to a signed-in user, and
the user sends it from the channel. Holding it means holding both sides. It is
stored hashed and single-use, and it expires quickly, because the plaintext
travels through a messaging app and may sit in a chat log forever.

A sender who is not linked is never answered. Replying would tell a stranger
that the number is live, invite abuse of a metered API, and - if the reply were
generated - hand an unauthenticated party a language model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.models import (
    ChannelConfig,
    ChannelConnection,
    ChannelLinkCode,
    ChannelType,
    WhatsAppTransport,
)

logger = logging.getLogger(__name__)

# Codes are read off one screen and typed into another, so the alphabet excludes
# characters people confuse: no O/0, no I/1/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_GROUPS = 2
_CODE_GROUP_LEN = 4
CODE_PREFIX = "LINK-"

# The only two the bridge understands (scripts/whatsapp-bridge/bridge.js).
WHATSAPP_BRIDGE_MODES = ("bot", "self-chat")
# One account fronting many people is a bot, not somebody talking to themself.
WHATSAPP_BRIDGE_MODE = "bot"


@dataclass(frozen=True)
class ChannelSpec:
    """What a channel needs from an administrator before users can pick it."""

    channel_type: ChannelType
    label: str
    required_fields: tuple[str, ...]
    # Per-transport requirements, where a channel has more than one backend.
    transport_fields: dict[str, tuple[str, ...]] | None = None


CHANNEL_SPECS: dict[ChannelType, ChannelSpec] = {
    ChannelType.whatsapp: ChannelSpec(
        ChannelType.whatsapp,
        "WhatsApp",
        required_fields=(),
        transport_fields={
            # Meta's official Business API.
            WhatsAppTransport.cloud_api: (
                "access_token",
                "phone_number_id",
                "verify_token",
            ),
            # The WhatsApp Web bridge pairs by QR code at runtime, so there is
            # nothing to type in beforehand.
            WhatsAppTransport.bridge: (),
        },
    ),
    ChannelType.telegram: ChannelSpec(
        ChannelType.telegram, "Telegram", required_fields=("bot_token",)
    ),
    ChannelType.slack: ChannelSpec(
        ChannelType.slack,
        "Slack",
        required_fields=("bot_token", "app_token", "signing_secret"),
    ),
    ChannelType.discord: ChannelSpec(
        ChannelType.discord, "Discord", required_fields=("bot_token",)
    ),
}


def required_fields_for(config: ChannelConfig | None, channel: ChannelType) -> list[str]:
    spec = CHANNEL_SPECS[channel]
    if spec.transport_fields is None:
        return list(spec.required_fields)
    transport = (config.transport if config else None) or WhatsAppTransport.cloud_api
    return list(spec.transport_fields.get(transport, ()))


# ---------------------------------------------------------------------------
# Credentials at rest
# ---------------------------------------------------------------------------


class CredentialSealError(RuntimeError):
    """Raised when credentials cannot be encrypted or decrypted."""


def _fernet():
    from cryptography.fernet import Fernet

    key = (settings.CHANNEL_SECRET_KEY or "").strip()
    if not key:
        raise CredentialSealError(
            "CHANNEL_SECRET_KEY is not set, so channel credentials cannot be "
            "stored. Generate one with Fernet.generate_key()."
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001 - any malformed key is the same problem
        raise CredentialSealError("CHANNEL_SECRET_KEY is not a valid Fernet key") from exc


def seal_credentials(values: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def open_credentials(sealed: str | None) -> dict[str, str]:
    """Decrypt stored credentials. An unreadable blob yields nothing, not a crash.

    A rotated or mistyped key must not take the whole admin page down; the
    channel simply reads as unconfigured until someone re-enters it.
    """
    if not sealed:
        return {}
    try:
        raw = _fernet().decrypt(sealed.encode())
    except Exception:  # noqa: BLE001 - InvalidToken, bad key, corrupt column
        logger.warning("Stored channel credentials could not be decrypted")
        return {}
    try:
        data = json.loads(raw.decode())
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def is_configured(config: ChannelConfig | None) -> bool:
    if config is None:
        return False
    required = required_fields_for(config, config.channel_type)
    if not required:
        # Nothing to enter - the bridge pairs interactively - so being enabled
        # is the whole of being configured.
        return True
    present = open_credentials(config.credentials_encrypted)
    return all(present.get(field) for field in required)


def enabled_channels(session: Session) -> list[ChannelConfig]:
    """Channels an administrator has both configured and switched on."""
    rows = session.exec(select(ChannelConfig).where(col(ChannelConfig.enabled))).all()
    return [row for row in rows if is_configured(row)]


# ---------------------------------------------------------------------------
# Link codes
# ---------------------------------------------------------------------------


def hash_code(code: str) -> str:
    return hashlib.sha256(normalise_code(code).encode()).hexdigest()


def normalise_code(code: str) -> str:
    """Accept what a person might actually send: spacing, case, a stray prefix."""
    cleaned = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    if cleaned.startswith("LINK"):
        cleaned = cleaned[4:]
    return cleaned


def generate_code() -> str:
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LEN))
        for _ in range(_CODE_GROUPS)
    ]
    return CODE_PREFIX + "-".join(groups)


class LinkCodeLimit(RuntimeError):
    """Too many codes outstanding for one agent."""


def issue_code(
    session: Session, *, agent_id, channel: ChannelType
) -> tuple[str, ChannelLinkCode]:
    """Mint a code for this agent and channel. Returns the plaintext once."""
    now = datetime.now(UTC)
    outstanding = session.exec(
        select(func.count())
        .select_from(ChannelLinkCode)
        .where(
            ChannelLinkCode.agent_id == agent_id,
            col(ChannelLinkCode.used_at).is_(None),
            col(ChannelLinkCode.expires_at) > now,
        )
    ).one()
    if int(outstanding) >= settings.CHANNEL_LINK_CODE_MAX_ACTIVE:
        raise LinkCodeLimit(
            "Too many unused codes for this agent. Use one, or wait for them to expire."
        )

    plain = generate_code()
    row = ChannelLinkCode(
        agent_id=agent_id,
        channel_type=channel,
        code_hash=hash_code(plain),
        expires_at=now + timedelta(minutes=settings.CHANNEL_LINK_CODE_TTL_MINUTES),
    )
    session.add(row)
    session.flush()
    return plain, row


def find_code_in(text: str) -> str | None:
    """The first thing in a message that looks like a link code.

    People send "LINK-7QK2-9F31", "link-7qk2-9f31", or paste it into a sentence.
    Anything that normalises to the right length and alphabet is worth checking
    against the database, which is the only place it can actually be validated.
    """
    if not text:
        return None
    want = _CODE_GROUPS * _CODE_GROUP_LEN
    for raw in text.replace("\n", " ").split():
        candidate = normalise_code(raw)
        if len(candidate) == want and all(ch in _CODE_ALPHABET for ch in candidate):
            return candidate
    return None


@dataclass(frozen=True)
class RedeemResult:
    connection: ChannelConnection | None
    reason: str | None = None


def redeem_code(
    session: Session,
    *,
    code: str,
    channel: ChannelType,
    platform_identity: str,
    display_name: str | None = None,
) -> RedeemResult:
    """Bind a platform identity to the agent that issued ``code``.

    Every failure returns the same shape and says nothing to the sender: the
    caller drops the message either way, so a wrong guess is not distinguishable
    from an expired code by anyone probing the bot.
    """
    now = datetime.now(UTC)
    row = session.exec(
        select(ChannelLinkCode).where(ChannelLinkCode.code_hash == hash_code(code))
    ).first()
    if row is None:
        return RedeemResult(None, "unknown code")
    if row.used_at is not None:
        return RedeemResult(None, "code already used")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return RedeemResult(None, "code expired")
    if row.channel_type != channel:
        # A code minted for Telegram must not link a WhatsApp number: the user
        # chose which channel they were connecting, and that choice is part of
        # what they authorised.
        return RedeemResult(None, "code was issued for a different channel")

    existing = session.exec(
        select(ChannelConnection).where(
            ChannelConnection.channel_type == channel,
            ChannelConnection.platform_identity == platform_identity,
        )
    ).first()
    if existing is not None:
        if existing.agent_id == row.agent_id:
            # Re-sending a code from an already-connected account is harmless.
            row.used_at = now
            session.add(row)
            return RedeemResult(existing)
        logger.warning(
            "Refusing to relink %s identity already bound to another agent", channel
        )
        return RedeemResult(None, "identity already connected elsewhere")

    connection = ChannelConnection(
        agent_id=row.agent_id,
        channel_type=channel,
        platform_identity=platform_identity,
        display_name=display_name,
        last_seen_at=now,
    )
    row.used_at = now
    session.add(row)
    session.add(connection)
    session.flush()
    return RedeemResult(connection)


def find_connection(
    session: Session, *, channel: ChannelType, platform_identity: str
) -> ChannelConnection | None:
    return session.exec(
        select(ChannelConnection).where(
            ChannelConnection.channel_type == channel,
            ChannelConnection.platform_identity == platform_identity,
        )
    ).first()


# ---------------------------------------------------------------------------
# Pushing the admin's choices out to the shards
# ---------------------------------------------------------------------------


def gateway_plan(session: Session) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """``(platforms, secrets)`` for a shard's default profile.

    Only channels an admin has configured *and* enabled make it out. A half-set
    channel is left off entirely rather than started and left to fail, which
    would leave people staring at a bot that never answers.
    """
    platforms: dict[str, dict[str, object]] = {}
    secrets: dict[str, str] = {}

    for config in enabled_channels(session):
        creds = open_credentials(config.credentials_encrypted)
        channel = config.channel_type

        if channel == ChannelType.telegram:
            platforms["telegram"] = {}
            secrets["TELEGRAM_BOT_TOKEN"] = creds.get("bot_token", "")
            # Anyone may message the shared bot; whether they are anyone *we
            # know* is decided by the control plane, before a turn can start.
            secrets["TELEGRAM_ALLOW_ALL_USERS"] = "true"

        elif channel == ChannelType.discord:
            platforms["discord"] = {}
            secrets["DISCORD_BOT_TOKEN"] = creds.get("bot_token", "")
            secrets["DISCORD_ALLOW_ALL_USERS"] = "true"

        elif channel == ChannelType.slack:
            platforms["slack"] = {}
            secrets["SLACK_BOT_TOKEN"] = creds.get("bot_token", "")
            secrets["SLACK_APP_TOKEN"] = creds.get("app_token", "")
            secrets["SLACK_SIGNING_SECRET"] = creds.get("signing_secret", "")
            secrets["SLACK_ALLOW_ALL_USERS"] = "true"

        elif channel == ChannelType.whatsapp:
            platforms["whatsapp"] = {}
            secrets["WHATSAPP_ALLOW_ALL_USERS"] = "true"
            # DMs are open at the transport; the control plane is the real gate.
            secrets["WHATSAPP_DM_POLICY"] = "open"
            # The bridge treats an empty allowlist as "nobody", deliberately, and
            # drops unknown senders before the gateway ever sees them - silently,
            # which is the whole difficulty in diagnosing it. A shared number has
            # to take messages from people it has never heard of; whether any of
            # them get an agent is decided by the control plane, not here.
            secrets["WHATSAPP_ALLOWED_USERS"] = "*"
            if config.transport == WhatsAppTransport.cloud_api:
                secrets["WHATSAPP_CLOUD_ACCESS_TOKEN"] = creds.get("access_token", "")
                secrets["WHATSAPP_CLOUD_PHONE_NUMBER_ID"] = creds.get(
                    "phone_number_id", ""
                )
                secrets["WHATSAPP_CLOUD_VERIFY_TOKEN"] = creds.get("verify_token", "")
            else:
                # The bridge logs in by QR at runtime, so there is nothing to
                # inject here beyond telling it who to listen to.
                #
                # "bot" and "self-chat" are the only modes the bridge knows, and
                # it does not validate: an unrecognised value falls through every
                # message-handling branch and drops inbound messages in silence.
                # A shared account serving many people is "bot".
                secrets["WHATSAPP_MODE"] = WHATSAPP_BRIDGE_MODE

    return platforms, {k: v for k, v in secrets.items() if v}


def apply_to_shards(session: Session) -> list[str]:
    """Rewrite every shard's gateway config from the current channel settings.

    Returns the paths written, for the admin page to report. Errors are
    collected rather than raised: one unreachable volume must not stop the
    others from being updated.
    """
    from app.services import agent_provisioning

    platforms, secrets = gateway_plan(session)
    written: list[str] = []
    for shard_id in range(max(1, settings.HERMES_SHARD_COUNT)):
        try:
            home = agent_provisioning.write_gateway(
                shard_id, channels=platforms, secrets=secrets
            )
        except OSError as exc:
            logger.warning("Could not write gateway config for shard %s: %s", shard_id, exc)
            continue
        written.append(str(home))
    return written
