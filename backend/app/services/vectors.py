"""Vector store abstraction over Qdrant (with an in-memory fake for tests).

Each point carries two vectors so the same store answers both halves of hybrid
search:

* ``dense``  - 1024-dim Jina embedding, cosine distance (semantic similarity),
* ``bm25``   - sparse BM25 vector declared with ``Modifier.IDF`` so Qdrant applies
  inverse document frequency from the real corpus statistics (lexical match).

Point ids are deterministic:
``uuid5(KB_NAMESPACE, f"{document_id}:{doc_version}:{kind}:{index}")`` so
re-running a job is idempotent. Payload schema is documented in docs/EMBEDDINGS.md.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings
from app.models import EmbeddingKind
from app.services.sparse import SparseVector

KB_NAMESPACE = uuid.UUID("6f1c2f2e-7f8a-4e6b-9d3a-2c1b4e5f6a7b")

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"


def point_id(
    document_id: uuid.UUID, doc_version: int, kind: str, index: int = 0
) -> str:
    return str(uuid.uuid5(KB_NAMESPACE, f"{document_id}:{doc_version}:{kind}:{index}"))


@dataclass(slots=True)
class Point:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    sparse: SparseVector | None = None


@dataclass(slots=True)
class ScoredPoint:
    id: str
    score: float
    payload: dict[str, Any]


def build_payload(
    *,
    document_id: uuid.UUID,
    namespace_id: uuid.UUID,
    kind: EmbeddingKind | str,
    doc_version: int,
    title: str,
    chunk_index: int | None = None,
    char_count: int | None = None,
) -> dict[str, Any]:
    return {
        "document_id": str(document_id),
        "namespace_id": str(namespace_id),
        "kind": str(kind),
        "doc_version": doc_version,
        "title": title,
        "chunk_index": chunk_index,
        "char_count": char_count,
    }


class VectorStore(Protocol):
    async def ensure_collection(self) -> None: ...
    async def upsert(self, points: list[Point]) -> None: ...
    async def delete_older_versions(
        self, document_id: uuid.UUID, keep_version: int
    ) -> None: ...
    async def delete_document(self, document_id: uuid.UUID) -> None: ...
    async def count_document(self, document_id: uuid.UUID) -> int: ...
    async def search_dense(
        self,
        vector: list[float],
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]: ...
    async def search_sparse(
        self,
        vector: SparseVector,
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[ScoredPoint]: ...
    async def health(self) -> tuple[bool, float, str | None]: ...
    async def close(self) -> None: ...


class QdrantStore:
    def __init__(
        self,
        url: str = str(settings.QDRANT_URL),
        collection: str = settings.QDRANT_COLLECTION,
        dim: int = settings.EMBEDDING_DIM,
        timeout: float = settings.QDRANT_TIMEOUT_SECONDS,
        api_key: str | None = None,
    ) -> None:
        from qdrant_client import AsyncQdrantClient

        self.collection = collection
        self.dim = dim
        key = settings.QDRANT_API_KEY if api_key is None else api_key
        self.client = AsyncQdrantClient(
            url=url,
            prefer_grpc=False,
            timeout=int(timeout),
            # None rather than "" so the client omits the header entirely when
            # the store is unauthenticated, which is how it runs in development.
            api_key=key or None,
        )

    # --- schema -------------------------------------------------------------

    async def ensure_collection(self) -> None:
        from qdrant_client import models as qm

        dense_config = {
            DENSE_VECTOR: qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE)
        }
        sparse_config = {SPARSE_VECTOR: qm.SparseVectorParams(modifier=qm.Modifier.IDF)}

        if await self.client.collection_exists(self.collection):
            if await self._schema_matches():
                await self._ensure_payload_indexes()
                return
            # A collection created before hybrid search has a single unnamed
            # vector and no sparse field; there is no in-place migration, so it
            # is recreated and the documents are re-indexed by the worker.
            await self.client.delete_collection(self.collection)

        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config=dense_config,
            sparse_vectors_config=sparse_config,
        )
        await self._ensure_payload_indexes()

    async def _schema_matches(self) -> bool:
        info = await self.client.get_collection(self.collection)
        params = info.config.params
        vectors = params.vectors
        if not isinstance(vectors, dict) or DENSE_VECTOR not in vectors:
            return False
        sparse = params.sparse_vectors or {}
        return SPARSE_VECTOR in sparse

    async def _ensure_payload_indexes(self) -> None:
        from qdrant_client import models as qm

        for name, schema in (
            ("document_id", qm.PayloadSchemaType.KEYWORD),
            ("namespace_id", qm.PayloadSchemaType.KEYWORD),
            ("kind", qm.PayloadSchemaType.KEYWORD),
            ("doc_version", qm.PayloadSchemaType.INTEGER),
        ):
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=name,
                    field_schema=schema,
                )
            except Exception:  # noqa: BLE001 - index already exists
                pass

    # --- writes -------------------------------------------------------------

    async def upsert(self, points: list[Point]) -> None:
        from qdrant_client import models as qm

        if not points:
            return
        structs = []
        for p in points:
            vector: dict[str, Any] = {DENSE_VECTOR: p.vector}
            if p.sparse and p.sparse.indices:
                vector[SPARSE_VECTOR] = qm.SparseVector(
                    indices=p.sparse.indices, values=p.sparse.values
                )
            structs.append(qm.PointStruct(id=p.id, vector=vector, payload=p.payload))
        await self.client.upsert(
            collection_name=self.collection, points=structs, wait=True
        )

    async def delete_older_versions(
        self, document_id: uuid.UUID, keep_version: int
    ) -> None:
        from qdrant_client import models as qm

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="document_id",
                            match=qm.MatchValue(value=str(document_id)),
                        ),
                        qm.FieldCondition(
                            key="doc_version", range=qm.Range(lt=keep_version)
                        ),
                    ]
                )
            ),
            wait=True,
        )

    async def delete_document(self, document_id: uuid.UUID) -> None:
        from qdrant_client import models as qm

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="document_id",
                            match=qm.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def count_document(self, document_id: uuid.UUID) -> int:
        from qdrant_client import models as qm

        res = await self.client.count(
            collection_name=self.collection,
            count_filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="document_id", match=qm.MatchValue(value=str(document_id))
                    )
                ]
            ),
            exact=True,
        )
        return int(res.count)

    # --- reads --------------------------------------------------------------

    def _access_filter(
        self,
        kind: str | None,
        namespace_ids: list[str] | None,
        document_ids: list[str] | None,
    ) -> Any:
        from qdrant_client import models as qm

        must: list[Any] = []
        if kind is not None:
            must.append(qm.FieldCondition(key="kind", match=qm.MatchValue(value=kind)))
        # ``None`` means unrestricted (superuser); an empty list means no access.
        if namespace_ids is not None or document_ids is not None:
            should: list[Any] = []
            if namespace_ids:
                should.append(
                    qm.FieldCondition(
                        key="namespace_id", match=qm.MatchAny(any=namespace_ids)
                    )
                )
            if document_ids:
                should.append(
                    qm.FieldCondition(
                        key="document_id", match=qm.MatchAny(any=document_ids)
                    )
                )
            if not should:
                return None  # caller short-circuits: nothing is accessible
            must.append(qm.Filter(should=should))
        return qm.Filter(must=must) if must else None

    async def _query(
        self,
        query: Any,
        using: str,
        kind: str | None,
        limit: int,
        namespace_ids: list[str] | None,
        document_ids: list[str] | None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]:
        restricted = namespace_ids is not None or document_ids is not None
        query_filter = self._access_filter(kind, namespace_ids, document_ids)
        if restricted and query_filter is None:
            return []
        result = await self.client.query_points(
            collection_name=self.collection,
            query=query,
            using=using,
            query_filter=query_filter,
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return [
            ScoredPoint(
                id=str(p.id), score=float(p.score), payload=dict(p.payload or {})
            )
            for p in result.points
        ]

    async def search_dense(
        self,
        vector: list[float],
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]:
        return await self._query(
            vector, DENSE_VECTOR, kind, limit, namespace_ids, document_ids, min_score
        )

    async def search_sparse(
        self,
        vector: SparseVector,
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[ScoredPoint]:
        from qdrant_client import models as qm

        if not vector.indices:
            return []
        query = qm.SparseVector(indices=vector.indices, values=vector.values)
        return await self._query(
            query, SPARSE_VECTOR, kind, limit, namespace_ids, document_ids
        )

    async def health(self) -> tuple[bool, float, str | None]:
        start = time.perf_counter()
        try:
            exists = await self.client.collection_exists(self.collection)
            return (
                True,
                (time.perf_counter() - start) * 1000,
                None if exists else "collection missing",
            )
        except Exception as exc:  # noqa: BLE001
            return False, (time.perf_counter() - start) * 1000, str(exc)[:200]

    async def close(self) -> None:
        await self.client.close()


class InMemoryVectorStore:
    """Dict-backed store for tests: cosine for dense, dot product for sparse."""

    def __init__(self) -> None:
        self.points: dict[str, Point] = {}

    async def ensure_collection(self) -> None:
        return None

    async def upsert(self, points: list[Point]) -> None:
        for p in points:
            self.points[p.id] = p

    async def delete_older_versions(
        self, document_id: uuid.UUID, keep_version: int
    ) -> None:
        for pid in list(self.points):
            pl = self.points[pid].payload
            if (
                pl.get("document_id") == str(document_id)
                and int(pl.get("doc_version", 0)) < keep_version
            ):
                del self.points[pid]

    async def delete_document(self, document_id: uuid.UUID) -> None:
        for pid in list(self.points):
            if self.points[pid].payload.get("document_id") == str(document_id):
                del self.points[pid]

    async def count_document(self, document_id: uuid.UUID) -> int:
        return sum(
            1
            for p in self.points.values()
            if p.payload.get("document_id") == str(document_id)
        )

    def _candidates(
        self,
        kind: str | None,
        namespace_ids: list[str] | None,
        document_ids: list[str] | None,
    ) -> list[Point]:
        out = []
        for p in self.points.values():
            if kind is not None and p.payload.get("kind") != kind:
                continue
            if namespace_ids is not None or document_ids is not None:
                allowed = (
                    namespace_ids and p.payload.get("namespace_id") in namespace_ids
                ) or (document_ids and p.payload.get("document_id") in document_ids)
                if not allowed:
                    continue
            out.append(p)
        return out

    async def search_dense(
        self,
        vector: list[float],
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]:
        import math

        def cosine(a: list[float], b: list[float]) -> float:
            if not a or not b:
                return 0.0
            dot = sum(x * y for x, y in zip(a, b, strict=False))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        scored = [
            ScoredPoint(p.id, cosine(vector, p.vector), p.payload)
            for p in self._candidates(kind, namespace_ids, document_ids)
        ]
        if min_score is not None:
            scored = [s for s in scored if s.score >= min_score]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    async def search_sparse(
        self,
        vector: SparseVector,
        *,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[ScoredPoint]:
        if not vector.indices:
            return []
        q = dict(zip(vector.indices, vector.values, strict=False))
        scored: list[ScoredPoint] = []
        for p in self._candidates(kind, namespace_ids, document_ids):
            if not p.sparse:
                continue
            dot = sum(
                v * q.get(i, 0.0)
                for i, v in zip(p.sparse.indices, p.sparse.values, strict=False)
            )
            if dot > 0:
                scored.append(ScoredPoint(p.id, dot, p.payload))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    async def health(self) -> tuple[bool, float, str | None]:
        return True, 0.0, None

    async def close(self) -> None:
        return None
