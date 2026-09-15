"""Ask: hybrid search, then a grounded answer written from what it found.

Retrieval is always the full fusion - every method against every target - because
a question is not the place to make the reader choose search settings. The top
pages become excerpts, the model answers from those alone, and the excerpts come
back with the answer so every claim can be checked.

Two things change that shape:

* **A pinned page.** When the question names the page it is about, there is
  nothing to search for. The page is loaded by id, permission-checked, and read
  whole - no embedding call, no vector query, no reranker, no fusion. That is
  the entire retrieval cost of the request, and it is the cheapest and fastest
  path in the feature.
* **A thread.** Follow-ups carry the last few exchanges, never their excerpts.
  See `app/services/conversations.py` for what is kept and why.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Sequence

from fastapi import APIRouter, HTTPException, Query
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
from app.core.db import engine
from app.core.permissions import accessible_documents_filter, require_document
from app.models import (
    AskAnswer,
    AskCitation,
    AskContext,
    AskConversation,
    AskConversationDetail,
    AskConversationPublic,
    AskConversationsPublic,
    AskConversationUpdate,
    AskMessage,
    AskMessagePublic,
    AskRequest,
    AskRole,
    Document,
    DocumentChunk,
    EmbeddingKind,
    Message,
    Namespace,
    UsageFeature,
    User,
)
from app.services import usage
from app.services.answering import (
    AnswerContext,
    Passage,
    Turn,
    answer,
    answer_language,
    build_context,
    cited_indexes,
    retrieval_query,
    stream_answer,
)
from app.services.conversations import (
    append_message,
    delete_conversation,
    get_conversation,
    history_for_prompt,
    list_conversations,
    load_messages,
    prune_conversations,
    start_conversation,
)
from app.services.llm import LLMClient, LLMTask
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
    *,
    meter: usage.UsageMeter | None = None,
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
    dense_query = await embeddings.embed_query(query, meter=meter)

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

        # One passage per page, carrying the whole page.
        #
        # Chunks are how a page is *found*; they are a poor way to read one. A
        # page that matched in three places used to arrive as three excerpts,
        # which spends the budget on the same document three times, invites the
        # model to cite the same page as though it were three sources, and still
        # omits whatever sits between them - the sentence that qualifies the
        # figure, the row above the total. The whole page costs little more and
        # answers questions the excerpts cannot.
        #
        # Which chunks matched is kept only to label the citation.
        first = matched[0] if matched else None
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
                chunk_index=first.chunk_index if first else None,
                chunk_title=first.title if first else None,
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


def _pinned_passages(
    session: Session, user: User, document_id: uuid.UUID
) -> list[Passage]:
    """The one page the question is pinned to, read whole.

    No search runs: the reader already said which page they mean, so ranking it
    against itself would only add an embedding call, a vector query and a
    reranker pass to a question whose answer is already on the table. The
    permission check is the same one the page itself uses, so pinning cannot
    reach a page the asker could not open.
    """
    document, _ = require_document(session, user, document_id, "viewer")
    namespace = session.get(Namespace, document.namespace_id)
    text = document.content_text or document.summary or ""
    if not text.strip():
        return []
    return [
        Passage(
            index=1,
            document_id=document.id,
            title=document.title,
            namespace_name=namespace.name if namespace else "",
            text=text,
            score=1.0,
        )
    ]


async def _search(
    session: Session,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: Reranker | None,
    body: AskRequest,
    *,
    query: str | None = None,
    meter: usage.UsageMeter | None = None,
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
    # What is searched for can differ from what is asked: a follow-up carries
    # the question before it so that "and in euros?" still finds the invoice.
    question = (query or body.q).strip()
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
        meter=meter,
    )
    top_k = body.top_k or settings.ASK_TOP_K
    candidates = result.hits[:top_k]

    ranked, scores = await rerank_hits(
        session, auth.user, question, candidates, reranker, meter=meter
    )
    if scores:
        hits = ranked[: keep_count(scores)]
    else:
        hits = ranked[: settings.ASK_DOCUMENTS_WITHOUT_RERANK]

    chunks_by_document = await _matching_chunks(
        vectors, embeddings, question, [h.document_id for h in hits], meter=meter
    )
    passages = _passages_for(session, auth.user, hits, chunks_by_document)
    return (
        passages,
        (time.perf_counter() - started) * 1000,
        len(result.hits),
        bool(scores),
    )


# ---------------------------------------------------------------------------
# Preparing a turn
# ---------------------------------------------------------------------------


async def _prepare(
    session: Session,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: Reranker | None,
    body: AskRequest,
    *,
    history: Sequence[Turn] = (),
    meter: usage.UsageMeter | None = None,
) -> tuple[list[Passage], float, int, bool]:
    """Find what this turn should be answered from.

    Returns the passages, how long finding them took, how many pages were
    considered, and whether a reranker chose between them.
    """
    if body.document_id is not None:
        started = time.perf_counter()
        passages = _pinned_passages(session, auth.user, body.document_id)
        return passages, (time.perf_counter() - started) * 1000, len(passages), False

    return await _search(
        session,
        auth,
        vectors,
        embeddings,
        reranker,
        body,
        query=retrieval_query(body.q, history),
        meter=meter,
    )


def _stats(context: AnswerContext, searched: int, took_ms: float) -> dict[str, object]:
    """The footer under an answer, kept with it so a reopened thread has it."""
    return {
        "searched": searched,
        "used": len({p.document_id for p in context.passages}),
        "passages": len(context.passages),
        "truncated": context.truncated,
        "model": settings.LLM_ANSWER_MODEL,
        "took_ms": round(took_ms),
    }


def _resolve_conversation(
    session: Session, user: User, body: AskRequest
) -> AskConversation:
    """The thread this question belongs to, started if it is the first one.

    The thread owns its scope: whichever space or pinned page the asker has
    selected is written back on every turn, so reopening it later restores the
    setup it was last used with.
    """
    if body.conversation_id is None:
        conversation = start_conversation(
            session,
            user,
            question=body.q,
            namespace_id=body.namespace_id,
            document_id=body.document_id,
        )
        prune_conversations(session, user)
        return conversation

    existing = get_conversation(session, user, body.conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation = existing
    if (
        conversation.namespace_id != body.namespace_id
        or conversation.document_id != body.document_id
    ):
        conversation.namespace_id = body.namespace_id
        conversation.document_id = body.document_id
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
    return conversation


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


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
    # A thread is only continued here, never started: this endpoint is what
    # API keys and MCP callers use, and they would otherwise leave a trail of
    # one-question threads in somebody's history. The UI streams instead.
    conversation = (
        _resolve_conversation(session, auth.user, body)
        if body.conversation_id is not None
        else None
    )
    history = (
        history_for_prompt(session, conversation.id) if conversation is not None else []
    )
    async with usage.ameter(auth.user.id, UsageFeature.ask) as m:
        m.operation()
        passages, retrieval_ms, searched, reranked = await _prepare(
            session, auth, vectors, embeddings, reranker, body, history=history, meter=m
        )
        context = build_context(passages)
        llm = LLMClient(task=LLMTask.answer, meter=m)
        try:
            text = await answer(
                llm,
                body.q,
                context,
                history=history,
                language=answer_language(body.q, history),
            )
        finally:
            await llm.close()

    citations = _citations(session, context, text)
    took_ms = (time.perf_counter() - started) * 1000
    if conversation is not None:
        append_message(session, conversation, role=AskRole.user, content=body.q.strip())
        append_message(
            session,
            conversation,
            role=AskRole.assistant,
            content=text,
            citations=citations,
            stats=_stats(context, searched, took_ms),
        )

    return AskAnswer(
        question=body.q.strip(),
        answer=text,
        conversation_id=conversation.id if conversation is not None else None,
        citations=citations,
        searched=searched,
        used=len({p.document_id for p in context.passages}),
        passages=len(context.passages),
        reranked=reranked,
        truncated=context.truncated,
        model=settings.LLM_ANSWER_MODEL,
        retrieval_ms=retrieval_ms,
        took_ms=took_ms,
    )


@router.post("/context", response_model=AskContext)
async def ask_context(
    session: SessionDep,
    auth: AuthDep,
    vectors: VectorsDep,
    embeddings: EmbeddingsDep,
    reranker: RerankerDep,
    body: AskRequest,
) -> AskContext:
    """The pages an answer would be written from, without writing it.

    Identical retrieval to `POST /ask/` - the same fusion, the same reranker,
    the same three pages, the same context budget - and then it stops. A caller
    that is going to compose a reply anyway gets the sources instead of a
    summary of them, and pays for one generation rather than two.
    """
    if not body.q.strip():
        raise HTTPException(status_code=422, detail="Ask a question")

    started = time.perf_counter()
    # Retrieval without generation still embeds and still reranks, so it is
    # still billed - and it is the shape an MCP caller uses most.
    async with usage.ameter(auth.user.id, UsageFeature.ask) as m:
        m.operation()
        passages, retrieval_ms, searched, reranked = await _prepare(
            session, auth, vectors, embeddings, reranker, body, meter=m
        )
    context = build_context(passages)
    return AskContext(
        question=body.q.strip(),
        # No answer exists yet, so nothing is marked as cited.
        documents=_citations(session, context, ""),
        searched=searched,
        used=len({p.document_id for p in context.passages}),
        passages=len(context.passages),
        reranked=reranked,
        truncated=context.truncated,
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

    Event order: ``conversation`` with the thread this turn belongs to, then
    ``sources`` once the search is done (so the reader can start reading the
    pages immediately), then ``delta`` for each piece of the answer, then
    ``done`` with the timings. Errors arrive as an ``error`` event rather than
    a broken stream.
    """
    if not body.q.strip():
        raise HTTPException(status_code=422, detail="Ask a question")

    started = time.perf_counter()
    conversation = _resolve_conversation(session, auth.user, body)
    # Read before the new question is stored, or the question would be in its
    # own history.
    history = history_for_prompt(session, conversation.id)
    # Stored now rather than at the end: a reader who closes the tab mid-answer
    # still finds the thread, with the question they asked in it.
    append_message(session, conversation, role=AskRole.user, content=body.q.strip())

    # Built here, not in a dependency: a `StreamingResponse` iterates its body
    # after the request's dependencies have been torn down, so anything the
    # generator needs has to be captured now - the same reason `user_id` and
    # `language` below are pulled out rather than read later.
    m = usage.UsageMeter(user_id=auth.user.id, feature=UsageFeature.ask)
    m.operation()

    passages, retrieval_ms, searched, reranked = await _prepare(
        session, auth, vectors, embeddings, reranker, body, history=history, meter=m
    )
    context = build_context(passages)
    # Citations are resolved up front so they can be shown while the answer is
    # still being written; `cited` is filled in by the final event.
    citations = _citations(session, context, "")
    # Detected here rather than inside the generator: it is the reader's own
    # words being read, and doing it before the response starts keeps the
    # first byte as early as it was.
    language = answer_language(body.q, history)
    conversation_id = conversation.id
    conversation_title_now = conversation.title
    user_id = auth.user.id

    def event(name: str, payload: dict[str, object]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"

    def save_answer(text: str, took_ms: float) -> None:
        """Store the finished answer on a connection of its own.

        The request's session is not used here: generation takes tens of
        seconds, and holding a pooled database connection open across it would
        tie up the pool for the whole answer. A short transaction at the end
        costs nothing and keeps the connection free meanwhile.
        """
        if not text.strip():
            return
        with Session(engine) as write_session:
            stored = write_session.get(AskConversation, conversation_id)
            if stored is None or stored.user_id != user_id:
                return
            cited = set(cited_indexes(text, len(citations)))
            append_message(
                write_session,
                stored,
                role=AskRole.assistant,
                content=text,
                citations=[
                    c.model_copy(update={"cited": c.index in cited}) for c in citations
                ],
                stats=_stats(context, searched, took_ms),
            )

    async def stream() -> AsyncIterator[str]:
        yield event(
            "conversation",
            {
                "id": str(conversation_id),
                "title": conversation_title_now,
                "document_id": str(body.document_id) if body.document_id else None,
            },
        )
        yield event(
            "sources",
            {
                "citations": [c.model_dump(mode="json") for c in citations],
                "searched": searched,
                "used": len({p.document_id for p in context.passages}),
                "passages": len(context.passages),
                "reranked": reranked,
                "pinned": body.document_id is not None,
                "truncated": context.truncated,
                "retrieval_ms": retrieval_ms,
                "model": settings.LLM_ANSWER_MODEL,
            },
        )
        llm = LLMClient(task=LLMTask.answer, meter=m)
        collected: list[str] = []
        try:
            async for piece in stream_answer(
                llm, body.q, context, history=history, language=language
            ):
                collected.append(piece)
                yield event("delta", {"text": piece})
        except Exception as exc:  # noqa: BLE001 - the reader gets a message, not a stall
            yield event("error", {"message": str(exc)[:300]})
        finally:
            await llm.close()
            # Also reached when the reader navigates away mid-answer, which is
            # why a partial answer is kept rather than lost - and why the
            # tokens spent getting that far are still counted.
            save_answer("".join(collected), (time.perf_counter() - started) * 1000)
            await asyncio.to_thread(m.flush)
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


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


def _conversation_public(
    conversation: AskConversation,
    document_title: str | None = None,
    namespace_slug: str | None = None,
) -> AskConversationPublic:
    return AskConversationPublic(
        id=conversation.id,
        title=conversation.title,
        namespace_id=conversation.namespace_id,
        document_id=conversation.document_id,
        document_title=document_title,
        namespace_slug=namespace_slug,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message_public(message: AskMessage) -> AskMessagePublic:
    return AskMessagePublic(
        id=message.id,
        seq=message.seq,
        role=message.role,
        content=message.content,
        citations=[AskCitation(**c) for c in (message.citations or [])],
        stats=message.stats,
        created_at=message.created_at,
    )


@router.get("/conversations", response_model=AskConversationsPublic)
def read_conversations(
    session: SessionDep,
    auth: AuthDep,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AskConversationsPublic:
    """The asker's threads, newest first.

    Titles and counts only - the messages of a thread are fetched when one is
    opened, so the rail stays a few kilobytes however long the history is.
    """
    rows, count = list_conversations(session, auth.user, limit=limit, offset=offset)
    return AskConversationsPublic(
        data=[_conversation_public(c, title, slug) for c, title, slug in rows],
        count=count,
    )


@router.get("/conversations/{conversation_id}", response_model=AskConversationDetail)
def read_conversation(
    session: SessionDep, auth: AuthDep, conversation_id: uuid.UUID
) -> AskConversationDetail:
    conversation = get_conversation(session, auth.user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    document_title: str | None = None
    namespace_slug: str | None = None
    if conversation.document_id is not None:
        document = session.get(Document, conversation.document_id)
        if document is not None:
            document_title = document.title
            namespace = session.get(Namespace, document.namespace_id)
            namespace_slug = namespace.slug if namespace else None

    base = _conversation_public(conversation, document_title, namespace_slug)
    return AskConversationDetail(
        **base.model_dump(),
        messages=[_message_public(m) for m in load_messages(session, conversation.id)],
    )


@router.patch("/conversations/{conversation_id}", response_model=AskConversationPublic)
def rename_conversation(
    session: SessionDep,
    auth: AuthDep,
    conversation_id: uuid.UUID,
    body: AskConversationUpdate,
) -> AskConversationPublic:
    conversation = get_conversation(session, auth.user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.title = body.title.strip()[:120]
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return _conversation_public(conversation)


@router.delete("/conversations/{conversation_id}")
def remove_conversation(
    session: SessionDep, auth: AuthDep, conversation_id: uuid.UUID
) -> Message:
    conversation = get_conversation(session, auth.user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    delete_conversation(session, conversation)
    return Message(message="Conversation deleted")
