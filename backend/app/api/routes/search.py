import html
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Float, desc, func, literal, or_
from sqlmodel import Session, col, select

from app.api.deps import (
    AuthDep,
    EmbeddingsDep,
    RerankerDep,
    SessionDep,
    VectorsDep,
)
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
    Note,
    RetrievalHit,
    RetrievalResults,
    RetrievalSourceHit,
    RetrievalSourceReport,
    SearchEntity,
    SearchResult,
    SearchResults,
    SearchSuggestionPublic,
    SearchSuggestionsPublic,
    UsageFeature,
    User,
)
from app.services import credits, retrieval, usage
from app.services.model_client import ModelServerError
from app.services.reranking import (
    Reranker,
    build_candidate_text,
    fit_to_budget,
)
from app.services.retrieval import FusedHit, retrieve
from app.services.sparse import tokenize
from app.services.suggestions import sample_for_user

logger = logging.getLogger(__name__)

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
            doc_type=doc.doc_type,
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
                doc_type=doc.doc_type,
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


async def rerank_hits(
    session: Session,
    user: User,
    query: str,
    hits: Sequence[FusedHit],
    reranker: Reranker | None,
    *,
    meter: usage.UsageMeter | None = None,
) -> tuple[list[FusedHit], list[float]]:
    """Reorder the leading candidates by how well each answers the query.

    Only the front of the list is rescored: fusion is already reliable about
    what belongs in the running, and the reranker is there to settle the order
    at the top, which is the part anyone reads. Anything past the pool keeps its
    fused position behind the rescored block.

    Returns the hits and the reranker's scores, which are empty when it did not
    run - unconfigured, too few candidates to be worth a call, or a failure. A
    reranker that is down must degrade search, not break it.
    """
    ordered = list(hits)
    if reranker is None or len(ordered) < settings.RERANK_MIN_CANDIDATES:
        return ordered, []

    pool = ordered[: settings.RERANK_CANDIDATES]
    tail = ordered[settings.RERANK_CANDIDATES :]
    texts = _candidate_texts(session, user, pool)
    documents = fit_to_budget([texts.get(h.document_id, "") for h in pool])
    if not any(documents):
        return ordered, []

    try:
        scored = await reranker.rerank(query, documents, meter=meter)
    except (ModelServerError, httpx.HTTPError) as exc:
        logger.warning("rerank failed, keeping fused order: %s", exc)
        return ordered, []

    seen: set[int] = set()
    reordered: list[FusedHit] = []
    scores: list[float] = []
    for result in scored:
        if 0 <= result.index < len(pool) and result.index not in seen:
            seen.add(result.index)
            reordered.append(pool[result.index])
            scores.append(result.score)
    # A provider that returns fewer results than it was given must not make
    # candidates disappear from the page.
    for i, hit in enumerate(pool):
        if i not in seen:
            reordered.append(hit)
            scores.append(0.0)
    return reordered + tail, scores


def _note_candidate_texts(
    session: Session, user: User, hits: Sequence[FusedHit]
) -> dict[uuid.UUID, str]:
    """The note half of the reranker's input.

    Easy to leave out, and the symptom does not look like a bug: without it a
    note falls through with an empty string, the reranker scores nothing, and
    every note sinks to the bottom. "Notes are included but never appear" reads
    as a ranking problem rather than a missing branch.
    """
    note_hits = [h for h in hits if h.entity_type == "note"]
    if not note_hits:
        return {}
    rows = session.exec(
        select(Note).where(
            col(Note.id).in_([h.document_id for h in note_hits]),
            col(Note.user_id) == user.id,
        )
    ).all()
    return {
        note.id: build_candidate_text(note.title or "Untitled", body=note.content_text)
        for note in rows
    }


def _candidate_texts(
    session: Session, user: User, hits: Sequence[FusedHit]
) -> dict[uuid.UUID, str]:
    """What each candidate looks like to the reranker: title plus its best text."""
    if not hits:
        return {}
    ids = [h.document_id for h in hits if h.entity_type == "document"]
    if not ids:
        return _note_candidate_texts(session, user, hits)
    rows = session.exec(
        select(Document).where(
            col(Document.id).in_(ids),
            accessible_documents_filter(session, user),
        )
    ).all()
    by_id = {doc.id: doc for doc in rows}

    wanted = {
        (h.document_id, h.best_chunk_index)
        for h in hits
        if h.best_chunk_index is not None and h.document_id in by_id
    }
    chunks: dict[tuple[uuid.UUID, int, int], DocumentChunk] = {}
    if wanted:
        chunk_rows = session.exec(
            select(DocumentChunk).where(
                col(DocumentChunk.document_id).in_({d for d, _ in wanted}),
                col(DocumentChunk.chunk_index).in_({i for _, i in wanted}),
            )
        ).all()
        chunks = {(c.document_id, c.doc_version, c.chunk_index): c for c in chunk_rows}

    out: dict[uuid.UUID, str] = _note_candidate_texts(session, user, hits)
    for hit in hits:
        doc = by_id.get(hit.document_id)
        if doc is None:
            continue
        chunk = None
        if hit.best_chunk_index is not None and doc.embedding_version is not None:
            chunk = chunks.get((doc.id, doc.embedding_version, hit.best_chunk_index))
        out[doc.id] = build_candidate_text(
            doc.title,
            body=doc.content_text,
            summary=doc.summary,
            passage=chunk.text if chunk else None,
        )
    return out


