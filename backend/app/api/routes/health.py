import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from anyio import to_thread
from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.api.deps import OptionalAuth
from app.core.config import settings
from app.core.db import engine
from app.models import HealthReport, ServiceHealth, WorkerHeartbeat
from app.services.model_client import probe_models_endpoint

router = APIRouter(prefix="/health", tags=["health"])

PROBE_TIMEOUT = 3.0
CACHE_TTL = 5.0

ProbeResult = tuple[bool, float | None, str | None]


def _probe_db() -> ProbeResult:
    start = time.perf_counter()
    try:
        with Session(engine) as session:
            session.connection().execute(text("SELECT 1"))
        return True, (time.perf_counter() - start) * 1000, None
    except Exception as exc:  # noqa: BLE001
        return False, (time.perf_counter() - start) * 1000, str(exc)[:200]


def _probe_worker() -> ProbeResult:
    start = time.perf_counter()
    try:
        with Session(engine) as session:
            latest = session.exec(
                select(WorkerHeartbeat).order_by(
                    col(WorkerHeartbeat.heartbeat_at).desc()
                )
            ).first()
        latency = (time.perf_counter() - start) * 1000
        if latest is None:
            return False, latency, "no worker has ever reported"
        age = datetime.now(UTC) - latest.heartbeat_at
        if age > timedelta(seconds=settings.WORKER_OFFLINE_AFTER_SECONDS):
            return False, latency, f"last heartbeat {int(age.total_seconds())}s ago"
        return True, latency, f"{latest.name}"
    except Exception as exc:  # noqa: BLE001
        return False, (time.perf_counter() - start) * 1000, str(exc)[:200]


async def _guarded(fn: Callable[[], Awaitable[ProbeResult]]) -> ProbeResult:
    try:
        with anyio.fail_after(PROBE_TIMEOUT):
            return await fn()
    except TimeoutError:
        return False, PROBE_TIMEOUT * 1000, "timeout"
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]


async def collect_health(request: Request) -> HealthReport:
    storage = getattr(request.app.state, "storage", None)
    vectors = getattr(request.app.state, "vectors", None)

    async def db() -> ProbeResult:
        return await to_thread.run_sync(_probe_db)

    async def worker() -> ProbeResult:
        return await to_thread.run_sync(_probe_worker)

    async def qdrant() -> ProbeResult:
        if vectors is None:
            return False, None, "not configured"
        ok, lat, detail = await vectors.health()
        return bool(ok), float(lat), detail

    async def minio() -> ProbeResult:
        if storage is None:
            return False, None, "not configured"
        ok, lat, detail = await to_thread.run_sync(storage.health)
        return bool(ok), float(lat), detail

    async def embedding() -> ProbeResult:
        return await probe_models_endpoint(str(settings.EMBEDDING_BASE_URL))

    async def llm() -> ProbeResult:
        return await probe_models_endpoint(str(settings.LLM_BASE_URL))

    probes: dict[str, Callable[[], Awaitable[ProbeResult]]] = {
        "db": db,
        "qdrant": qdrant,
        "minio": minio,
        "embedding": embedding,
        "llm": llm,
        "worker": worker,
    }
    results: dict[str, ProbeResult] = {}

    async def run(name: str, fn: Callable[[], Awaitable[ProbeResult]]) -> None:
        results[name] = await _guarded(fn)

    async with anyio.create_task_group() as tg:
        for name, fn in probes.items():
            tg.start_soon(run, name, fn)

    services = {
        name: ServiceHealth(ok=ok, latency_ms=lat, detail=detail)
        for name, (ok, lat, detail) in results.items()
    }
    status = "ok" if all(s.ok for s in services.values()) else "degraded"
    return HealthReport(status=status, services=services, checked_at=datetime.now(UTC))


def _without_detail(report: HealthReport) -> HealthReport:
    """The same verdict, with the diagnostics removed.

    Whether each service answers is what a monitor needs, and it is safe to say.
    *Why* it did not is a different thing: a failing database reports its host,
    its port and the user it tried, and the worker probe names the container it
    runs in. None of that is a stranger's business, and this endpoint has no
    credential behind it.
    """
    return HealthReport(
        status=report.status,
        services={
            name: ServiceHealth(
                ok=service.ok,
                latency_ms=service.latency_ms,
                detail=None if service.ok else "unavailable",
            )
            for name, service in report.services.items()
        },
        checked_at=report.checked_at,
    )


@router.get("/", response_model=HealthReport)
async def read_health(request: Request, auth: OptionalAuth) -> Any:
    """Reachability of Postgres, Qdrant, MinIO, the model servers and the worker.

    Open, so a monitor can poll it without a credential. Anyone signed in also
    sees why a service is unhealthy; anyone else sees only that it is.
    """
    cache: tuple[float, HealthReport] | None = getattr(
        request.app.state, "health_cache", None
    )
    now = time.monotonic()
    if cache is not None and now - cache[0] < CACHE_TTL:
        report = cache[1]
    else:
        report = await collect_health(request)
        request.app.state.health_cache = (now, report)
    return report if auth is not None else _without_detail(report)
