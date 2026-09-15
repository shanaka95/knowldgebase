"""Reading and writing the notes on a page.

Who may do what, and why:

* **Reading** follows the page. If you can read the page you can read what
  people said about it - a note whose context you cannot see is useless anyway.
* **Writing** needs only *viewer*. This is the deliberate one. A note is the
  thing you want from somebody who cannot edit the document: the person who
  received the invoice, not the person who filed it. Requiring edit rights
  would mean the people with the most to add are the ones who cannot.
* **Editing** belongs to whoever wrote it, and nobody else. Putting words in
  someone's mouth is worse than not being able to fix a typo.
* **Deleting** belongs to the author or to anybody who could edit the page,
  because an editor has to be able to clear something that should not be there.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep, WriteAuth
from app.core.permissions import has_min_role, require_document
from app.models import (
    DocumentNote,
    DocumentNoteCreate,
    DocumentNotePublic,
    DocumentNotesPublic,
    DocumentNoteUpdate,
    Message,
    get_datetime_utc,
)
from app.services import notes as notes_service

router = APIRouter(prefix="/documents/{document_id}/notes", tags=["notes"])


def _to_public(
    note: DocumentNote,
    *,
    authors: dict[uuid.UUID, Any],
    viewer_id: uuid.UUID,
    can_edit_page: bool,
) -> DocumentNotePublic:
    mine = note.created_by == viewer_id
    return DocumentNotePublic(
        id=note.id,
        document_id=note.document_id,
        body=note.body,
        created_by=note.created_by,
        author=authors.get(note.created_by) if note.created_by else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
        can_edit=mine,
        can_delete=mine or can_edit_page,
    )


@router.get("/", response_model=DocumentNotesPublic)
def read_notes(session: SessionDep, auth: WriteAuth, document_id: uuid.UUID) -> Any:
    """Every note on a page, oldest first."""
    document, role = require_document(session, auth.user, document_id, "viewer")
    rows = notes_service.list_notes(session, document.id)
    authors = notes_service.authors(session, rows)
    can_edit_page = has_min_role(role, "editor")
    data = [
        _to_public(
            note,
            authors=authors,
            viewer_id=auth.user.id,
            can_edit_page=can_edit_page,
        )
        for note in rows
    ]
    return DocumentNotesPublic(data=data, count=len(data))


@router.post("/", response_model=DocumentNotePublic, status_code=201)
def create_note(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    body: DocumentNoteCreate,
) -> Any:
    """Add a note. Viewer is enough, on purpose - see the module docstring."""
    document, role = require_document(session, auth.user, document_id, "viewer")
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write something first")

    note = notes_service.add(session, document, body=text, author_id=auth.user.id)
    session.commit()
    session.refresh(note)
    return _to_public(
        note,
        authors=notes_service.authors(session, [note]),
        viewer_id=auth.user.id,
        can_edit_page=has_min_role(role, "editor"),
    )


@router.patch("/{note_id}", response_model=DocumentNotePublic)
def update_note(
    session: SessionDep,
    auth: WriteAuth,
    document_id: uuid.UUID,
    note_id: uuid.UUID,
    body: DocumentNoteUpdate,
) -> Any:
    """Change a note you wrote."""
    document, role = require_document(session, auth.user, document_id, "viewer")
    note = _note_on(session, document_id, note_id)
    if note.created_by != auth.user.id:
        raise HTTPException(
            status_code=403, detail="Only the person who wrote a note may change it"
        )

    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write something first")
    note.body = text
    note.updated_at = get_datetime_utc()
    session.add(note)
    notes_service.refresh(session, document)
    session.commit()
    session.refresh(note)
    return _to_public(
        note,
        authors=notes_service.authors(session, [note]),
        viewer_id=auth.user.id,
        can_edit_page=has_min_role(role, "editor"),
    )


@router.delete("/{note_id}", response_model=Message)
def delete_note(
    session: SessionDep, auth: WriteAuth, document_id: uuid.UUID, note_id: uuid.UUID
) -> Any:
    """Remove a note you wrote, or any note if you can edit the page."""
    document, role = require_document(session, auth.user, document_id, "viewer")
    note = _note_on(session, document_id, note_id)
    if note.created_by != auth.user.id and not has_min_role(role, "editor"):
        raise HTTPException(
            status_code=403, detail="Not enough permissions to remove this note"
        )

    session.delete(note)
    session.flush()
    notes_service.refresh(session, document)
    session.commit()
    return Message(message="Note deleted")


def _note_on(
    session: SessionDep, document_id: uuid.UUID, note_id: uuid.UUID
) -> DocumentNote:
    """The note, if it is on the page the caller named.

    Checked rather than assumed: a note id from another page would otherwise be
    editable by anyone who could read this one.
    """
    note = session.get(DocumentNote, note_id)
    if note is None or note.document_id != document_id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note
