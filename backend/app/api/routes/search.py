import html
import re
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Float, desc, func, literal, or_
from sqlmodel import Session, col, select

from app.api.deps import AuthDep, EmbeddingsDep, SessionDep, VectorsDep
from app.core.config import settings
from app.core.permissions import (
    accessible_documents_filter,
    accessible_namespace_ids,
    require_namespace,
)
from app.models import (
    Document,
    DocumentChunk,
    DocumentShare,
    EmbeddingKind,
    Namespace,
    RetrievalHit,
    RetrievalResults,
    RetrievalSourceHit,
    RetrievalSourceReport,
    SearchResult,
    SearchResults,
    User,
)
from app.services.retrieval import FusedHit, retrieve
from app.services.sparse import tokenize

router = APIRouter(prefix="/search", tags=["search"])

SNIPPET_CHARS = 320
SNIPPET_LEAD = 80
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


@router.get("/", response_model=SearchResults)
def search_documents(
    session: SessionDep,
    auth: AuthDep,
    q: str = Query(min_length=1, max_length=200),
    namespace_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = Query(default=20, le=100),
) -> Any:
    """Full-text search over title + content (Postgres tsvector), scoped to readable documents."""
    q = q.strip()
    if not q:
        return SearchResults(data=[], count=0)
    tsquery = func.websearch_to_tsquery("english", q)
    rank = func.coalesce(
        func.ts_rank_cd(col(Document.search_vector), tsquery), literal(0.0)
    ).cast(Float)
    snippet = func.ts_headline(
        "english",
        col(Document.content_text),
        tsquery,
        "MaxWords=40, MinWords=15, MaxFragments=2, StartSel=<mark>, StopSel=</mark>",
    )
    match = or_(
        col(Document.search_vector).op("@@")(tsquery),
        col(Document.title).ilike(f"%{q}%"),
    )
    where: list[Any] = [accessible_documents_filter(session, auth.user), match]
    if namespace_id is not None:
        where.append(Document.namespace_id == namespace_id)

    count = session.exec(select(func.count()).select_from(Document).where(*where)).one()
    rows = session.exec(
        select(Document, Namespace, rank.label("rank"), snippet.label("snippet"))
        .join(Namespace, col(Namespace.id) == col(Document.namespace_id))
        .where(*where)
        .order_by(desc("rank"), col(Document.updated_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    data = [
        SearchResult(
            document_id=doc.id,
            title=doc.title,
            namespace_id=ns.id,
            namespace_slug=ns.slug,
            namespace_name=ns.name,
            folder_id=doc.folder_id,
            snippet=snip or doc.content_text[:200],
            rank=float(r or 0.0),
            updated_at=doc.updated_at,
            embedding_status=doc.embedding_status,
        )
        for doc, ns, r, snip in rows
    ]
    return SearchResults(data=data, count=count)


# --- hybrid retrieval -------------------------------------------------------------


def highlight(text: str, tokens: Iterable[str]) -> str:
    """HTML-escape ``text`` and wrap words whose stem matches a query token in ``<mark>``.

    Escaping happens per fragment rather than up front, so the marker tags are the
    only markup in the result and entities can never be matched by accident.
    """
    wanted = set(tokens)
    if not wanted:
        return html.escape(text)
    out: list[str] = []
    pos = 0
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        if not any(stem in wanted for stem in tokenize(word)):
            continue
        out.append(html.escape(text[pos : match.start()]))
        out.append(f"<mark>{html.escape(word)}</mark>")
        pos = match.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _window(text: str, tokens: Iterable[str]) -> str:
    """Cut a snippet-sized window centred on the first query-token match."""
    text = " ".join(text.split())
    if len(text) <= SNIPPET_CHARS:
        return text
    wanted = set(tokens)
    start = 0
    for match in _WORD_RE.finditer(text):
        if any(stem in wanted for stem in tokenize(match.group(0))):
            start = max(0, match.start() - SNIPPET_LEAD)
            break
    end = start + SNIPPET_CHARS
    return (
        ("…" if start else "")
        + text[start:end].strip()
        + ("…" if end < len(text) else "")
    )


def _shared_document_ids(session: Session, user: User) -> list[uuid.UUID]:
    return list(
        session.exec(
            select(DocumentShare.document_id).where(DocumentShare.user_id == user.id)
        ).all()
    )


def _access_scope(
    session: Session, user: User, namespace_id: uuid.UUID | None
) -> tuple[list[str] | None, list[str] | None]:
    """Namespace/document ids the vector store may return (``None`` = unrestricted)."""
    if namespace_id is not None:
        require_namespace(session, user, namespace_id, "viewer")
        shared_here = session.exec(
            select(DocumentShare.document_id)
            .join(Document, col(Document.id) == col(DocumentShare.document_id))
            .where(
                DocumentShare.user_id == user.id,
                Document.namespace_id == namespace_id,
            )
        ).all()
        return [str(namespace_id)], [str(d) for d in shared_here]
    if user.is_superuser:
        return None, None
    namespaces = accessible_namespace_ids(session, user)
    return (
        [str(n) for n in namespaces],
        [str(d) for d in _shared_document_ids(session, user)],
    )


def _hydrate(
    session: Session,
    user: User,
    hits: Sequence[FusedHit],
    tokens: list[str],
) -> list[RetrievalHit]:
    """Load the documents behind the fused hits, preserving the RRF order."""
    if not hits:
        return []
    ids = [h.document_id for h in hits]
    rows = session.exec(
        select(Document, Namespace)
        .join(Namespace, col(Namespace.id) == col(Document.namespace_id))
        .where(
            col(Document.id).in_(ids),
            # Defence in depth: the vector filter already scoped this, but the
            # database has the authoritative answer.
            accessible_documents_filter(session, user),
        )
    ).all()
    by_id = {doc.id: (doc, ns) for doc, ns in rows}

    wanted_chunks = {
        (h.document_id, h.best_chunk_index)
        for h in hits
        if h.best_chunk_index is not None and h.document_id in by_id
    }
    chunks: dict[tuple[uuid.UUID, int, int], DocumentChunk] = {}
    if wanted_chunks:
        chunk_rows = session.exec(
            select(DocumentChunk).where(
                col(DocumentChunk.document_id).in_({d for d, _ in wanted_chunks}),
                col(DocumentChunk.chunk_index).in_({i for _, i in wanted_chunks}),
            )
        ).all()
        chunks = {(c.document_id, c.doc_version, c.chunk_index): c for c in chunk_rows}

    results: list[RetrievalHit] = []
    for hit in hits:
        found = by_id.get(hit.document_id)
        if found is None:
            continue
        doc, ns = found
        chunk = None
        if hit.best_chunk_index is not None and doc.embedding_version is not None:
            chunk = chunks.get((doc.id, doc.embedding_version, hit.best_chunk_index))
        if chunk is not None:
            raw_snippet = chunk.text
        elif doc.summary:
            raw_snippet = doc.summary
        else:
            raw_snippet = doc.content_text
        results.append(
            RetrievalHit(
                document_id=doc.id,
                title=doc.title,
                namespace_id=ns.id,
                namespace_slug=ns.slug,
                namespace_name=ns.name,
                folder_id=doc.folder_id,
                score=hit.score,
                snippet=highlight(_window(raw_snippet, tokens), tokens),
                summary=doc.summary,
                updated_at=doc.updated_at,
                embedding_status=doc.embedding_status,
                matched_chunk_index=hit.best_chunk_index if chunk else None,
                matched_chunk_title=chunk.title if chunk else None,
                sources=[
                    RetrievalSourceHit(
                        method=s.method,
                        target=s.target,
                        rank=s.rank,
                        score=s.score,
                        contribution=s.contribution,
                        chunk_index=s.chunk_index,
                        chunk_title=s.chunk_title,
                    )
                    for s in hit.sources
                ],
            )
        )
    return results


def _lexical_source(
    session: Session, user: User, namespace_id: uuid.UUID | None
) -> Callable[[str, int], list[tuple[uuid.UUID, float]]]:
    """Postgres full-text ranking, used as one more source in the fusion.

    Qdrant only knows indexed pages, so without this a page written a minute ago
    would be unfindable.
    """

    def run(query: str, limit: int) -> list[tuple[uuid.UUID, float]]:
        tsquery = func.websearch_to_tsquery("english", query)
        rank = func.coalesce(
            func.ts_rank_cd(col(Document.search_vector), tsquery), literal(0.0)
        ).cast(Float)
        where: list[Any] = [
            accessible_documents_filter(session, user),
            or_(
                col(Document.search_vector).op("@@")(tsquery),
                col(Document.title).ilike(f"%{query}%"),
            ),
        ]
        if namespace_id is not None:
            where.append(Document.namespace_id == namespace_id)
        rows = session.exec(
            select(Document.id, rank.label("rank"))
            .where(*where)
            .order_by(desc("rank"), col(Document.updated_at).desc())
            .limit(limit)
        ).all()
        return [(row[0], float(row[1] or 0.0)) for row in rows]

    return run


@router.get("/retrieve", response_model=RetrievalResults)
async def retrieve_documents(
    session: SessionDep,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    q: str = Query(min_length=1, max_length=1000),
    bm25: bool = True,
    vector: bool = True,
    targets: list[EmbeddingKind] = Query(  # noqa: B008 - FastAPI query default
        default=[EmbeddingKind.document, EmbeddingKind.summary, EmbeddingKind.chunk]
    ),
    namespace_id: uuid.UUID | None = None,
    limit: int = Query(default=20, le=100),
    rrf_k: int | None = Query(default=None, ge=1, le=1000),
    candidates_per_source: int | None = Query(default=None, ge=1, le=500),
) -> Any:
    """Hybrid search: BM25 and/or vector search over pages, summaries and chunks.

    Each enabled method runs against each enabled target as a separate ranked
    source; the rankings are then fused with Reciprocal Rank Fusion, so a page
    several sources agree on outranks one that only a single source likes.
    """
    if not bm25 and not vector:
        raise HTTPException(
            status_code=422,
            detail="Enable at least one search method (bm25 and/or vector)",
        )
    if not targets:
        raise HTTPException(status_code=422, detail="Select at least one search target")

    started = time.perf_counter()
    namespace_ids, document_ids = _access_scope(session, auth.user, namespace_id)
    result = await retrieve(
        q.strip(),
        vectors=vectors,
        embeddings=embeddings,
        use_bm25=bm25,
        use_vector=vector,
        targets=[str(t) for t in targets],
        namespace_ids=namespace_ids,
        document_ids=document_ids,
        candidates_per_source=candidates_per_source,
        rrf_k=rrf_k,
        lexical=_lexical_source(session, auth.user, namespace_id),
    )
    data = _hydrate(session, auth.user, result.hits[:limit], result.query_tokens)
    return RetrievalResults(
        data=data,
        count=len(data),
        query=q,
        query_tokens=result.query_tokens,
        # what actually ran: an all-stopword query has no BM25 terms to search
        used_bm25=result.ran_bm25,
        used_vector=result.ran_vector,
        targets=[str(t) for t in targets],
        rrf_k=settings.RRF_K if rrf_k is None else rrf_k,
        sources=[
            RetrievalSourceReport(
                method=s.method,
                target=s.target,
                hits=s.hits,
                took_ms=round(s.took_ms, 2),
                error=s.error,
            )
            for s in result.sources
        ],
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )
