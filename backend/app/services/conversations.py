"""Ask threads: storing them, reading them back, and feeding them to the model.

A thread is a private list of questions and answers belonging to one person.
Two things are deliberately *not* stored: the excerpts each answer was written
from (a whole page per citation - hundreds of kilobytes a turn, and stale the
moment the page is edited) and anything derived by a model (titles come from
the first question, not from a generation call).

What is stored is what the reader needs to recognise the thread later: the
text of both sides, which pages were cited, and a short preview of each.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.models import (
    AskCitation,
    AskConversation,
    AskMessage,
    AskRole,
    Document,
    Namespace,
    User,
)
from app.services.answering import Turn, conversation_title


def get_conversation(
    session: Session, user: User, conversation_id: uuid.UUID
) -> AskConversation | None:
    """One thread, or nothing - a thread of somebody else's is not found."""
    return session.exec(
        select(AskConversation).where(
            AskConversation.id == conversation_id,
            AskConversation.user_id == user.id,
        )
    ).first()


def list_conversations(
    session: Session, user: User, *, limit: int = 30, offset: int = 0
) -> tuple[list[tuple[AskConversation, str | None, str | None]], int]:
    """Newest first, with the pinned page's title resolved in the same query."""
    count = session.exec(
        select(func.count())
        .select_from(AskConversation)
        .where(AskConversation.user_id == user.id)
    ).one()
    rows = session.exec(
        select(AskConversation, Document.title, Namespace.slug)
        .join(
            Document,
            col(Document.id) == col(AskConversation.document_id),
            isouter=True,
        )
        .join(
            Namespace,
            col(Namespace.id) == col(Document.namespace_id),
            isouter=True,
        )
        .where(AskConversation.user_id == user.id)
        .order_by(col(AskConversation.updated_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [(c, title, slug) for c, title, slug in rows], int(count)


def load_messages(
    session: Session, conversation_id: uuid.UUID, *, limit: int | None = None
) -> list[AskMessage]:
    statement = (
        select(AskMessage)
        .where(AskMessage.conversation_id == conversation_id)
        .order_by(col(AskMessage.seq))
    )
    if limit is not None:
        # The newest `limit` messages, put back in reading order.
        newest = session.exec(
            select(AskMessage)
            .where(AskMessage.conversation_id == conversation_id)
            .order_by(col(AskMessage.seq).desc())
            .limit(limit)
        ).all()
        return sorted(newest, key=lambda m: m.seq)
    return list(session.exec(statement).all())


def history_for_prompt(session: Session, conversation_id: uuid.UUID) -> list[Turn]:
    """The last few exchanges, as the model should see them.

    Only the turns that can still fit are read from the database - there is no
    point loading a fifty-message thread to use the last six.
    """
    wanted = max(settings.ASK_HISTORY_TURNS, 1) * 2
    messages = load_messages(session, conversation_id, limit=wanted)

    turns: list[Turn] = []
    pending: str | None = None
    for message in messages:
        if message.role == AskRole.user:
            # Two questions in a row: the first went unanswered (the reader
            # stopped it, or the model failed). Keep the newer one.
            pending = message.content
        elif pending is not None:
            turns.append(Turn(question=pending, answer=message.content))
            pending = None
    return turns


def start_conversation(
    session: Session,
    user: User,
    *,
    question: str,
    namespace_id: uuid.UUID | None,
    document_id: uuid.UUID | None,
) -> AskConversation:
    conversation = AskConversation(
        user_id=user.id,
        title=conversation_title(question),
        namespace_id=namespace_id,
        document_id=document_id,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def append_message(
    session: Session,
    conversation: AskConversation,
    *,
    role: AskRole,
    content: str,
    citations: Sequence[AskCitation] | None = None,
    stats: dict[str, Any] | None = None,
) -> AskMessage:
    """Add one turn and move the thread to the top of the history rail."""
    message = AskMessage(
        conversation_id=conversation.id,
        seq=conversation.message_count + 1,
        role=role,
        content=content,
        citations=[_store_citation(c) for c in citations] if citations else None,
        stats=stats,
    )
    conversation.message_count += 1
    conversation.updated_at = datetime.now(UTC)
    session.add(message)
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return message


def _store_citation(citation: AskCitation) -> dict[str, Any]:
    """A citation as it is kept: the page it points at, plus a preview.

    The full excerpt is the live page and is not worth a copy - it would be
    stale as soon as somebody edits the page, and a thread of ten answers would
    carry several megabytes of duplicated content. The preview is enough to
    recognise the source when the thread is reopened; the title links to the
    page itself for the rest.
    """
    data = citation.model_dump(mode="json")
    text = citation.text or ""
    limit = settings.ASK_STORED_CITATION_CHARS
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    data["text"] = text
    return data


def prune_conversations(session: Session, user: User) -> None:
    """Keep a person's history bounded without ever asking them to tidy it.

    Oldest threads go first, and only past the cap, so nothing a person is
    still using disappears.
    """
    cap = settings.ASK_MAX_CONVERSATIONS_PER_USER
    total = session.exec(
        select(func.count())
        .select_from(AskConversation)
        .where(AskConversation.user_id == user.id)
    ).one()
    if int(total) <= cap:
        return
    stale = session.exec(
        select(col(AskConversation.id))
        .where(AskConversation.user_id == user.id)
        .order_by(col(AskConversation.updated_at))
        .limit(int(total) - cap)
    ).all()
    if not stale:
        return
    session.exec(delete(AskMessage).where(col(AskMessage.conversation_id).in_(stale)))
    session.exec(delete(AskConversation).where(col(AskConversation.id).in_(stale)))
    session.commit()


def delete_conversation(session: Session, conversation: AskConversation) -> None:
    session.exec(
        delete(AskMessage).where(col(AskMessage.conversation_id) == conversation.id)
    )
    session.delete(conversation)
    session.commit()
