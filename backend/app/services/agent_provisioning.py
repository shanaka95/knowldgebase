"""Writing the Hermes profile that backs one agent.

A Hermes *profile* is a directory: `config.yaml`, `.env`, `SOUL.md`, and the
conversation store the gateway creates beside them. The gateway discovers
profiles by listing that directory on every inbound message, so provisioning an
agent is a filesystem write - no restart, no API, no coordination.

Three properties of the layout are load-bearing for isolation:

* The knowledge-base key lives in the profile's own `.env`, and `config.yaml`
  refers to it as `${PLUSGPT_API_KEY}`. Hermes resolves that through its
  per-profile secret scope, which fails closed rather than reading the process
  environment, so one agent cannot end up authenticating as another.
* The toolset is cut down to what a knowledge-base assistant needs. No shell,
  no filesystem, no browser - there is nothing for an injected prompt to drive.
* No adapters are configured here. Channels belong to the gateway's default
  profile, which owns the one shared bot per platform; a user's profile only
  ever runs turns.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# The MCP server's name doubles as a toolset name: Hermes registers an alias
# from `plusgpt` to the `mcp-plusgpt` toolset its tools land in. Leaving it out
# of the list below does not merely omit a nicety - it takes the knowledge base
# away from the agent entirely.
MCP_SERVER_NAME = "plusgpt"

# Only what the agent actually needs. `terminal`, `file` and `browser` are
# deliberately absent: see the module docstring.
AGENT_TOOLSETS = [MCP_SERVER_NAME, "skills", "todo", "vision"]

# The file-ingestion tools, and only those. A channel agent can still write a
# page from what somebody types or pastes - that is often the quickest way to
# capture something - but it cannot take a document in. Uploading is the web
# app's job, where the file is in front of the person sending it.
#
# These are excluded at the MCP layer rather than left to the agent's
# judgement: a prompt asking for a file to be uploaded then finds no tool.
WITHHELD_MCP_TOOLS = [
    "upload_document",
    "retry_import",
]

# Hermes reads per-platform toolsets from `platform_toolsets`, and silently
# ignores any key it does not know - so a plausible-looking `enabled_toolsets`
# leaves the platform default in force, which for every messaging platform
# includes terminal, file and browser. The name matters more than it looks.
TOOLSET_CONFIG_KEY = "platform_toolsets"

# The platforms an agent can be reached on. Each needs its own entry; a platform
# with no entry falls back to Hermes' permissive default.
AGENT_PLATFORMS = ("telegram", "whatsapp", "slack", "discord", "cli")

# Named again as a denial, not only omitted from the grant. Toolsets compose -
# a preset gaining a member, a plugin declaring one, an adapter override - and
# any of those would quietly hand a hosted agent code execution or the
# filesystem. Listing them here means the grant and the denial both have to
# change before that can happen.
DENIED_TOOLSETS = [
    "terminal",
    "file",
    "browser",
    "code_execution",
    "coding",
    "computer_use",
    "debugging",
    "delegation",
]


def profile_name_for(agent_id: uuid.UUID) -> str:
    """Stable directory name. Derived from the id, so renaming never moves state."""
    return f"a-{agent_id.hex[:16]}"


def shard_for(agent_id: uuid.UUID) -> int:
    """Spread agents over the shards evenly and deterministically."""
    count = max(1, settings.HERMES_SHARD_COUNT)
    return int(agent_id.int % count)


def shard_root(shard_id: int) -> Path:
    """Where one shard's profiles live on the shared volume."""
    root = Path(settings.HERMES_PROFILES_ROOT)
    return root / f"shard-{shard_id}" / "profiles"


def profile_dir(shard_id: int, profile_name: str) -> Path:
    return shard_root(shard_id) / profile_name


def _yaml_quote(value: str) -> str:
    """Single-quoted YAML scalar. Doubling an apostrophe is the whole escape."""
    return "'" + str(value).replace("'", "''") + "'"


def _toolset_block_for(granted: list[str]) -> str:
    """Per-platform toolsets, which is the only form Hermes reads."""
    lines = [f"{TOOLSET_CONFIG_KEY}:"]
    joined = ", ".join(granted)
    lines += [f"  {platform}: [{joined}]" for platform in AGENT_PLATFORMS]
    return "\n".join(lines)


def _toolset_block() -> str:
    return _toolset_block_for(AGENT_TOOLSETS)


