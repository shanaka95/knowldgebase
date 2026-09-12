"""Loads ``models.toml`` - the one place that says where the AI models live.

Precedence is file < environment, so a checked-in ``models.toml`` describes the
deployment and Compose only has to override the two values that differ inside
containers (``host.docker.internal`` instead of ``127.0.0.1``).

Every role speaks the OpenAI-compatible HTTP API, so switching from a local vMLX
server to a hosted provider is a base URL and an API key.
"""

from __future__ import annotations

import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "../models.toml"
ROLES = ("llm", "embeddings", "parser")


def _config_path() -> Path:
    return Path(os.environ.get("MODELS_CONFIG_FILE", DEFAULT_CONFIG_PATH))


@lru_cache(maxsize=1)
def load_models_config() -> dict[str, dict[str, Any]]:
    """Return ``{role: settings}`` with ``[defaults]`` merged into each role.

    A missing file is not an error: every value also has a built-in default and
    can be supplied by an environment variable.
    """
    path = _config_path()
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        logger.info("No models config at %s; using env vars and defaults", path)
        return {role: {} for role in ROLES}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Ignoring unreadable models config %s: %s", path, exc)
        return {role: {} for role in ROLES}

    defaults = dict(raw.get("defaults") or {})
    merged: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        section = dict(raw.get(role) or {})
        # An explicitly empty base_url means "inherit the default gateway".
        if not section.get("base_url"):
            section.pop("base_url", None)
        role_config = {**defaults, **section}
        if "base_url" in role_config:
            role_config["base_url"] = _localize(str(role_config["base_url"]))
        merged[role] = role_config
    return merged


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _localize(base_url: str) -> str:
    """Make one config file work both inside and outside Docker.

    ``host.docker.internal`` is how a container reaches a model server running on
    the host, but that name does not resolve on the host itself - so when the
    process is not containerised it becomes ``127.0.0.1``.
    """
    if not _in_container() and "host.docker.internal" in base_url:
        return base_url.replace("host.docker.internal", "127.0.0.1")
    return base_url


def model_setting(role: str, key: str, fallback: Any = None) -> Any:
    """One value for a role, falling back to the built-in default."""
    return load_models_config().get(role, {}).get(key, fallback)
