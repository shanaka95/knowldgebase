"""Reciprocal Rank Fusion and the multi-source retrieval orchestration."""

import uuid

import pytest

from app.models import EmbeddingKind
from app.services.retrieval import reciprocal_rank_fusion, retrieve
from app.services.sparse import encode_document
from app.services.vectors import InMemoryVectorStore, Point, ScoredPoint, build_payload

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def point(
    document_id: uuid.UUID,
    score: float,
    kind: str = EmbeddingKind.document,
    chunk_index: int | None = None,
) -> ScoredPoint:
    return ScoredPoint(
        id=str(uuid.uuid4()),
        score=score,
        payload={
            "document_id": str(document_id),
            "kind": kind,
            "chunk_index": chunk_index,
            "title": "title",
        },
    )


def test_agreement_across_sources_beats_one_strong_source() -> None:
    loved, agreed = uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion(
        {
            ("bm25", EmbeddingKind.document, "document"): [
                point(loved, 99.0),
                point(agreed, 1.0),
            ],
            ("vector", EmbeddingKind.document, "document"): [point(agreed, 0.9)],
            ("vector", EmbeddingKind.chunk, "document"): [
                point(agreed, 0.8, EmbeddingKind.chunk, 0)
            ],
        },
        k=60,
    )
    assert fused[0].document_id == agreed
    assert fused[0].score > fused[1].score
    assert {s.method for s in fused[0].sources} == {"bm25", "vector"}


def test_one_document_counts_once_per_source_at_its_best_rank() -> None:
    doc = uuid.uuid4()
    fused = reciprocal_rank_fusion(
        {
            ("vector", EmbeddingKind.chunk, "document"): [
                point(doc, 0.9, EmbeddingKind.chunk, 3),
                point(doc, 0.8, EmbeddingKind.chunk, 4),
                point(doc, 0.7, EmbeddingKind.chunk, 5),
            ]
        },
        k=60,
    )
    assert len(fused) == 1
    assert len(fused[0].sources) == 1, "three chunks of one document are one vote"
    assert fused[0].sources[0].rank == 1
    assert fused[0].best_chunk_index == 3
    assert fused[0].score == pytest.approx(1 / 61)


def test_small_k_sharpens_the_advantage_of_rank_one() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    ranking = {
        ("bm25", EmbeddingKind.document, "document"): [
            point(first, 9.0),
            point(second, 8.0),
        ]
    }
    sharp = reciprocal_rank_fusion(ranking, k=1)
    flat = reciprocal_rank_fusion(ranking, k=1000)
    sharp_gap = sharp[0].score - sharp[1].score
    flat_gap = flat[0].score - flat[1].score
    assert sharp_gap > flat_gap


def test_empty_and_malformed_rankings() -> None:
    assert reciprocal_rank_fusion({}) == []
    junk = ScoredPoint(id="x", score=1.0, payload={"document_id": "not-a-uuid"})
    missing = ScoredPoint(id="y", score=1.0, payload={})
    assert (
        reciprocal_rank_fusion({("bm25", "document", "document"): [junk, missing]})
        == []
    )


class StubEmbeddings:
    """Deterministic 4-dim embeddings; records how often it was called."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: list[str], **_: object) -> list[list[float]]:
        self.calls += 1
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]

    async def embed_query(self, text: str, **_: object) -> list[float]:
        return (await self.embed([text]))[0]


async def _store_with(document_id: uuid.UUID, text: str) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    namespace_id = uuid.uuid4()
    await store.upsert(
        [
            Point(
                id=str(uuid.uuid4()),
                vector=[1.0, 1.0, 0.5, 0.25],
                sparse=encode_document(text),
                payload=build_payload(
                    document_id=document_id,
                    namespace_id=namespace_id,
                    kind=EmbeddingKind.document,
                    doc_version=1,
                    title="Budget review",
                ),
            )
        ]
    )
    return store


async def test_retrieve_runs_both_methods_and_reports_each_source() -> None:
    doc = uuid.uuid4()
    store = await _store_with(doc, "quarterly budget review of cloud spend")
    embeddings = StubEmbeddings()

    result = await retrieve(
        "budget review",
        vectors=store,
        embeddings=embeddings,
        targets=[EmbeddingKind.document],
    )

    assert embeddings.calls == 1, "one embedding call serves every vector target"
    assert {(s.method, s.target) for s in result.sources} == {
        ("bm25", EmbeddingKind.document),
        ("vector", EmbeddingKind.document),
    }
    assert result.hits and result.hits[0].document_id == doc
    assert {s.method for s in result.hits[0].sources} == {"bm25", "vector"}
    assert result.query_tokens == ["budget", "review"]


async def test_disabling_bm25_skips_its_sources_entirely() -> None:
    doc = uuid.uuid4()
    store = await _store_with(doc, "quarterly budget review")

    result = await retrieve(
        "budget",
        vectors=store,
        embeddings=StubEmbeddings(),
        use_bm25=False,
        targets=[EmbeddingKind.document],
    )
    assert {s.method for s in result.sources} == {"vector"}


async def test_disabling_vector_never_embeds() -> None:
    doc = uuid.uuid4()
    store = await _store_with(doc, "quarterly budget review")
    embeddings = StubEmbeddings()

    result = await retrieve(
        "budget",
        vectors=store,
        embeddings=embeddings,
        use_vector=False,
        targets=[EmbeddingKind.document],
    )
    assert embeddings.calls == 0
    assert {s.method for s in result.sources} == {"bm25"}


async def test_a_failing_source_does_not_kill_the_search() -> None:
    class BrokenSparse(InMemoryVectorStore):
        async def search_sparse(
            self, *args: object, **kwargs: object
        ) -> list[ScoredPoint]:
            raise RuntimeError("qdrant down")

    doc = uuid.uuid4()
    store = BrokenSparse()
    await store.upsert(
        [
            Point(
                id=str(uuid.uuid4()),
                vector=[1.0, 1.0, 0.5, 0.25],
                sparse=encode_document("budget"),
                payload=build_payload(
                    document_id=doc,
                    namespace_id=uuid.uuid4(),
                    kind=EmbeddingKind.document,
                    doc_version=1,
                    title="Budget",
                ),
            )
        ]
    )
    result = await retrieve(
        "budget",
        vectors=store,
        embeddings=StubEmbeddings(),
        targets=[EmbeddingKind.document],
    )
    errors = [s for s in result.sources if s.error]
    assert len(errors) == 1
    assert "qdrant down" in (errors[0].error or "")
    assert result.hits, "the healthy vector source still returned results"
