"""Hybrid retrieval: BM25 + dense vector search fused with Reciprocal Rank Fusion.

Each enabled (method, target) pair is an independent *source*:

    bm25:document   bm25:summary   bm25:chunk
    vector:document vector:summary vector:chunk

Every source returns its own ranking. Ranks - not scores - are then fused, which
is what makes RRF work across methods whose scores are not comparable (cosine
similarity in [-1, 1] versus unbounded BM25):

    score(doc) = sum over sources of  1 / (k + rank_in_that_source)

``k`` (default 60) damps the influence of any single source's top hit, so a
document found by several sources outranks one that a single source loves.
Because several points (chunks) can map to the same document, a document takes
its *best* rank within each source.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import settings
from app.models import EmbeddingKind
from app.services.sparse import encode_query, tokenize
from app.services.usage import UsageMeter
from app.services.vectors import ScoredPoint, VectorStore

SearchMethod = str  # "bm25" | "vector"


class Embedder(Protocol):
    """Just the part of the embedding client retrieval needs."""

    async def embed(
        self, texts: list[str], *, meter: UsageMeter | None = None
    ) -> list[list[float]]: ...
    async def embed_query(
        self, text: str, *, meter: UsageMeter | None = None
    ) -> list[float]: ...


class LexicalSearch(Protocol):
    """A keyword search that does not depend on the vector store.

    Qdrant only knows about pages the worker has already indexed, so a page is
    unfindable for the minute or two after it is written. Postgres full-text
    search sees it immediately, which is why it joins the fusion as its own
    source rather than being a separate feature.
    """

    def __call__(self, query: str, limit: int, /) -> list[tuple[uuid.UUID, float]]: ...


@dataclass(slots=True)
class SourceHit:
    """One source's opinion about one document."""

    method: SearchMethod
    target: str  # document | summary | chunk
    rank: int  # 1-based
    score: float
    contribution: float
    chunk_index: int | None = None
    chunk_title: str | None = None


@dataclass(slots=True)
class FusedHit:
    document_id: uuid.UUID
    score: float
    sources: list[SourceHit] = field(default_factory=list)

    @property
    def best_chunk_index(self) -> int | None:
        chunk_hits = [s for s in self.sources if s.target == EmbeddingKind.chunk]
        if not chunk_hits:
            return None
        return min(chunk_hits, key=lambda s: s.rank).chunk_index


@dataclass(slots=True)
class SourceReport:
    """Per-source diagnostics returned to the UI."""

    method: SearchMethod
    target: str
    hits: int
    took_ms: float
    error: str | None = None


@dataclass(slots=True)
class RetrievalResult:
    hits: list[FusedHit]
    sources: list[SourceReport]
    query_tokens: list[str]
    # What actually ran. BM25 is skipped when the query is all stopwords, so this
    # can be False even though the caller asked for it.
    ran_bm25: bool = False
    ran_vector: bool = False


DEFAULT_TARGETS: tuple[str, ...] = (
    EmbeddingKind.document,
    EmbeddingKind.summary,
    EmbeddingKind.chunk,
)

FULLTEXT_METHOD = "fulltext"
FULLTEXT_TARGET = "page"


def reciprocal_rank_fusion(
    rankings: dict[tuple[SearchMethod, str], list[ScoredPoint]],
    *,
    k: int | None = None,
) -> list[FusedHit]:
    """Fuse per-source point rankings into a single document ranking."""
    k = settings.RRF_K if k is None else k
    fused: dict[uuid.UUID, FusedHit] = {}

    for (method, target), points in rankings.items():
        seen_in_source: set[uuid.UUID] = set()
        for position, point in enumerate(points, start=1):
            raw_id = point.payload.get("document_id")
            if not raw_id:
                continue
            try:
                document_id = uuid.UUID(str(raw_id))
            except ValueError:
                continue
            # Several chunks of one document may hit; only its best rank counts.
            if document_id in seen_in_source:
                continue
            seen_in_source.add(document_id)

            contribution = 1.0 / (k + position)
            hit = fused.setdefault(document_id, FusedHit(document_id, 0.0))
            hit.score += contribution
            hit.sources.append(
                SourceHit(
                    method=method,
                    target=target,
                    rank=position,
                    score=point.score,
                    contribution=contribution,
                    chunk_index=point.payload.get("chunk_index"),
                    chunk_title=point.payload.get("title"),
                )
            )

    ordered = sorted(fused.values(), key=lambda h: h.score, reverse=True)
    for hit in ordered:
        hit.sources.sort(key=lambda s: s.contribution, reverse=True)
    return ordered