def _note_scope(user: User, namespace_id: uuid.UUID | None) -> retrieval.NoteScope:
    """Whose notes. There is no superuser branch here, and there must not be.

    `_access_scope` above returns `(None, None)` for a superuser, meaning "every
    page". The equivalent for notes does not exist: an administrator reading
    somebody's private notes is a different product.
    """
    return retrieval.NoteScope(
        owner_id=str(user.id),
        namespace_ids=[str(namespace_id)] if namespace_id else None,
    )


def _note_lexical_source(
    session: Session, user: User, namespace_id: uuid.UUID | None
) -> Callable[[str, int], list[tuple[uuid.UUID, float]]]:
    """Postgres full text over this person's notes.

    Archived notes are deliberately not filtered out. Archiving takes a note
    out of the list, not out of the index - that is the whole point of putting
    something away rather than deleting it.
    """

    def run(query: str, limit: int) -> list[tuple[uuid.UUID, float]]:
        tsquery = func.websearch_to_tsquery("english", query)
        rank = func.coalesce(
            func.ts_rank_cd(col(Note.search_vector), tsquery), literal(0.0)
        ).cast(Float)
        where: list[Any] = [
            # Not `accessible_documents_filter`. A note is reachable by exactly
            # one person and this is the only predicate that says so.
            col(Note.user_id) == user.id,
            or_(
                col(Note.search_vector).op("@@")(tsquery),
                col(Note.title).ilike(f"%{query}%"),
            ),
        ]
        if namespace_id is not None:
            where.append(Note.namespace_id == namespace_id)
        rows = session.exec(
            select(Note.id, rank.label("rank"))
            .where(*where)
            .order_by(desc("rank"), col(Note.updated_at).desc())
            .limit(limit)
        ).all()
        return [(row[0], float(row[1] or 0.0)) for row in rows]

    return run


