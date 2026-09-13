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
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# Only what the agent actually needs. `terminal`, `file` and `browser` are
# deliberately absent: see the module docstring.
AGENT_TOOLSETS = ["skills", "todo", "vision"]


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

# The knowledge base, reached as this user and only this user.
mcp_servers:
  plusgpt:
    url: {_yaml_quote(mcp_url)}
    headers:
      Authorization: 'Bearer ${{PLUSGPT_API_KEY}}'
    timeout: 120
    connect_timeout: 30

# No shell, no filesystem, no browser: an injected prompt has nothing to drive.
enabled_toolsets: [{", ".join(AGENT_TOOLSETS)}]

skills:
  external_dirs:
    - /opt/plusgpt-skills
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

When they send you a document or a photograph, pass the file to the knowledge
base rather than transcribing it yourself, and say where you filed it. When
they ask for a document back, fetch the original and send it.

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
    # Hermes creates these itself, but making them up front means the first
    # message does not race the directory into existence.
    for child in ("sessions", "memories", "cache", "logs"):
        (directory / child).mkdir(exist_ok=True)

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
        "enabled_toolsets: [todo]",
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
    _atomic_write(home / "config.yaml", render_gateway_config(channels))
    _atomic_write(home / ".env", render_gateway_env(secrets), mode=0o600)
    return home