async def retrieve(
    query: str,
    *,
    vectors: VectorStore,
    embeddings: Embedder,
    use_bm25: bool = True,
    use_vector: bool = True,
    targets: tuple[str, ...] | list[str] = DEFAULT_TARGETS,
    namespace_ids: list[str] | None = None,
    document_ids: list[str] | None = None,
    candidates_per_source: int | None = None,
    rrf_k: int | None = None,
    vector_min_score: float | None = None,
    lexical: LexicalSearch | None = None,
    meter: UsageMeter | None = None,
) -> RetrievalResult:
    """Run every enabled source concurrently and fuse the rankings with RRF."""
    per_source = candidates_per_source or settings.RETRIEVAL_CANDIDATES_PER_SOURCE
    floor = settings.VECTOR_MIN_SCORE if vector_min_score is None else vector_min_score
    targets = tuple(targets)
    sparse_query = encode_query(query)

    dense_query: list[float] | None = None
    if use_vector:
        # One embedding call serves every vector target, and a repeat of the
        # same query costs nothing at all.
        dense_query = await embeddings.embed_query(query, meter=meter)

    async def run_one(
        method: SearchMethod, target: str
    ) -> tuple[tuple[SearchMethod, str], list[ScoredPoint], SourceReport]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            if method == "bm25":
                points = await vectors.search_sparse(
                    sparse_query,
                    kind=target,
                    limit=per_source,
                    namespace_ids=namespace_ids,
                    document_ids=document_ids,
                )
            else:
                assert dense_query is not None
                points = await vectors.search_dense(
                    dense_query,
                    kind=target,
                    limit=per_source,
                    namespace_ids=namespace_ids,
                    document_ids=document_ids,
                    min_score=floor or None,
                )
            took = (loop.time() - started) * 1000
            return (
                (method, target),
                points,
                SourceReport(method, target, len(points), took),
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the search
            took = (loop.time() - started) * 1000
            return (
                (method, target),
                [],
                SourceReport(method, target, 0, took, str(exc)[:200]),
            )

    async def run_lexical() -> tuple[
        tuple[SearchMethod, str], list[ScoredPoint], SourceReport
    ]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        key = (FULLTEXT_METHOD, FULLTEXT_TARGET)
        assert lexical is not None
        try:
            rows = await asyncio.to_thread(lexical, query, per_source)
            points = [
                ScoredPoint(
                    id=str(document_id),
                    score=score,
                    payload={
                        "document_id": str(document_id),
                        "kind": FULLTEXT_TARGET,
                        "chunk_index": None,
                        "title": None,
                    },
                )
                for document_id, score in rows
            ]
            took = (loop.time() - started) * 1000
            return (
                key,
                points,
                SourceReport(FULLTEXT_METHOD, FULLTEXT_TARGET, len(points), took),
            )
        except Exception as exc:  # noqa: BLE001
            took = (loop.time() - started) * 1000
            return (
                key,
                [],
                SourceReport(FULLTEXT_METHOD, FULLTEXT_TARGET, 0, took, str(exc)[:200]),
            )

    ran_bm25 = bool(use_bm25 and sparse_query.indices)
    ran_vector = bool(use_vector)
    jobs = []
    if ran_bm25:
        jobs += [run_one("bm25", t) for t in targets]
    if ran_vector:
        jobs += [run_one("vector", t) for t in targets]
    # Keyword search also covers pages that are not in the vector store yet.
    if use_bm25 and lexical is not None:
        jobs.append(run_lexical())

    if not jobs:
        return RetrievalResult([], [], tokenize(query), ran_bm25, ran_vector)

    results = await asyncio.gather(*jobs)
    rankings = {key: points for key, points, _ in results}
    reports = [report for _, _, report in results]

    return RetrievalResult(
        hits=reciprocal_rank_fusion(rankings, k=rrf_k),
        sources=reports,
        query_tokens=tokenize(query),
        ran_bm25=ran_bm25,
        ran_vector=ran_vector,
    )