def _hydrate_notes(
    session: Session,
    user: User,
    hits: Sequence[FusedHit],
    tokens: list[str],
) -> dict[uuid.UUID, RetrievalHit]:
    """Load the notes behind the fused hits, keyed by id."""
    note_hits = [h for h in hits if h.entity_type == "note"]
    if not note_hits:
        return {}
    rows = session.exec(
        select(Note).where(
            col(Note.id).in_([h.document_id for h in note_hits]),
            # Defence in depth, exactly as the document path does it: the vector
            # filter already scoped this, and the database is the authority.
            col(Note.user_id) == user.id,
        )
    ).all()
    by_id = {note.id: note for note in rows}

    names: dict[uuid.UUID, str] = {}
    space_ids = {n.namespace_id for n in rows if n.namespace_id}
    if space_ids:
        names = {
            row[0]: row[1]
            for row in session.exec(
                select(Namespace.id, Namespace.name).where(
                    col(Namespace.id).in_(space_ids)
                )
            ).all()
        }

    out: dict[uuid.UUID, RetrievalHit] = {}
    for hit in note_hits:
        note = by_id.get(hit.document_id)
        if note is None:
            continue
        body = f"{note.title}\n\n{note.content_text}".strip()
        out[note.id] = RetrievalHit(
            document_id=note.id,
            entity_type=SearchEntity.note,
            title=note.title or "Untitled",
            doc_type=None,
            namespace_id=note.namespace_id,
            namespace_slug="",
            namespace_name=names.get(note.namespace_id, "")
            if note.namespace_id
            else "",
            folder_id=None,
            score=hit.score,
            snippet=highlight(body, tokens),
            summary=None,
            updated_at=note.updated_at,
            embedding_status=note.embedding_status,
            matched_chunk_index=hit.best_chunk_index,
            matched_chunk_title=None,
            archived=note.archived_at is not None,
            sources=[
                RetrievalSourceHit(
                    method=src.method,
                    target=src.target,
                    rank=src.rank,
                    score=src.score,
                    contribution=src.contribution,
                    chunk_index=src.chunk_index,
                    chunk_title=src.chunk_title,
                    entity=src.entity,
                )
                for src in hit.sources
            ],
        )
    return out


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
    reranker: RerankerDep,
    q: str = Query(min_length=1, max_length=1000),
    bm25: bool = True,
    vector: bool = True,
    targets: list[EmbeddingKind] = Query(  # noqa: B008 - FastAPI query default
        default=[EmbeddingKind.document, EmbeddingKind.summary, EmbeddingKind.chunk]
    ),
    namespace_id: uuid.UUID | None = None,
    limit: int = Query(default=20, le=100),
    rerank: bool = True,
    rrf_k: int | None = Query(default=None, ge=1, le=1000),
    candidates_per_source: int | None = Query(default=None, ge=1, le=500),
    include_pages: bool = True,
    include_notes: bool = False,
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
    if not include_pages and not include_notes:
        raise HTTPException(
            status_code=422, detail="Search pages, notes, or both - not neither"
        )
    # Every (method, target) pair is its own query against the vector store, all
    # fired at once, so a target named a thousand times would turn one cheap
    # request into a thousand expensive ones. Order is kept so the reply names
    # the targets in the order they were asked for.
    targets = list(dict.fromkeys(targets))
    try:
        credits.ensure_credit(session, auth.user)
    except credits.CreditsExhausted as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    started = time.perf_counter()
    namespace_ids, document_ids = _access_scope(session, auth.user, namespace_id)
    # One search, however many calls it turns into - and sometimes none at all,
    # because the same query embedded a minute ago is served from memory.
    async with usage.ameter(auth.user.id, UsageFeature.search) as m:
        m.operation()
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
            lexical=_lexical_source(session, auth.user, namespace_id)
            if include_pages
            else None,
            include_documents=include_pages,
            # `include_notes` defaults to false on the wire while the interface
            # sends true. A client generated before notes existed can then never
            # be handed one and mis-link it, and an API key, an MCP caller or a
            # messaging agent does not silently start answering from somebody's
            # private notes - that is a decision, not a default.
            notes=_note_scope(auth.user, namespace_id) if include_notes else None,
            note_lexical=_note_lexical_source(session, auth.user, namespace_id)
            if include_notes
            else None,
            meter=m,
        )
        # Rerank before trimming to `limit`: the point is to decide which pages
        # deserve the top places, and that cannot be done after they are cut.
        hits, rerank_scores = await rerank_hits(
            session,
            auth.user,
            q.strip(),
            result.hits,
            reranker if rerank else None,
            meter=m,
        )
    wanted = hits[:limit]
    pages = {
        hit.document_id: hit
        for hit in _hydrate(
            session,
            auth.user,
            [h for h in wanted if h.entity_type == "document"],
            result.query_tokens,
        )
    }
    notes_by_id = _hydrate_notes(session, auth.user, wanted, result.query_tokens)
    # Re-merged in the fused order rather than pages-then-notes: the ranking is
    # the whole point of fusing them into one search.
    data = [
        (notes_by_id if h.entity_type == "note" else pages).get(h.document_id)
        for h in wanted
    ]
    data = [hit for hit in data if hit is not None]
    return RetrievalResults(
        data=data,
        count=len(data),
        query=q,
        query_tokens=result.query_tokens,
        # what actually ran: an all-stopword query has no BM25 terms to search
        used_bm25=result.ran_bm25,
        used_vector=result.ran_vector,
        used_rerank=bool(rerank_scores),
        targets=[str(t) for t in targets],
        rrf_k=settings.RRF_K if rrf_k is None else rrf_k,
        sources=[
            RetrievalSourceReport(
                method=s.method,
                target=s.target,
                hits=s.hits,
                took_ms=round(s.took_ms, 2),
                error=s.error,
                entity=s.entity,
            )
            for s in result.sources
        ],
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )


@router.get("/suggestions", response_model=SearchSuggestionsPublic)
def read_search_suggestions(
    session: SessionDep,
    auth: AuthDep,
    limit: int = Query(default=0, ge=0, le=10),
) -> SearchSuggestionsPublic:
    """A few example searches, written from this person's own pages.

    Private by construction: the query is scoped to the asker, and a suggestion
    is only ever written for the person who created the page behind it. Nobody
    sees an example drawn from somebody else's document, shared or not.

    A different few come back each time, so an empty search box does not become
    wallpaper.
    """
    rows = sample_for_user(session, auth.user.id, limit or None)
    return SearchSuggestionsPublic(
        data=[
            SearchSuggestionPublic(question=r.question, document_id=r.document_id)
            for r in rows
        ],
        count=len(rows),
    )
