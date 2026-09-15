"""Example searches, written from the reader's own pages.

An empty search box has to say what it is for. Generic examples explain the
mechanics - exact codes favour keywords, a phrased question favours meaning -
and say nothing about what is actually in this knowledge base, which is the
thing a new reader does not know.

So each page contributes one question when it is indexed. The question is
generated from the summary that step has already produced, which makes it a
short prompt against a short input rather than another pass over the document.

These are private. A suggestion belongs to the person whose page produced it,
every read is scoped by user, and nothing here is shown to anybody else even
when the page itself is shared.
"""

from __future__ import annotations

import logging
import random
import uuid

from sqlmodel import Session, col, delete, func, select

from app.core.config import settings
from app.models import SearchSuggestion
from app.services.llm import LLMClient, LLMTask
from app.services.usage import UsageMeter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write one example search query for a knowledge base, based on a summary of one document in it.

Rules:
- Write what a colleague would actually type to find this document later.
- Be specific to this document: name the thing it is about, not its category.
- Between three and ten words. No quotes, no question mark unless it is natural.
- Write it in the language the summary is written in.
- Output only the query. No explanation, no alternatives, no numbering."""

MAX_LENGTH = 120


def _clean(text: str) -> str:
    query = " ".join((text or "").split()).strip().strip('"').strip("'")
    # A model that ignores "output only the query" usually offers a list; the
    # first line is the query and the rest is commentary.
    query = query.split("\n")[0].strip()
    return query[:MAX_LENGTH]


async def question_for_document(
    title: str, summary: str, *, meter: UsageMeter | None = None
) -> str | None:
    """One example search for a page, or None if the model would not write one.

    Failure here is not worth retrying or reporting: the page is indexed either
    way, and the only casualty is one fewer example under the search box.
    """
    source = (summary or "").strip()
    if not source:
        return None
    llm = LLMClient(task=LLMTask.indexing, meter=meter)
    try:
        answer = await llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Title: {title}\n\nSummary: {source}"},
            ],
            max_tokens=60,
            temperature=0.4,
        )
    except Exception:  # noqa: BLE001 - decoration, never a failure
        logger.info("no example search written for %r", title[:60], exc_info=True)
        return None
    finally:
        await llm.close()

    query = _clean(answer)
    return query if len(query) >= 3 else None


def store_suggestion(
    session: Session,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    namespace_id: uuid.UUID,
    question: str,
) -> None:
    """Keep one question per page, replacing the page's previous one.

    A re-indexed page has new content and deserves a new question rather than a
    second row describing the same page twice.
    """
    existing = session.exec(
        select(SearchSuggestion).where(
            SearchSuggestion.user_id == user_id,
            SearchSuggestion.document_id == document_id,
        )
    ).first()
    if existing is not None:
        existing.question = question[:MAX_LENGTH]
        existing.namespace_id = namespace_id
        session.add(existing)
    else:
        session.add(
            SearchSuggestion(
                user_id=user_id,
                document_id=document_id,
                namespace_id=namespace_id,
                question=question[:MAX_LENGTH],
            )
        )
    _prune(session, user_id)
    session.commit()


def _prune(session: Session, user_id: uuid.UUID) -> None:
    cap = settings.SEARCH_SUGGESTIONS_PER_USER
    total = session.exec(
        select(func.count())
        .select_from(SearchSuggestion)
        .where(SearchSuggestion.user_id == user_id)
    ).one()
    if int(total) <= cap:
        return
    stale = session.exec(
        select(col(SearchSuggestion.id))
        .where(SearchSuggestion.user_id == user_id)
        .order_by(col(SearchSuggestion.created_at))
        .limit(int(total) - cap)
    ).all()
    if stale:
        session.exec(
            delete(SearchSuggestion).where(col(SearchSuggestion.id).in_(stale))
        )


def sample_for_user(
    session: Session, user_id: uuid.UUID, limit: int | None = None
) -> list[SearchSuggestion]:
    """A few of this person's examples, different ones each time.

    Sampled in Python over the newest few rather than with `ORDER BY random()`
    over the whole table: the set is small and capped, and this way the newest
    pages - the ones somebody just added and is most likely looking for - are
    the ones being drawn from.
    """
    limit = limit or settings.SEARCH_SUGGESTIONS_SHOWN
    rows = list(
        session.exec(
            select(SearchSuggestion)
            .where(SearchSuggestion.user_id == user_id)
            .order_by(col(SearchSuggestion.created_at).desc())
            .limit(max(limit * 5, 15))
        ).all()
    )

    # One row per document, but two documents can be summarised into the same
    # question - two copies of a policy, a form and its renewal. Offering the
    # same words twice is useless to read and, downstream, gave React two
    # children with the same key, which it is explicit is unsupported.
    seen: set[str] = set()
    pool: list[SearchSuggestion] = []
    for row in rows:
        key = " ".join(row.question.lower().split())
        if key in seen:
            continue
        seen.add(key)
        pool.append(row)

    if len(pool) <= limit:
        return pool
    return random.sample(pool, limit)
