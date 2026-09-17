"""Personal notes: reading them, writing them, and who may.

Not `app/services/notes.py`, which maintains the remarks people leave on a
page. These belong to one person.

Everything here funnels through `owned_note`. There is no helper for notes in
`core/permissions.py` and that is deliberate: a function sitting beside
`accessible_documents_filter` is an invitation to reach for it, and that filter
grants access to everyone in a space. The only question a note asks is whether
the reader wrote it.

The three kinds share one `content_text` column, derived here and nowhere else.
That is what lets one search vector, one lexical source and one indexer serve
all of them, and what makes a fourth kind a branch in `derive_text` rather than
a second pipeline.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import HTTPException
from selectolax.lexbor import LexborHTMLParser
from sqlmodel import Session, col, select

from app.core.content import html_to_text, normalize_content
from app.models import (
    ContentFormat,
    Namespace,
    Note,
    NoteKind,
    NoteSummaryPublic,
    NoteTag,
    NoteTagLink,
    NoteTagPublic,
    User,
)

# What a card shows instead of mounting an editor per note.
PREVIEW_CHARS = 280


def owned_note(session: Session, user: User, note_id: uuid.UUID) -> Note:
    """This person's note, or a 404.

    404 rather than 403 for everyone else - including a superuser, and
    including somebody who administers the space the note is filed in. A 403
    would confirm that a note with this id exists, which is an oracle for
    other people's private notes and the one thing this model must not leak.
    """
    note = session.get(Note, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def owned_notes(user: User) -> Any:  # noqa: ANN401 - a SQLAlchemy predicate
    """The predicate every listing query carries. There is no other one."""
    return col(Note.user_id) == user.id


def not_archived() -> Any:  # noqa: ANN401 - a SQLAlchemy predicate
    """Notes still in the list.

    A named predicate applied at each call site rather than a base query that
    filters silently, because the interesting case is where it is *absent*:
    search deliberately sees archived notes, and a default filter with an
    `include_archived=True` escape hatch would bury that decision in a keyword
    argument. One that is visibly not there cannot be misread.
    """
    return col(Note.archived_at).is_(None)


# --- content ----------------------------------------------------------------


def checklist_counts(content_html: str) -> tuple[int, int]:
    """(done, total) for a checklist body.

    Read off the HTML rather than stored, because the editor owns the document
    and a second copy of the truth is a second thing to keep in step. A note is
    a few hundred bytes, so parsing it on write costs nothing worth measuring.
    """
    if not content_html:
        return 0, 0
    tree = LexborHTMLParser(content_html)
    items = tree.css("li[data-checked]")
    done = sum(1 for node in items if node.attributes.get("data-checked") == "true")
    return done, len(items)


def derive_text(kind: NoteKind, *, content_html: str, content_json: Any | None) -> str:
    """Whatever this note amounts to in words.

    The single place a kind turns into something indexable. A drawing has no
    words of its own yet, so it is findable by what its author called it until
    the vision pass lands and writes a description here.
    """
    if kind == NoteKind.drawing:
        caption = ""
        if isinstance(content_json, dict):
            caption = str(content_json.get("caption") or "")
        return caption.strip()
    return html_to_text(content_html).strip()


def apply_content(
    note: Note,
    *,
    content: str | None,
    content_format: ContentFormat,
    content_json: Any | None,
    title: str | None,
) -> bool:
    """Write the body onto the note. True when the meaning moved.

    The return value is what decides a version bump and a re-index. Ticking a
    checkbox changes the HTML but not a word of the text, and re-embedding a
    shopping list because somebody crossed off milk is spend for nothing.
    """
    before_title, before_text = note.title, note.content_text

    if title is not None:
        note.title = title.strip()[:300]
    if content is not None:
        html, _ = normalize_content(content, content_format)
        note.content_html = html
    if content_json is not None:
        note.content_json = content_json

    note.content_text = derive_text(
        note.kind, content_html=note.content_html, content_json=note.content_json
    )

    from app import crud  # imported here to avoid a cycle at module import

    return crud.content_changed(
        before_title, before_text, note.title, note.content_text
    )


# --- tags -------------------------------------------------------------------


def fold(name: str) -> str:
    """How two tag names are judged the same. Work and work are one tag."""
    return " ".join(name.split()).casefold()


def tags_for(
    session: Session, note_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[NoteTag]]:
    """Every note's tags in one query, so a list of fifty is not fifty queries."""
    if not note_ids:
        return {}
    rows = session.exec(
        select(NoteTagLink.note_id, NoteTag)
        .join(NoteTag, col(NoteTag.id) == col(NoteTagLink.tag_id))
        .where(col(NoteTagLink.note_id).in_(list(note_ids)))
    ).all()
    out: dict[uuid.UUID, list[NoteTag]] = {}
    for note_id, tag in rows:
        out.setdefault(note_id, []).append(tag)
    for tags in out.values():
        tags.sort(key=lambda t: t.name_folded)
    return out


def set_tags(
    session: Session, note: Note, tag_ids: Iterable[uuid.UUID], *, user: User
) -> None:
    """Replace this note's tags, ignoring any that are not this person's.

    Silently dropping a foreign id rather than refusing: the ids come from the
    caller's own interface, so one that is not theirs is a stale client rather
    than something to explain, and looking it up to say "no such tag" would
    answer whether somebody else has a tag by that id.
    """
    wanted = set(tag_ids)
    mine = set(
        session.exec(
            select(NoteTag.id).where(
                col(NoteTag.user_id) == user.id,
                col(NoteTag.id).in_(wanted or {uuid.uuid4()}),
            )
        ).all()
    )
    for link in session.exec(
        select(NoteTagLink).where(col(NoteTagLink.note_id) == note.id)
    ).all():
        session.delete(link)
    for tag_id in mine:
        session.add(NoteTagLink(note_id=note.id, tag_id=tag_id))


# --- serialisation ----------------------------------------------------------


def summary(
    note: Note,
    *,
    namespace_name: str | None = None,
    tags: Sequence[NoteTag] = (),
) -> NoteSummaryPublic:
    """A note as a list shows it: no body, and a plain-text preview.

    The preview is text rather than HTML so the board can render it without
    `dangerouslySetInnerHTML` and without mounting an editor per card.
    """
    done, total = (
        checklist_counts(note.content_html)
        if note.kind == NoteKind.checklist
        else (0, 0)
    )
    preview = note.content_text[:PREVIEW_CHARS]
    return NoteSummaryPublic(
        id=note.id,
        namespace_id=note.namespace_id,
        namespace_name=namespace_name,
        kind=note.kind,
        title=note.title,
        preview=preview,
        color=note.color,
        pinned=note.pinned_at is not None,
        archived=note.archived_at is not None,
        checklist_done=done,
        checklist_total=total,
        tags=[NoteTagPublic(id=t.id, name=t.name, color=t.color) for t in tags],
        version=note.version,
        created_at=note.created_at,
        updated_at=note.updated_at,
        embedding_status=note.embedding_status,
        chunk_count=note.chunk_count,
    )


def namespace_names(
    session: Session, namespace_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Space names for a page of notes, in one query."""
    wanted = {n for n in namespace_ids if n is not None}
    if not wanted:
        return {}
    rows = session.exec(
        select(Namespace.id, Namespace.name).where(col(Namespace.id).in_(wanted))
    ).all()
    return {row[0]: row[1] for row in rows}
