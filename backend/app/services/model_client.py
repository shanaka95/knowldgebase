"""Shared HTTP plumbing for the OpenAI-compatible MLX servers.

vMLX starts models on demand: the first request after idle can be refused or
answered with 502/503 for a while, so we retry those (and only those) with
backoff for up to ``MODEL_SERVER_COLD_START_SECONDS``. Read timeouts are never
retried - a multi-minute LLM call must not be doubled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {502, 503, 504, 429}


class ModelServerError(RuntimeError):
    """Non-retryable failure talking to a model server."""


async def post_json_with_cold_start_retry(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    *,
    what: str,
    max_wait: float | None = None,
) -> dict[str, Any]:
    max_wait = (
        settings.MODEL_SERVER_COLD_START_SECONDS if max_wait is None else max_wait
    )
    deadline = time.monotonic() + max_wait
    delay = 1.0
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await client.post(url, json=body)
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ConnectTimeout,
        ) as exc:
            if time.monotonic() + delay > deadline:
                raise ModelServerError(
                    f"{what}: model server unreachable ({exc})"
                ) from exc
            logger.info(
                "%s: server not ready (%s), retrying in %.0fs", what, exc, delay
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
            continue
        if response.status_code in RETRYABLE_STATUS:
            if time.monotonic() + delay > deadline:
                raise ModelServerError(
                    f"{what}: server returned {response.status_code}: {response.text[:200]}"
                )
            logger.info(
                "%s: HTTP %s, retrying in %.0fs", what, response.status_code, delay
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
            continue
        if response.status_code >= 400:
            raise ModelServerError(
                f"{what}: HTTP {response.status_code}: {response.text[:500]}"
            )
        data: dict[str, Any] = response.json()
        return data


def auth_headers(api_key: str | None) -> dict[str, str]:
    """Bearer header for hosted providers; local servers usually need none."""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def make_http_client(
    read_timeout: float, api_key: str | None = None
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0),
        headers=auth_headers(api_key),
    )


async def probe_models_endpoint(
    base_url: str, api_key: str | None = None
) -> tuple[bool, float, str | None]:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=3.0, headers=auth_headers(api_key)
        ) as client:
            r = await client.get(f"{base_url.rstrip('/')}/models")
        ok = r.status_code < 400
        return (
            ok,
            (time.perf_counter() - start) * 1000,
            None if ok else f"HTTP {r.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        return False, (time.perf_counter() - start) * 1000, str(exc)[:200]