def render_config_yaml(*, model: str, mcp_url: str) -> str:
    """The profile's `config.yaml`.

    `${PLUSGPT_API_KEY}` is interpolated by Hermes from this profile's `.env`
    through its secret scope - the value is never written into this file.
    """
    return f"""# Managed by PlusGPT. Changes here are overwritten when the agent is updated.
model:
  provider: custom
  base_url: {_yaml_quote(settings.AGENT_LLM_PROXY_URL)}
  default: {_yaml_quote(model)}
  api_key: '${{PLUSGPT_LLM_TOKEN}}'

# The knowledge base, reached as this user and only this user, and read-only.
# A channel agent answers questions; it does not write. Excluding the writing
# tools here rather than trusting the agent not to call them means a prompt
# that asks for a page to be created finds no tool to create one.
mcp_servers:
  plusgpt:
    url: {_yaml_quote(mcp_url)}
    headers:
      Authorization: 'Bearer ${{PLUSGPT_API_KEY}}'
    timeout: 120
    connect_timeout: 30
    tools:
      exclude: [{", ".join(WITHHELD_MCP_TOOLS)}]

# No shell, no filesystem, no browser: an injected prompt has nothing to drive.
# `{MCP_SERVER_NAME}` is the knowledge base itself - omitting it would leave the
# agent with nothing to look anything up in.
{_toolset_block()}

# Attachments are refused before a turn starts. A channel agent reads the
# knowledge base and nothing else, so a file sent here has nowhere to go; saying
# so immediately beats a model discovering mid-turn that it has no way to file
# it, which is what the person actually experienced.
gateway:
  refuse_attachments: true

skills:
  external_dirs:
    - /opt/plusgpt-skills

# Nobody here can run /sethome, and cron delivery is not something a user of a
# hosted assistant configures, so the onboarding prompts are noise on a first
# message - which is the worst possible moment for them.
onboarding:
  home_channel_prompt: false
  # Quoted: YAML reads a bare `off` as boolean false, and Hermes checks for
  # the string, so an unquoted value would silently leave the offer switched on.
  profile_build: "off"

# A chat window is not a terminal. Nobody wants to watch their assistant narrate
# which tool it is calling; they want the answer. Quoted for the same reason as
# above - a bare `off` is boolean false, and this setting is compared as a string.
display:
  tool_progress: "off"
  interim_assistant_messages: false

# No plugins. `plusgpt-files` still ships in the image and could be enabled
# here, but filing from a chat is switched off: attachments are refused at the
# gateway before a turn starts, so a tool for uploading them would have nothing
# to act on.
plugins:
  enabled: []

agent:
  disabled_toolsets: [{", ".join(DENIED_TOOLSETS)}]
"""


def render_env(*, api_key: str, llm_token: str) -> str:
    return (
        "# Managed by PlusGPT. This file is the agent's entire credential set.\n"
        f"PLUSGPT_API_KEY={api_key}\n"
        f"PLUSGPT_LLM_TOKEN={llm_token}\n"
    )


def render_soul(*, agent_name: str, persona: str | None) -> str:
    """The agent's identity, prepended to its system prompt.

    Deliberately short. The detail of *how* to use the knowledge base lives in
    the `plusgpt` skill, which is versioned with the MCP server and tested
    against it; duplicating it here would let the two drift apart.
    """
    body = f"""# {agent_name}

You are {agent_name}, a personal assistant reached over a messaging app.

PlusGPT is your knowledge base. It holds what matters about the person you are
talking to - their documents, contracts, bills, letters and notes. Look things
up there before asking them to repeat something they have already told you, and
file anything worth keeping.

You are talking to one person, in a chat window. Keep replies short enough to
read on a phone. Lead with the answer; add detail only if it was asked for.

You can write pages from what they tell you. If they dictate a note, paste some
text, or ask you to keep something, make a page for it and say where you put it.

You cannot take files. If someone sends a document or a photograph, say plainly
that files are added in PlusGPT on the web, and offer the alternative: if they
paste the text, you will make a page from it now. Do not offer to transcribe an
attachment yourself, and do not promise to file it later.

When they ask for a document itself, fetch the original and send it.

If the knowledge base has nothing on a topic, say so plainly rather than
filling the gap from memory. Being wrong about someone's own paperwork is worse
than being unhelpful.
"""
    if persona and persona.strip():
        body += f"\n## How they want you to work\n\n{persona.strip()}\n"
    return body


