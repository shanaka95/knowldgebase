from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.models import Document, EmbeddingJob, EmbeddingStatus, JobStatus
from app.worker import queue
from tests.worker.conftest import (
    enqueue_now,
    fresh,
    make_document,
    make_namespace,
    make_user,
)


def test_concurrent_claims_never_hand_out_the_same_job(db_session: Session) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    jobs = [
        enqueue_now(db_session, make_document(db_session, ns, user)) for _ in range(6)
    ]
    ids = {j.id for j in jobs}

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda w: queue.claim_jobs(f"w{w}", 6), range(3)))
    claimed = [j.id for batch in results for j in batch]
    # no job may be handed to two workers ...
    assert len(claimed) == len(set(claimed))
    # ... and every job we queued must have been claimed (other tests may have
    # left additional claimable jobs behind, so allow a superset)
    assert ids <= set(claimed)
    for j in ids:
        row = fresh(db_session, EmbeddingJob, j)
        assert row.status == JobStatus.running and row.locked_by is not None


def test_claim_skips_future_and_cancel_requested_jobs(db_session: Session) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    later = enqueue_now(db_session, make_document(db_session, ns, user))
    row = db_session.get(EmbeddingJob, later.id)
    assert row is not None
    row.run_after = datetime.now(UTC) + timedelta(hours=1)
    db_session.add(row)
    cancelled = enqueue_now(db_session, make_document(db_session, ns, user))
    row2 = db_session.get(EmbeddingJob, cancelled.id)
    assert row2 is not None
    row2.cancel_requested = True
    db_session.add(row2)
    db_session.commit()
    claimed = {j.id for j in queue.claim_jobs("w", 50)}
    assert later.id not in claimed and cancelled.id not in claimed


def test_stale_lease_is_reclaimed_then_fails_after_max_attempts(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    job = enqueue_now(db_session, doc)
    row = db_session.get(EmbeddingJob, job.id)
    assert row is not None
    row.max_attempts = 2
    db_session.add(row)
    db_session.commit()

    [claimed] = [j for j in queue.claim_jobs("dead-worker", 50) if j.id == job.id]
    assert claimed.status == JobStatus.running

    def expire() -> None:
        r = db_session.get(EmbeddingJob, job.id)
        assert r is not None
        r.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        db_session.add(r)
        db_session.commit()

    expire()
    assert queue.reclaim_stale(60) >= 1
    row = fresh(db_session, EmbeddingJob, job.id)
    assert (
        row.status == JobStatus.queued and row.attempts == 1 and row.locked_by is None
    )

    [claimed] = [j for j in queue.claim_jobs("dead-worker", 50) if j.id == job.id]
    expire()
    queue.reclaim_stale(60)
    row = fresh(db_session, EmbeddingJob, job.id)
    assert row.status == JobStatus.failed and row.attempts == 2
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.failed
    assert "lease expired" in (d.embedding_error or "")


def test_release_job_requeues_running_job(db_session: Session) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    job = enqueue_now(db_session, doc)
    assert any(j.id == job.id for j in queue.claim_jobs("w", 50))
    queue.release_job(job.id)
    row = fresh(db_session, EmbeddingJob, job.id)
    assert row.status == JobStatus.queued and row.locked_by is None
    assert (
        fresh(db_session, Document, doc.id).embedding_status == EmbeddingStatus.pending
    )
