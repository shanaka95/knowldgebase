"""Ask: hybrid search, then a grounded answer written from what it found.

Retrieval is always the full fusion - every method against every target - because
a question is not the place to make the reader choose search settings. The top
pages become excerpts, the model answers from those alone, and the excerpts come
back with the answer so every claim can be checked.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from app.api.deps import (
    AuthDep,
    EmbeddingsDep,
    RerankerDep,
    SessionDep,
    VectorsDep,
)
from app.api.routes.search import _access_scope, _lexical_source, rerank_hits
from app.core.config import settings
from app.core.permissions import accessible_documents_filter
from app.models import (
    AskAnswer,
    AskCitation,
    AskRequest,
    Document,
    DocumentChunk,
    EmbeddingKind,
    Namespace,
    User,
)
from app.services.answering import (
    AnswerContext,
    Passage,
    answer,
    build_context,
    cited_indexes,
    stream_answer,
)
from app.services.llm import LLMClient
from app.services.reranking import Reranker, keep_count
from app.services.retrieval import FusedHit, retrieve
from app.services.sparse import encode_query
from app.services.vectors import ScoredPoint

router = APIRouter(prefix="/ask", tags=["ask"])


async def _matching_chunks(
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    query: str,
    document_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[int]]:
    """Rank the individual sections of the chosen pages against the question.

    Document ranking answers "which pages are about this?". It does not say
    *where* in a long page the answer sits, and a page's single best-matching
    section is often not the one holding the detail that was asked for - an
    invoice matches on its summary while the amount lives three sections down.
    So the chosen pages get a second, section-level pass.
    """
    if not document_ids:
        return {}
    ids = [str(d) for d in document_ids]
    per_source = settings.RETRIEVAL_CANDIDATES_PER_SOURCE
    sparse_query = encode_query(query)
    dense_query = await embeddings.embed_query(query)

    rankings: dict[tuple[str, str], list[ScoredPoint]] = {}
    if sparse_query.indices:
        rankings[("bm25", EmbeddingKind.chunk)] = await vectors.search_sparse(
            sparse_query, kind=EmbeddingKind.chunk, limit=per_source, document_ids=ids
        )
    rankings[("vector", EmbeddingKind.chunk)] = await vectors.search_dense(
        dense_query,
        kind=EmbeddingKind.chunk,
        limit=per_source,
        document_ids=ids,
        min_score=settings.VECTOR_MIN_SCORE or None,
    )

    # Same fusion as the document ranking, but keyed on the individual section.
    scores: dict[tuple[uuid.UUID, int], float] = {}
    for points in rankings.values():
        for position, point in enumerate(points, start=1):
            raw_id = point.payload.get("document_id")
            chunk_index = point.payload.get("chunk_index")
            if raw_id is None or chunk_index is None:
                continue
            try:
                key = (uuid.UUID(str(raw_id)), int(chunk_index))
            except ValueError:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (settings.RRF_K + position)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    by_document: dict[uuid.UUID, list[int]] = {}
    for (document_id, chunk_index), _ in ordered:
        chunks = by_document.setdefault(document_id, [])
        if len(chunks) < settings.ASK_CHUNKS_PER_DOC:
            chunks.append(chunk_index)
    return by_document


def _passages_for(
    session: Session,
    user: User,
    hits: list[FusedHit],
    chunks_by_document: dict[uuid.UUID, list[int]] | None = None,
) -> list[Passage]:
    """Load the text the model should read, in relevance order.

    Pages keep their ranking order, and within a page its best-matching sections
    come first. A page with no matching section contributes its summary, falling
    back to the page text.
    """
    if not hits:
        return []
    ids = [h.document_id for h in hits]
    rows = session.exec(
        select(Document, Namespace)
        .join(Namespace, col(Namespace.id) == col(Document.namespace_id))
        .where(
            col(Document.id).in_(ids),
            # The vector filter already scoped this; the database is the
            # authority on who may read what.
            accessible_documents_filter(session, user),
        )
    ).all()
    by_id = {doc.id: (doc, ns) for doc, ns in rows}

    chunks_by_document = chunks_by_document or {}
    wanted: set[tuple[uuid.UUID, int]] = set()
    for h in hits:
        if h.document_id not in by_id:
            continue
        indexes = chunks_by_document.get(h.document_id)
        if not indexes and h.best_chunk_index is not None:
            indexes = [h.best_chunk_index]
        for index in indexes or []:
            wanted.add((h.document_id, index))
    chunks: dict[tuple[uuid.UUID, int, int], DocumentChunk] = {}
    if wanted:
        chunk_rows = session.exec(
            select(DocumentChunk).where(
                col(DocumentChunk.document_id).in_({d for d, _ in wanted}),
                col(DocumentChunk.chunk_index).in_({i for _, i in wanted}),
            )
        ).all()
        chunks = {(c.document_id, c.doc_version, c.chunk_index): c for c in chunk_rows}

    passages: list[Passage] = []
    for hit in hits:
        found = by_id.get(hit.document_id)
        if found is None:
            continue
        doc, ns = found

        indexes = chunks_by_document.get(doc.id) or (
            [hit.best_chunk_index] if hit.best_chunk_index is not None else []
        )
        matched = [
            chunks[(doc.id, doc.embedding_version, i)]
            for i in indexes
            if doc.embedding_version is not None
            and (doc.id, doc.embedding_version, i) in chunks
        ]

        if matched:
            for chunk in matched:
                passages.append(
                    Passage(
                        index=len(passages) + 1,
                        document_id=doc.id,
                        title=doc.title,
                        namespace_name=ns.name,
                        text=chunk.text,
                        chunk_index=chunk.chunk_index,
                        chunk_title=chunk.title,
                        score=hit.score,
                    )
                )
        else:
            passages.append(
                Passage(
                    index=len(passages) + 1,
                    document_id=doc.id,
                    title=doc.title,
                    namespace_name=ns.name,
                    # The page itself, not its summary: a summary is written for
                    # matching and drops the specifics an answer needs - a figure
                    # in a table survives here and does not survive there.
                    text=doc.content_text or doc.summary or "",
                    score=hit.score,
                )
            )
        if len(passages) >= settings.ASK_MAX_PASSAGES:
            break
    return passages


def _citations(
    session: Session, context: AnswerContext, answer_text: str
) -> list[AskCitation]:
    """Attach page metadata to each excerpt and mark the ones the answer cites."""
    if not context.passages:
        return []
    ids = [p.document_id for p in context.passages]
    rows = session.exec(
        select(Document, Namespace)
        .join(Namespace, col(Namespace.id) == col(Document.namespace_id))
        .where(col(Document.id).in_(ids))
    ).all()
    meta = {doc.id: (doc, ns) for doc, ns in rows}
    cited = set(cited_indexes(answer_text, len(context.passages)))

    citations: list[AskCitation] = []
    for p in context.passages:
        found = meta.get(p.document_id)
        if found is None:
            continue
        doc, ns = found
        citations.append(
            AskCitation(
                index=p.index,
                document_id=doc.id,
                title=doc.title,
                namespace_id=ns.id,
                namespace_slug=ns.slug,
                namespace_name=ns.name,
                folder_id=doc.folder_id,
                text=p.text,
                chunk_index=p.chunk_index,
                chunk_title=p.chunk_title,
                score=p.score,
                cited=p.index in cited,
                updated_at=doc.updated_at,
            )
        )
    return citations


async def _search(
    session: Session,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: Reranker | None,
    body: AskRequest,
) -> tuple[list[Passage], float, int, bool]:
    """Find the pages worth reading, then narrow them to the ones worth quoting.

    Fusion casts a wide net - ten pages - because recall is what decides whether
    the answer is in the room at all. The reranker then reads the question
    against each of those pages and keeps the few that actually address it.
    Sending all ten to the model would bury the answer in near misses and pay
    for the privilege; sending the reranked top three keeps the prompt short and
    the citations honest.
    """
    started = time.perf_counter()
    question = body.q.strip()
    namespace_ids, document_ids = _access_scope(session, auth.user, body.namespace_id)
    result = await retrieve(
        question,
        vectors=vectors,
        embeddings=embeddings,
        use_bm25=True,
        use_vector=True,
        namespace_ids=namespace_ids,
        document_ids=document_ids,
        lexical=_lexical_source(session, auth.user, body.namespace_id),
    )
    top_k = body.top_k or settings.ASK_TOP_K
    candidates = result.hits[:top_k]

    ranked, scores = await rerank_hits(
        session, auth.user, question, candidates, reranker
    )
    if scores:
        hits = ranked[: keep_count(scores)]
    else:
        hits = ranked[: settings.ASK_DOCUMENTS_WITHOUT_RERANK]

    chunks_by_document = await _matching_chunks(
        vectors, embeddings, question, [h.document_id for h in hits]
    )
    passages = _passages_for(session, auth.user, hits, chunks_by_document)
    return (
        passages,
        (time.perf_counter() - started) * 1000,
        len(result.hits),
        bool(scores),
    )


@router.post("/", response_model=AskAnswer)
async def ask_question(
    session: SessionDep,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: RerankerDep,
    body: AskRequest,
) -> AskAnswer:
    """Answer a question from the knowledge base, with citations."""
    if not body.q.strip():
        raise HTTPException(status_code=422, detail="Ask a question")

    started = time.perf_counter()
    passages, retrieval_ms, searched, reranked = await _search(
        session, auth, vectors, embeddings, reranker, body
    )
    context = build_context(passages)
    llm = LLMClient()
    try:
        text = await answer(llm, body.q, context)
    finally:
        await llm.close()

    return AskAnswer(
        question=body.q.strip(),
        answer=text,
        citations=_citations(session, context, text),
        searched=searched,
        used=len({p.document_id for p in context.passages}),
        passages=len(context.passages),
        reranked=reranked,
        truncated=context.truncated,
        model=settings.LLM_MODEL,
        retrieval_ms=retrieval_ms,
        took_ms=(time.perf_counter() - started) * 1000,
    )


@router.post("/stream")
async def ask_question_stream(
    session: SessionDep,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: RerankerDep,
    body: AskRequest,
) -> StreamingResponse:
    """The same answer, streamed as server-sent events.

    Event order: ``sources`` once the search is done (so the reader can start
    reading the pages immediately), then ``delta`` for each piece of the answer,
    then ``done`` with the timings. Errors arrive as an ``error`` event rather
    than a broken stream.
    """
    if not body.q.strip():
        raise HTTPException(status_code=422, detail="Ask a question")

    started = time.perf_counter()
    passages, retrieval_ms, searched, reranked = await _search(
        session, auth, vectors, embeddings, reranker, body
    )
    context = build_context(passages)
    # Citations are resolved up front so they can be shown while the answer is
    # still being written; `cited` is filled in by the final event.
    citations = _citations(session, context, "")

    def event(name: str, payload: dict[str, object]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"

    async def stream() -> AsyncIterator[str]:
        yield event(
            "sources",
            {
                "citations": [c.model_dump(mode="json") for c in citations],
                "searched": searched,
                "used": len({p.document_id for p in context.passages}),
                "passages": len(context.passages),
                "reranked": reranked,
                "truncated": context.truncated,
                "retrieval_ms": retrieval_ms,
                "model": settings.LLM_MODEL,
            },
        )
        llm = LLMClient()
        collected: list[str] = []
        try:
            async for piece in stream_answer(llm, body.q, context):
                collected.append(piece)
                yield event("delta", {"text": piece})
        except Exception as exc:  # noqa: BLE001 - the reader gets a message, not a stall
            yield event("error", {"message": str(exc)[:300]})
        finally:
            await llm.close()
        text = "".join(collected)
        yield event(
            "done",
            {
                "cited": cited_indexes(text, len(context.passages)),
                "took_ms": (time.perf_counter() - started) * 1000,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
