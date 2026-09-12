"""Heartbeat file touched by the worker; used by the compose healthcheck."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.core.config import settings


def touch(path: str | None = None) -> None:
    p = Path(path or settings.WORKER_HEARTBEAT_FILE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=True)
        os.utime(p, None)
    except OSError:  # pragma: no cover - best effort only
        pass


def is_fresh(path: str | None = None, max_age_seconds: float = 30.0) -> bool:
    p = Path(path or settings.WORKER_HEARTBEAT_FILE)
    try:
        return time.time() - p.stat().st_mtime < max_age_seconds
    except OSError:
        return False
