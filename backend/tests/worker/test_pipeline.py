from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from sqlmodel import Session, select

from app import crud
from app.core.content import html_to_blocks
from app.models import (
    ChunkingMethod,
    Document,
    EmbeddingJob,
    EmbeddingKind,
    EmbeddingStatus,
    JobStatus,
)
from app.services.vectors import InMemoryVectorStore
from app.worker import queue
from app.worker.pipeline import PipelineDeps, run_job
from tests.worker.conftest import (
    EMBED_URL,
    LLM_URL,
    ScriptedLLM,
    chunk_rows,
    det_vector,
    embeddings_response,
    enqueue_now,
    fresh,
    good_chunking_json,
    make_document,
    make_namespace,
    make_user,
)


def n_blocks(doc: Document) -> int:
    return len(html_to_blocks(doc.content_html))


def claim(job_id: Any, worker: str = "test-worker") -> EmbeddingJob:
    """Claim until this job comes up.

    Other tests leave queued indexing jobs behind, and claiming is first-come,
    so a single batch can fill up with jobs that are not this one.
    """
    for _ in range(50):
        batch = queue.claim_jobs(worker, 50)
        if not batch:
            break
        for job in batch:
            if job.id == job_id:
                return job
    raise AssertionError(f"job {job_id} was never claimable")


def kinds(store: InMemoryVectorStore, document_id: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in store.points.values():
        if p.payload["document_id"] == str(document_id):
            out[p.payload["kind"]] = out.get(p.payload["kind"], 0) + 1
    return out


# --------------------------------------------------------------------- happy path


@pytest.mark.anyio
async def test_happy_path_writes_three_kinds_and_marks_ready(
    db_session: Session,
    deps: PipelineDeps,
    vector_store: InMemoryVectorStore,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    llm = ScriptedLLM([good_chunking_json(n_blocks(doc))])
    mocked_http.post(LLM_URL).mock(side_effect=llm)
    mocked_http.post(EMBED_URL).mock(side_effect=embeddings_response)

    job = claim(enqueue_now(db_session, doc).id)
    assert await run_job(job, deps) == JobStatus.succeeded

    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.ready
    assert d.embedding_version == d.version == 1
    assert d.chunk_count == 2
    assert d.chunking_method == ChunkingMethod.llm
    assert d.summary and "summary" in d.summary
    assert d.embedding_error is None and d.embedding_updated_at is not None

    rows = chunk_rows(db_session, doc.id)
    assert [r.title for r in rows] == ["Onboarding", "Expenses"]
    assert all(r.doc_version == 1 and r.char_count == len(r.text) for r in rows)

    assert kinds(vector_store, doc.id) == {"document": 1, "summary": 1, "chunk": 2}
    for p in vector_store.points.values():
        pl = p.payload
        assert pl["namespace_id"] == str(ns.id) and pl["doc_version"] == 1
        assert len(p.vector) == 1024
        if pl["kind"] == EmbeddingKind.chunk:
            assert pl["chunk_index"] in (0, 1) and pl["title"] in (
                "Onboarding",
                "Expenses",
            )
        else:
            assert pl["title"] == doc.title
    # embedding inputs: document = title + text, chunk = title + text
    assert next(
        p for p in vector_store.points.values() if p.payload["kind"] == "document"
    ).vector == det_vector(f"{doc.title}\n\n{doc.content_text}")

    j = fresh(db_session, EmbeddingJob, job.id)
    assert j.status == JobStatus.succeeded and j.progress == 100 and j.chunk_count == 2
    assert j.stats and j.stats["points"] == 4 and "stage_ms" in j.stats
    assert llm.calls == ["chunk", "summary"]


@pytest.mark.anyio
async def test_short_document_skips_chunking(
    db_session: Session,
    deps: PipelineDeps,
    vector_store: InMemoryVectorStore,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(
        db_session, ns, user, html="<p>Just a tiny note.</p>", title="Note"
    )
    llm = ScriptedLLM([])
    mocked_http.post(LLM_URL).mock(side_effect=llm)
    mocked_http.post(EMBED_URL).mock(side_effect=embeddings_response)

    assert (
        await run_job(claim(enqueue_now(db_session, doc).id), deps)
        == JobStatus.succeeded
    )
    d = fresh(db_session, Document, doc.id)
    assert d.chunking_method == ChunkingMethod.none_short and d.chunk_count == 0
    assert kinds(vector_store, doc.id) == {"document": 1, "summary": 1}
    assert llm.calls == ["summary"]


@pytest.mark.anyio
async def test_llm_garbage_twice_uses_fallback(
    db_session: Session,
    deps: PipelineDeps,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    llm = ScriptedLLM(["garbage", "more garbage"])
    mocked_http.post(LLM_URL).mock(side_effect=llm)
    mocked_http.post(EMBED_URL).mock(side_effect=embeddings_response)

    assert (
        await run_job(claim(enqueue_now(db_session, doc).id), deps)
        == JobStatus.succeeded
    )
    d = fresh(db_session, Document, doc.id)
    assert d.chunking_method == ChunkingMethod.fallback_headings
    assert d.chunk_count == 2 and d.embedding_status == EmbeddingStatus.ready
    j = db_session.exec(
        select(EmbeddingJob).where(EmbeddingJob.document_id == doc.id)
    ).one()
    db_session.refresh(j)
    assert j.stats and "fallback_reason" in j.stats
    assert llm.calls == ["chunk", "chunk", "summary"]


# ------------------------------------------------------------------- failures


@pytest.mark.anyio
async def test_embedding_500_is_retried_with_backoff(
    db_session: Session, deps: PipelineDeps, mocked_http: respx.MockRouter
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n_blocks(doc))])
    )
    mocked_http.post(EMBED_URL).mock(return_value=httpx.Response(500, text="boom"))

    job = claim(enqueue_now(db_session, doc).id)
    assert await run_job(job, deps) == JobStatus.queued

    j = fresh(db_session, EmbeddingJob, job.id)
    assert j.status == JobStatus.queued and j.attempts == 1 and j.locked_by is None
    assert j.run_after > datetime.now(UTC)
    assert "500" in (j.error or "")
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.pending
    assert d.embedding_error is not None and d.embedding_error.startswith("attempt 1/3")
    assert d.embedding_version is None


@pytest.mark.anyio
async def test_final_attempt_marks_failed(
    db_session: Session, deps: PipelineDeps, mocked_http: respx.MockRouter
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n_blocks(doc))])
    )
    mocked_http.post(EMBED_URL).mock(return_value=httpx.Response(500, text="boom"))

    job_id = enqueue_now(db_session, doc).id
    row = db_session.get(EmbeddingJob, job_id)
    assert row is not None
    row.attempts = 2  # this is the third and last attempt
    db_session.add(row)
    db_session.commit()

    assert await run_job(claim(job_id), deps) == JobStatus.failed
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.failed
    assert d.embedding_attempts == 3 and (d.embedding_error or "").startswith(
        "attempt 3/3"
    )


