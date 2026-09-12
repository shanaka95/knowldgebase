from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlmodel import col, func, select

from app.api.deps import AuthDep, SessionDep
from app.core.config import settings
from app.models import (
    EmbeddingJob,
    JobStatus,
    WorkerHeartbeat,
    WorkerPublic,
    WorkersPublic,
)

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("/", response_model=WorkersPublic)
def read_workers(session: SessionDep, auth: AuthDep) -> Any:  # noqa: ARG001
    """Known embedding workers with their heartbeat status and the queue depth."""
    now = datetime.now(UTC)
    offline_after = timedelta(seconds=settings.WORKER_OFFLINE_AFTER_SECONDS)
    rows = session.exec(
        select(WorkerHeartbeat).order_by(col(WorkerHeartbeat.heartbeat_at).desc())
    ).all()
    workers = [
        WorkerPublic(
            **WorkerHeartbeat.model_validate(w).model_dump(),
            online=(now - w.heartbeat_at) <= offline_after,
        )
        for w in rows
    ]
    queued = session.exec(
        select(func.count())
        .select_from(EmbeddingJob)
        .where(EmbeddingJob.status == JobStatus.queued)
    ).one()
    running = session.exec(
        select(func.count())
        .select_from(EmbeddingJob)
        .where(EmbeddingJob.status == JobStatus.running)
    ).one()
    return WorkersPublic(
        workers=workers,
        any_online=any(w.online for w in workers),
        queued_jobs=queued,
        running_jobs=running,
    )