def write_profile(
    *,
    shard_id: int,
    profile_name: str,
    agent_name: str,
    persona: str | None,
    api_key: str | None,
    llm_token: str | None,
    model: str | None = None,
    mcp_url: str | None = None,
) -> Path:
    """Create or update a profile directory.

    Credentials are optional so a rename can rewrite the persona without
    reissuing keys: passing ``None`` leaves the existing `.env` alone.
    """
    directory = profile_dir(shard_id, profile_name)
    directory.mkdir(parents=True, exist_ok=True)
    _own(directory)
    _own(directory.parent)
    # Hermes creates these itself, but making them up front means the first
    # message does not race the directory into existence.
    for child in ("sessions", "memories", "cache", "logs"):
        child_dir = directory / child
        child_dir.mkdir(exist_ok=True)
        _own(child_dir)

    _atomic_write(
        directory / "config.yaml",
        render_config_yaml(
            model=model or settings.AGENT_LLM_MODEL,
            mcp_url=mcp_url or settings.HERMES_MCP_URL,
        ),
    )
    _atomic_write(
        directory / "SOUL.md", render_soul(agent_name=agent_name, persona=persona)
    )
    if api_key is not None and llm_token is not None:
        _atomic_write(
            directory / ".env",
            render_env(api_key=api_key, llm_token=llm_token),
            mode=0o600,
        )
    return directory


def _own(path: Path) -> None:
    """Hand a path to the uid the gateway runs as.

    The backend writes these files as root; the gateway reads them as an
    unprivileged user in another container. Without this it cannot read a 0600
    `.env`, and cannot write its own conversation store into the directories at
    all. Best effort: a platform or filesystem that refuses chown should not
    stop an agent being created, and the failure shows up as the gateway
    reporting what it could not open.
    """
    if settings.HERMES_PROFILE_UID < 0:
        return
    try:
        os.chown(path, settings.HERMES_PROFILE_UID, settings.HERMES_PROFILE_GID)
    except (OSError, AttributeError) as exc:
        logger.debug("Could not chown %s: %s", path, exc)


def _atomic_write(path: Path, content: str, *, mode: int = 0o644) -> None:
    """Replace a file in one step.

    The gateway reads these directories continuously, so a half-written
    `config.yaml` would be read as a broken one.
    """
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(content)
        os.chmod(tmp_name, mode)
        _own(Path(tmp_name))
        os.replace(tmp_name, path)
    except Exception:
        # Cleanup must never mask the write error that brought us here.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def remove_profile(shard_id: int, profile_name: str) -> None:
    """Delete a profile directory and everything in it.

    Best effort by design: the credentials inside it are revoked before this
    runs, so a directory left behind is inert, and refusing to delete the agent
    because a volume was briefly unavailable would be worse.
    """
    directory = profile_dir(shard_id, profile_name)
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Could not remove profile %s: %s", directory, exc)


# ---------------------------------------------------------------------------
# The shard itself
#
# A shard's own Hermes home is the "default profile". It owns the one shared bot
# per platform and nothing else: no knowledge base, no user data, no tools. Its
# only job is to accept messages and hand each one to the profile the control
# plane names.
# ---------------------------------------------------------------------------


def shard_home(shard_id: int) -> Path:
    return Path(settings.HERMES_PROFILES_ROOT) / f"shard-{shard_id}"


def render_gateway_config(channels: dict[str, dict[str, object]]) -> str:
    """The default profile's `config.yaml`.

    ``profile_route_provider`` is what makes this multi-tenant: instead of a
    static routing table, every inbound sender is resolved against PlusGPT, and
    an unrecognised one is dropped rather than falling through to this profile.
    """
    lines = [
        "# Managed by PlusGPT. Edited through the admin Channels page.",
        "gateway:",
        "  multiplex_profiles: true",
        f"  profile_route_provider: {_yaml_quote(settings.AGENT_CONTROL_ROUTE_URL)}",
        "  profile_route_provider_token: '${AGENT_CONTROL_TOKEN}'",
        "",
        "platforms:",
    ]
    if not channels:
        lines.append("  {}")
    for name, options in sorted(channels.items()):
        lines.append(f"  {name}:")
        lines.append("    enabled: true")
        for key, value in sorted(options.items()):
            if isinstance(value, bool):
                lines.append(f"    {key}: {'true' if value else 'false'}")
            else:
                lines.append(f"    {key}: {_yaml_quote(str(value))}")
    lines += [
        "",
        "# This profile answers nobody directly - every real turn runs in a user's",
        "# profile - so it needs no tools of its own.",
        _toolset_block_for(["todo"]),
        "",
    ]
    return "\n".join(lines)


