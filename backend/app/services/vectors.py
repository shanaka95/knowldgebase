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


def note_point_id(
    note_id: uuid.UUID, doc_version: int, kind: str, index: int = 0
) -> str:
    """Deterministic, and in a visibly separate id space from a document's.

    The "note:" prefix means a note and a document that happened to share a
    uuid could never collide on a point id.
    """
    return str(uuid.uuid5(KB_NAMESPACE, f"note:{note_id}:{doc_version}:{kind}:{index}"))


@dataclass(slots=True)
class Point:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    sparse: SparseVector | None = None


def build_note_payload(
    *,
    note_id: uuid.UUID,
    owner_id: uuid.UUID,
    namespace_id: uuid.UUID | None,
    kind: EmbeddingKind | str,
    doc_version: int,
    title: str,
    chunk_index: int | None = None,
    char_count: int | None = None,
) -> dict[str, Any]:
    """A note's payload.

    Carries `note_id`, never `document_id`, so `delete_document` and the
    document-id scope filter cannot reach a note even by accident. `owner_id`
    is not optional: it is the single field that makes reading somebody else's
    note structurally impossible rather than a rule to remember.

    `namespace_id` is omitted rather than null when the note is unfiled, because
    Qdrant treats a missing key as non-matching - which is what makes an unfiled
    note correctly invisible to a space-scoped search.
    """
    payload: dict[str, Any] = {
        "entity_type": "note",
        "note_id": str(note_id),
        "owner_id": str(owner_id),
        "kind": str(kind),
        "doc_version": doc_version,
        "title": title,
        "chunk_index": chunk_index,
        "char_count": char_count,
    }
    if namespace_id is not None:
        payload["namespace_id"] = str(namespace_id)
    return payload


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
        # Which kind of thing this point is about. One collection holds more
        # than pages now, and `kind` cannot say so: it is the *level* a point
        # describes (whole, summary, chunk), which every entity has its own
        # version of. See `_access_filter` for why this field is the thing that
        # keeps the two corpora apart.
        "entity_type": "document",
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
    # Notes get their own methods rather than an `owner_id=None` keyword on the
    # ones above. A default would make "search notes without saying whose" a
    # thing somebody could write; this way it does not type-check.
    async def search_dense_notes(
        self,
        vector: list[float],
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]: ...
    async def search_sparse_notes(
        self,
        vector: SparseVector,
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
    ) -> list[ScoredPoint]: ...
    async def delete_older_note_versions(
        self, note_id: uuid.UUID, keep_version: int
    ) -> None: ...
    async def delete_note(self, note_id: uuid.UUID) -> None: ...
    async def delete_notes_of_owner(self, owner_id: uuid.UUID) -> None: ...
    async def count_note(self, note_id: uuid.UUID) -> int: ...
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
            # Indexed ahead of anything writing them, so the filters that read
            # them are fast from the first point rather than after a backfill.
            ("entity_type", qm.PayloadSchemaType.KEYWORD),
            ("owner_id", qm.PayloadSchemaType.KEYWORD),
            ("note_id", qm.PayloadSchemaType.KEYWORD),
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

        # A document search never returns a note, whatever else is asked for.
        #
        # Written as an exclusion rather than `entity_type == "document"` on
        # purpose: points written before notes existed carry no `entity_type`
        # at all, and `must_not` against a field a point does not have passes.
        # That is what lets notes ship without re-indexing the corpus, and
        # without a window where document search is quietly wrong.
        must: list[Any] = [
            qm.Filter(
                must_not=[
                    qm.FieldCondition(
                        key="entity_type", match=qm.MatchValue(value="note")
                    )
                ]
            )
        ]
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

    # --- notes --------------------------------------------------------------

    def _note_filter(
        self,
        *,
        owner_id: str,
        kind: str | None,
        namespace_ids: list[str] | None,
        note_ids: list[str] | None,
    ) -> Any:
        """Only this person's notes. `owner_id` has no default, deliberately."""
        from qdrant_client import models as qm

        must: list[Any] = [
            qm.FieldCondition(key="entity_type", match=qm.MatchValue(value="note")),
            qm.FieldCondition(key="owner_id", match=qm.MatchValue(value=owner_id)),
        ]
        if kind is not None:
            must.append(qm.FieldCondition(key="kind", match=qm.MatchValue(value=kind)))
        if namespace_ids is not None:
            must.append(
                qm.FieldCondition(
                    key="namespace_id", match=qm.MatchAny(any=namespace_ids)
                )
            )
        if note_ids is not None:
            must.append(
                qm.FieldCondition(key="note_id", match=qm.MatchAny(any=note_ids))
            )
        return qm.Filter(must=must)

    async def _query_notes(
        self,
        query: Any,
        using: str,
        *,
        owner_id: str,
        kind: str | None,
        limit: int,
        namespace_ids: list[str] | None,
        note_ids: list[str] | None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]:
        if namespace_ids is not None and not namespace_ids:
            return []
        if note_ids is not None and not note_ids:
            return []
        result = await self.client.query_points(
            collection_name=self.collection,
            query=query,
            using=using,
            query_filter=self._note_filter(
                owner_id=owner_id,
                kind=kind,
                namespace_ids=namespace_ids,
                note_ids=note_ids,
            ),
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

    async def search_dense_notes(
        self,
        vector: list[float],
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[ScoredPoint]:
        return await self._query_notes(
            vector,
            DENSE_VECTOR,
            owner_id=owner_id,
            kind=kind,
            limit=limit,
            namespace_ids=namespace_ids,
            note_ids=note_ids,
            min_score=min_score,
        )

    async def search_sparse_notes(
        self,
        vector: SparseVector,
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
    ) -> list[ScoredPoint]:
        from qdrant_client import models as qm

        if not vector.indices:
            return []
        return await self._query_notes(
            qm.SparseVector(indices=vector.indices, values=vector.values),
            SPARSE_VECTOR,
            owner_id=owner_id,
            kind=kind,
            limit=limit,
            namespace_ids=namespace_ids,
            note_ids=note_ids,
        )

    async def delete_older_note_versions(
        self, note_id: uuid.UUID, keep_version: int
    ) -> None:
        from qdrant_client import models as qm

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="note_id", match=qm.MatchValue(value=str(note_id))
                        ),
                        qm.FieldCondition(
                            key="doc_version", range=qm.Range(lt=keep_version)
                        ),
                    ]
                )
            ),
            wait=True,
        )

    async def delete_note(self, note_id: uuid.UUID) -> None:
        from qdrant_client import models as qm

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="note_id", match=qm.MatchValue(value=str(note_id))
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def delete_notes_of_owner(self, owner_id: uuid.UUID) -> None:
        """Everything one account wrote.

        `Note.user_id` is CASCADE, so by the time this runs the rows are gone
        and there is nothing left to walk note by note. Owner is the only handle
        left, which is why it is on the payload.
        """
        from qdrant_client import models as qm

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="entity_type", match=qm.MatchValue(value="note")
                        ),
                        qm.FieldCondition(
                            key="owner_id", match=qm.MatchValue(value=str(owner_id))
                        ),
                    ]
                )
            ),
            wait=True,
        )

    async def count_note(self, note_id: uuid.UUID) -> int:
        from qdrant_client import models as qm

        res = await self.client.count(
            collection_name=self.collection,
            count_filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="note_id", match=qm.MatchValue(value=str(note_id))
                    )
                ]
            ),
            exact=True,
        )
        return int(res.count)

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
            # Mirrors the `must_not` in `QdrantStore._access_filter`. A fake
            # that is more permissive than the real store would make every
            # privacy test pass without testing anything.
            if p.payload.get("entity_type") == "note":
                continue
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

    # --- notes --------------------------------------------------------------
    #
    # Faithful to QdrantStore on purpose. The whole suite runs against this
    # fake, so one that is more permissive than the real store would make every
    # privacy test pass without testing anything.

    def _note_candidates(
        self,
        *,
        owner_id: str,
        kind: str | None,
        namespace_ids: list[str] | None,
        note_ids: list[str] | None,
    ) -> list[Point]:
        out = []
        for p in self.points.values():
            pl = p.payload
            if pl.get("entity_type") != "note":
                continue
            if pl.get("owner_id") != owner_id:
                continue
            if kind is not None and pl.get("kind") != kind:
                continue
            if (
                namespace_ids is not None
                and pl.get("namespace_id") not in namespace_ids
            ):
                continue
            if note_ids is not None and pl.get("note_id") not in note_ids:
                continue
            out.append(p)
        return out

    async def search_dense_notes(
        self,
        vector: list[float],
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
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
            for p in self._note_candidates(
                owner_id=owner_id,
                kind=kind,
                namespace_ids=namespace_ids,
                note_ids=note_ids,
            )
        ]
        if min_score is not None:
            scored = [x for x in scored if x.score >= min_score]
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    async def search_sparse_notes(
        self,
        vector: SparseVector,
        *,
        owner_id: str,
        kind: str | None = None,
        limit: int = 50,
        namespace_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
    ) -> list[ScoredPoint]:
        if not vector.indices:
            return []
        wanted = dict(zip(vector.indices, vector.values, strict=False))
        scored = []
        for p in self._note_candidates(
            owner_id=owner_id,
            kind=kind,
            namespace_ids=namespace_ids,
            note_ids=note_ids,
        ):
            if not p.sparse:
                continue
            dot = sum(
                value * wanted.get(index, 0.0)
                for index, value in zip(p.sparse.indices, p.sparse.values, strict=False)
            )
            if dot > 0:
                scored.append(ScoredPoint(p.id, dot, p.payload))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    async def delete_older_note_versions(
        self, note_id: uuid.UUID, keep_version: int
    ) -> None:
        for pid in list(self.points):
            pl = self.points[pid].payload
            if (
                pl.get("note_id") == str(note_id)
                and int(pl.get("doc_version", 0)) < keep_version
            ):
                del self.points[pid]

    async def delete_note(self, note_id: uuid.UUID) -> None:
        for pid in list(self.points):
            if self.points[pid].payload.get("note_id") == str(note_id):
                del self.points[pid]

    async def delete_notes_of_owner(self, owner_id: uuid.UUID) -> None:
        for pid in list(self.points):
            pl = self.points[pid].payload
            if pl.get("entity_type") == "note" and pl.get("owner_id") == str(owner_id):
                del self.points[pid]

    async def count_note(self, note_id: uuid.UUID) -> int:
        return sum(
            1 for p in self.points.values() if p.payload.get("note_id") == str(note_id)
        )

    async def health(self) -> tuple[bool, float, str | None]:
        return True, 0.0, None

    async def close(self) -> None:
        return None
