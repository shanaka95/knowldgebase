"""Notes on a page: what somebody added that the document does not say.

A scanned invoice cannot tell you it was already disputed, and a policy PDF
cannot tell you which team it actually applies to. Notes are where that goes.

The design question is whether a note is *content* or *about* content, and the
answer here is both, deliberately:

* **About**, for reading. A note has an author and a time and is rendered as
  somebody's addition. A scan should still read as the scan.
* **Content**, for finding. A note is indexed with the page and answered from
  with it. A note nobody can find by searching for it is a note nobody will
  read again, and "why did we keep this?" is exactly the kind of question
  people search for.

That second half is what this module exists to keep true. `Document.notes_text`
is a denormalised copy of every note on the page, maintained here and nowhere
else, because a Postgres generated column may only reference its own row - so
the page's search vector cannot join to the notes table, and something has to
put the text where it can see it.

Changing a note re-indexes the page. Embedding is not free, which is why this
is one enqueue after the write rather than one per note.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, delete, func, select

from app import crud
from app.models import Document, DocumentNote, User, UserRef

# How notes are run together for indexing. A blank line, so the chunker sees
# separate thoughts rather than one run-on paragraph.
JOINER = "\n\n"

# What the stored text is prefixed with, so a model reading the page knows the
# difference between what the document says and what somebody said about it.
HEADING = "Notes added by readers:"


def list_notes(session: Session, document_id: uuid.UUID) -> list[DocumentNote]:
    """Every note on a page, oldest first - the order they were written in."""
    return list(
        session.exec(
            select(DocumentNote)
            .where(DocumentNote.document_id == document_id)
            .order_by(col(DocumentNote.created_at))
        ).all()
    )


def notes_text(notes: list[DocumentNote]) -> str:
    """The text the index and the answering model see.

    Prefixed once rather than per note: the heading is there to mark the
    boundary between the document and what was added to it, and repeating it
    would only dilute both the keyword weights and the embedding.
    """
    bodies = [note.body.strip() for note in notes if note.body.strip()]
    if not bodies:
        return ""
    return HEADING + "\n" + JOINER.join(bodies)


def refresh(session: Session, document: Document, *, reindex: bool = True) -> None:
    """Put the page's notes back where search can see them.

    Called after every write. The read is cheap - notes are few and indexed by
    page - and recomputing beats maintaining an incremental sum that can drift.
    """
    document.notes_text = notes_text(list_notes(session, document.id))
    session.add(document)
    if reindex:
        # The page's meaning has changed for anybody searching it, so the
        # vectors have to be redone. One enqueue for the write, not one per
        # note: embedding is the expensive half of this.
        crud.enqueue_embedding_job(session=session, document=document)


def add(
    session: Session,
    document: Document,
    *,
    body: str,
    author_id: uuid.UUID | None,
    reindex: bool = True,
) -> DocumentNote:
    note = DocumentNote(
        document_id=document.id, body=body.strip(), created_by=author_id
    )
    session.add(note)
    session.flush()
    refresh(session, document, reindex=reindex)
    return note


def note_count(session: Session, document_id: uuid.UUID) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(DocumentNote)
            .where(DocumentNote.document_id == document_id)
        ).one()
    )


def counts_for(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many notes each of these pages has, in one query.

    A list of pages showing a note count would otherwise be a query per row.
    """
    if not document_ids:
        return {}
    counts = dict.fromkeys(document_ids, 0)
    rows = session.exec(
        select(col(DocumentNote.document_id), func.count())
        .where(col(DocumentNote.document_id).in_(document_ids))
        .group_by(col(DocumentNote.document_id))
    ).all()
    for document_id, count in rows:
        counts[document_id] = int(count)
    return counts


def copy_to(
    session: Session, source_id: uuid.UUID, target: Document, *, author_id: uuid.UUID
) -> None:
    """Carry a page's notes onto a copy of it.

    A copy that lost the notes would lose the part explaining why the page was
    worth copying. Attributed to whoever made the copy rather than the original
    author, because on this page it is their note now.
    """
    for note in list_notes(session, source_id):
        session.add(
            DocumentNote(document_id=target.id, body=note.body, created_by=author_id)
        )
    session.flush()
    refresh(session, target, reindex=False)


def delete_all(session: Session, document_id: uuid.UUID) -> None:
    session.exec(
        delete(DocumentNote).where(col(DocumentNote.document_id) == document_id)
    )


def authors(session: Session, notes: list[DocumentNote]) -> dict[uuid.UUID, UserRef]:
    """Who wrote each note, in one query rather than one per note."""
    ids = {note.created_by for note in notes if note.created_by is not None}
    if not ids:
        return {}
    rows = session.exec(select(User).where(col(User.id).in_(list(ids)))).all()
    return {
        user.id: UserRef(id=user.id, email=user.email, full_name=user.full_name)
        for user in rows
    }