@pytest.mark.anyio
async def test_dimension_mismatch_fails_immediately(
    db_session: Session, deps: PipelineDeps, mocked_http: respx.MockRouter
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n_blocks(doc))])
    )
    mocked_http.post(EMBED_URL).mock(
        side_effect=lambda req: embeddings_response(req, dim=8)
    )

    job = claim(enqueue_now(db_session, doc).id)
    assert await run_job(job, deps) == JobStatus.failed
    j = fresh(db_session, EmbeddingJob, job.id)
    assert j.status == JobStatus.failed and j.attempts == 1
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.failed
    assert "1024" in (d.embedding_error or "")


# ---------------------------------------------------------------- cancellation


class BlockingLLM:
    """Fake LLM whose first call blocks until released (simulates a slow model)."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
    ) -> str:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return json.dumps({"chunks": [{"title": "All", "start": 1, "end": 999}]})


class FakeEmbedder:
    batch_size = 16

    def __init__(self, on_call: Any = None) -> None:
        self.on_call = on_call

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.on_call is not None:
            self.on_call()
        return [det_vector(t) for t in texts]


@pytest.mark.anyio
async def test_update_during_run_cancels_job_and_new_version_succeeds(
    db_session: Session,
    vector_store: InMemoryVectorStore,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    blocking = BlockingLLM()
    deps = PipelineDeps(llm=blocking, embedder=FakeEmbedder(), vectors=vector_store)  # type: ignore[arg-type]

    job1 = claim(enqueue_now(db_session, doc).id)
    task = asyncio.create_task(run_job(job1, deps))
    await asyncio.wait_for(blocking.started.wait(), timeout=10)
    assert (
        fresh(db_session, Document, doc.id).embedding_status == EmbeddingStatus.chunking
    )

    # the user saves a new version while the LLM is still "thinking"
    d = db_session.get(Document, doc.id)
    assert d is not None
    d.version = 2
    d.content_html = d.content_html + "<p>Appendix: brand new paragraph.</p>"
    job2 = crud.enqueue_embedding_job(session=db_session, document=d, force=True)
    db_session.commit()
    assert fresh(db_session, EmbeddingJob, job1.id).cancel_requested is True

    # the runner's cancel watcher would do exactly this
    assert queue.cancelled_job_ids([job1.id]) == [job1.id]
    task.cancel()
    assert await task == JobStatus.cancelled

    j1 = fresh(db_session, EmbeddingJob, job1.id)
    assert j1.status == JobStatus.cancelled
    d = fresh(db_session, Document, doc.id)
    assert (
        d.embedding_status == EmbeddingStatus.pending
    )  # owned by the new job, untouched by the old
    assert d.embedding_version is None and chunk_rows(db_session, doc.id) == []
    assert kinds(vector_store, doc.id) == {}

    # the new job completes normally
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n_blocks(d))])
    )
    mocked_http.post(EMBED_URL).mock(side_effect=embeddings_response)
    from app.services.embeddings import EmbeddingClient
    from app.services.llm import LLMClient

    deps2 = PipelineDeps(
        llm=LLMClient(), embedder=EmbeddingClient(), vectors=vector_store
    )
    assert await run_job(claim(job2.id), deps2) == JobStatus.succeeded
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_status == EmbeddingStatus.ready and d.embedding_version == 2
    assert all(p.payload["doc_version"] == 2 for p in vector_store.points.values())


@pytest.mark.anyio
async def test_checkpoint_detects_cancel_flag_without_task_cancel(
    db_session: Session, vector_store: InMemoryVectorStore
) -> None:
    """If the watcher is slow, the stage-boundary checkpoint still stops the job."""
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    blocking = BlockingLLM()
    deps = PipelineDeps(llm=blocking, embedder=FakeEmbedder(), vectors=vector_store)  # type: ignore[arg-type]
    job = claim(enqueue_now(db_session, doc).id)
    task = asyncio.create_task(run_job(job, deps))
    await asyncio.wait_for(blocking.started.wait(), timeout=10)
    row = db_session.get(EmbeddingJob, job.id)
    assert row is not None
    row.cancel_requested = True
    db_session.add(row)
    db_session.commit()
    blocking.release.set()  # LLM answers, but the next checkpoint must abort
    assert await task == JobStatus.cancelled
    assert fresh(db_session, Document, doc.id).embedding_version is None


@pytest.mark.anyio
async def test_version_bump_before_write_supersedes_job(
    db_session: Session,
    vector_store: InMemoryVectorStore,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n_blocks(doc))])
    )

    def bump_version() -> None:
        with Session(queue.engine) as s:
            d = s.get(Document, doc.id)
            assert d is not None
            d.version = 2
            s.add(d)
            s.commit()

    from app.services.llm import LLMClient

    deps = PipelineDeps(
        llm=LLMClient(),
        embedder=FakeEmbedder(on_call=bump_version),
        vectors=vector_store,
    )  # type: ignore[arg-type]
    job = claim(enqueue_now(db_session, doc).id)
    assert await run_job(job, deps) == JobStatus.superseded
    assert fresh(db_session, EmbeddingJob, job.id).status == JobStatus.superseded
    d = fresh(db_session, Document, doc.id)
    assert d.embedding_version is None and d.summary is None
    assert kinds(vector_store, doc.id) == {}  # nothing written for the stale version


@pytest.mark.anyio
async def test_reembedding_removes_old_version_points(
    db_session: Session,
    deps: PipelineDeps,
    vector_store: InMemoryVectorStore,
    mocked_http: respx.MockRouter,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    n = n_blocks(doc)
    mocked_http.post(LLM_URL).mock(
        side_effect=ScriptedLLM([good_chunking_json(n), good_chunking_json(n)])
    )
    mocked_http.post(EMBED_URL).mock(side_effect=embeddings_response)

    assert (
        await run_job(claim(enqueue_now(db_session, doc).id), deps)
        == JobStatus.succeeded
    )
    assert {p.payload["doc_version"] for p in vector_store.points.values()} == {1}

    d = db_session.get(Document, doc.id)
    assert d is not None
    d.version = 2
    job2 = crud.enqueue_embedding_job(session=db_session, document=d, force=True)
    db_session.commit()
    assert await run_job(claim(job2.id), deps) == JobStatus.succeeded
    versions = {
        p.payload["doc_version"]
        for p in vector_store.points.values()
        if p.payload["document_id"] == str(doc.id)
    }
    assert versions == {2}
    assert kinds(vector_store, doc.id) == {"document": 1, "summary": 1, "chunk": 2}
    rows = chunk_rows(db_session, doc.id)
    assert {r.doc_version for r in rows} == {2}


# ------------------------------------------------------------------ enqueue


def test_enqueue_coalesces_within_debounce(db_session: Session) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    j1 = crud.enqueue_embedding_job(session=db_session, document=doc)
    db_session.commit()
    doc.version = 2
    j2 = crud.enqueue_embedding_job(session=db_session, document=doc)
    db_session.commit()
    assert j1.id == j2.id
    jobs = db_session.exec(
        select(EmbeddingJob).where(EmbeddingJob.document_id == doc.id)
    ).all()
    assert (
        len(jobs) == 1
        and jobs[0].doc_version == 2
        and jobs[0].status == JobStatus.queued
    )
    assert jobs[0].run_after > datetime.now(UTC)
    assert doc.embedding_status == EmbeddingStatus.pending


def test_enqueue_force_supersedes_queued_and_cancels_running(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    ns = make_namespace(db_session, user)
    doc = make_document(db_session, ns, user)
    queued = crud.enqueue_embedding_job(session=db_session, document=doc)
    db_session.commit()
    forced = crud.enqueue_embedding_job(session=db_session, document=doc, force=True)
    db_session.commit()
    assert forced.id != queued.id
    assert fresh(db_session, EmbeddingJob, queued.id).status == JobStatus.superseded

    running = claim(forced.id)
    assert running.status == JobStatus.running
    doc = fresh(db_session, Document, doc.id)
    doc.version += 1
    newest = crud.enqueue_embedding_job(session=db_session, document=doc)
    db_session.commit()
    assert newest.id != forced.id
    assert fresh(db_session, EmbeddingJob, forced.id).cancel_requested is True