def render_gateway_env(secrets: dict[str, str]) -> str:
    lines = [
        "# Managed by PlusGPT. Platform credentials for this shard's shared bots.",
        f"AGENT_CONTROL_TOKEN={settings.AGENT_CONTROL_TOKEN}",
        # Hermes' own allowlist would otherwise refuse every stranger before
        # routing ever runs. Authorisation lives in the control plane instead,
        # which resolves an unlinked sender to nobody and drops the message -
        # and which runs first, at ingress, on every inbound event.
        "GATEWAY_ALLOW_ALL_USERS=true",
    ]
    lines += [f"{key}={value}" for key, value in sorted(secrets.items())]
    return "\n".join(lines) + "\n"


def write_gateway(
    shard_id: int, *, channels: dict[str, dict[str, object]], secrets: dict[str, str]
) -> Path:
    home = shard_home(shard_id)
    (home / "profiles").mkdir(parents=True, exist_ok=True)
    _own(home)
    _own(home / "profiles")
    _atomic_write(home / "config.yaml", render_gateway_config(channels))
    _atomic_write(home / ".env", render_gateway_env(secrets), mode=0o600)
    return home


# ---------------------------------------------------------------------------
# WhatsApp pairing
#
# The local bridge signs in the way WhatsApp Web does: it shows a QR code and
# somebody scans it. That has to happen on the shard, where the bridge and its
# session directory live, so the backend asks for it through the volume the two
# already share and reads the answer back the same way. No new port, nothing
# else to authenticate.
# ---------------------------------------------------------------------------


def pairing_dir(shard_id: int) -> Path:
    return shard_home(shard_id) / "pairing"


def request_pairing(shard_id: int, *, action: str = "pair") -> None:
    """Ask the shard to start pairing, or to forget the paired account."""
    directory = pairing_dir(shard_id)
    directory.mkdir(parents=True, exist_ok=True)
    _own(directory)
    _atomic_write(
        directory / "request.json",
        json.dumps({"action": action, "requested_at": time.time()}),
    )


def cancel_pairing(shard_id: int) -> None:
    """Withdraw the request. The shard notices and stops the bridge."""
    try:
        (pairing_dir(shard_id) / "request.json").unlink()
    except OSError:
        pass


def pairing_status(shard_id: int) -> dict[str, object]:
    """What the shard last reported.

    A missing file means the shard has not started, which is a real answer: the
    administrator needs to know that rather than watch a spinner.
    """
    path = pairing_dir(shard_id) / "status.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {
            "state": "unavailable",
            "detail": "The gateway has not started yet, so pairing cannot begin.",
        }
    except (OSError, ValueError):
        return {"state": "unknown", "detail": "The gateway's status could not be read."}
    return data if isinstance(data, dict) else {"state": "unknown"}


def signal_revocation(shard_id: int) -> None:
    """Tell a shard that some access has been withdrawn.

    The gateway caches route answers so it does not call us on every message,
    which means a disconnected channel would otherwise keep working until the
    entry expired. Touching one file per shard is enough: the gateway clears
    the whole cache and re-asks, and the cost is a stat per message rather than
    a list we would have to keep in sync.
    """
    path = shard_home(shard_id) / "routes-revoked-at"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()))
        _own(path)
    except OSError as exc:
        logger.warning("Could not signal revocation to shard %s: %s", shard_id, exc)


def signal_revocation_everywhere() -> None:
    for shard_id in range(max(1, settings.HERMES_SHARD_COUNT)):
        signal_revocation(shard_id)


def queue_channel_message(
    shard_id: int, *, platform: str, chat_id: str, text: str
) -> None:
    """Ask a shard to deliver a notice to a channel.

    There is no inbound message to answer - somebody is being told their account
    was disconnected, which by definition happens from the dashboard - so this
    cannot ride back on a turn. The shard drains the directory with
    ``hermes send``, which reuses the gateway's own platform credentials.
    """
    directory = shard_home(shard_id) / "outbox"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _own(directory)
        path = directory / f"{uuid.uuid4().hex}.json"
        _atomic_write(
            path,
            json.dumps(
                {"platform": platform, "chat_id": chat_id, "text": text, "attempts": 0}
            ),
        )
    except OSError as exc:
        # Best effort: failing to say goodbye must not stop the disconnect. The
        # binding is what actually withdraws access.
        logger.warning("Could not queue a notice for shard %s: %s", shard_id, exc)
