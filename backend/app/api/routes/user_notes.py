"""Personal notes over HTTP.

Tagged ``user-notes`` rather than ``notes``: the generated client makes one
service class per tag, and ``NotesService`` already exists for the remarks
people leave on a page. Two routers sharing a tag would merge into one class
and collide method for method.

Every handler starts at `user_notes.owned_note` or carries
`user_notes.owned_notes(user)`. There is no role ladder to walk here, because
there are no roles: a note has exactly one reader.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlmodel import col, select

from app import crud
from app.api.deps import AuthDep, SessionDep, WriteAuth
from app.core.permissions import require_namespace
from app.models import (
    CleanupKind,
    CleanupTask,
    Message,
    Note,
    NoteCreate,
    NoteKind,
    NoteMove,
    NotePublic,
    NoteReminder,
    NoteReminderPublic,
    NoteReminderUpsert,
    NotesPublic,
    NoteTag,
    NoteTagCreate,
    NoteTagLink,
    NoteTagPublic,
    NoteTagsPublic,
    NoteTagUpdate,
    NoteUpdate,
    ReminderEnds,
    ReminderRecurrence,
    ReminderStatus,
)
from app.services import quota
from app.services import reminders as reminder_rules
from app.services import user_notes as notes_service

router = APIRouter(prefix="/notes", tags=["user-notes"])


def _now() -> datetime:
    return datetime.now(UTC)


def _set_reminder_status(
    session: SessionDep,
    note_id: uuid.UUID,
    status: ReminderStatus,
    reason: str | None,
) -> None:
    """Pause or resume a note's reminder alongside the note itself."""
    reminder = session.exec(
        select(NoteReminder).where(col(NoteReminder.note_id) == note_id)
    ).first()
    if reminder is None or reminder.status in {
        ReminderStatus.done,
        ReminderStatus.cancelled,
    }:
        return
    reminder.status = status
    reminder.last_error = reason
    session.add(reminder)


def _detail(session: SessionDep, note: Note) -> NotePublic:
    tags = notes_service.tags_for(session, [note.id]).get(note.id, [])
    names = notes_service.namespace_names(
        session, [note.namespace_id] if note.namespace_id else []
    )
    base = notes_service.summary(
        note,
        namespace_name=names.get(note.namespace_id) if note.namespace_id else None,
        tags=tags,
    )
    return NotePublic(
        **base.model_dump(),
        content_html=note.content_html,
        content_json=note.content_json,
        content_text=note.content_text,
    )


def _check_space(
    session: SessionDep, auth: AuthDep, namespace_id: uuid.UUID | None
) -> None:
    """A note may only be filed in a space its author can actually see.

    Not because the space grants any access to the note - it grants none - but
    because filing into a space you cannot see would let you learn that one
    exists by whether the call succeeded.
    """
    if namespace_id is not None:
        require_namespace(session, auth.user, namespace_id, "viewer")


# --- tags -------------------------------------------------------------------
#
# Declared before `/{note_id}` so FastAPI, which matches in declaration order,
# does not read "tags" as a note id and 422 on the uuid.


@router.get("/tags", response_model=NoteTagsPublic)
def read_tags(session: SessionDep, auth: AuthDep) -> Any:
    """Every label this person has made, alphabetically."""
    rows = session.exec(
        select(NoteTag)
        .where(col(NoteTag.user_id) == auth.user.id)
        .order_by(col(NoteTag.name_folded))
    ).all()
    return NoteTagsPublic(
        data=[NoteTagPublic(id=t.id, name=t.name, color=t.color) for t in rows],
        count=len(rows),
    )


@router.post("/tags", response_model=NoteTagPublic)
def create_tag(session: SessionDep, auth: WriteAuth, body: NoteTagCreate) -> Any:
    """Make a label, or hand back the one that already means this."""
    folded = notes_service.fold(body.name)
    if not folded:
        raise HTTPException(status_code=422, detail="A tag needs a name")
    existing = session.exec(
        select(NoteTag).where(
            col(NoteTag.user_id) == auth.user.id,
            col(NoteTag.name_folded) == folded,
        )
    ).first()
    if existing is not None:
        # Idempotent rather than a 409: typing a tag you already have is not a
        # mistake to report, it is the tag you meant.
        return NoteTagPublic(id=existing.id, name=existing.name, color=existing.color)

    tag = NoteTag(
        user_id=auth.user.id,
        name=" ".join(body.name.split()),
        name_folded=folded,
        color=body.color,
    )
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return NoteTagPublic(id=tag.id, name=tag.name, color=tag.color)


@router.patch("/tags/{tag_id}", response_model=NoteTagPublic)
def update_tag(
    session: SessionDep, auth: WriteAuth, tag_id: uuid.UUID, body: NoteTagUpdate
) -> Any:
    tag = session.get(NoteTag, tag_id)
    if tag is None or tag.user_id != auth.user.id:
        raise HTTPException(status_code=404, detail="Tag not found")
    if body.name is not None:
        folded = notes_service.fold(body.name)
        if not folded:
            raise HTTPException(status_code=422, detail="A tag needs a name")
        clash = session.exec(
            select(NoteTag).where(
                col(NoteTag.user_id) == auth.user.id,
                col(NoteTag.name_folded) == folded,
                col(NoteTag.id) != tag.id,
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail="You already have that tag")
        tag.name = " ".join(body.name.split())
        tag.name_folded = folded
    if body.color is not None:
        tag.color = body.color or None
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return NoteTagPublic(id=tag.id, name=tag.name, color=tag.color)


@router.delete("/tags/{tag_id}", response_model=Message)
def delete_tag(session: SessionDep, auth: WriteAuth, tag_id: uuid.UUID) -> Any:
    """Remove a label. The notes that carried it are untouched."""
    tag = session.get(NoteTag, tag_id)
    if tag is None or tag.user_id != auth.user.id:
        raise HTTPException(status_code=404, detail="Tag not found")
    session.delete(tag)
    session.commit()
    return Message(message="Tag deleted")


# --- search -----------------------------------------------------------------


@router.get("/search", response_model=NotesPublic)
def search_notes(
    session: SessionDep,
    auth: AuthDep,
    q: str = Query(min_length=1, max_length=1000),
    namespace_id: uuid.UUID | None = None,
    kind: NoteKind | None = None,
    include_archived: bool = True,
    limit: int = Query(default=50, le=100),
) -> Any:
    """Find your own notes, and nobody else's.

    Archived notes are included by default. Archiving means "out of my way",
    not "forgotten": the whole point of putting something away is that search
    can still get it back.

    Keyword only for now. The note is in this index the moment it is saved,
    because Postgres writes the search vector at COMMIT; meaning-based search
    joins in once the indexer is wired up and needs no change here.
    """
    match = func.websearch_to_tsquery("english", q)
    where = [
        notes_service.owned_notes(auth.user),
        col(Note.search_vector).op("@@")(match),
    ]
    if namespace_id is not None:
        require_namespace(session, auth.user, namespace_id, "viewer")
        where.append(col(Note.namespace_id) == namespace_id)
    if kind is not None:
        where.append(col(Note.kind) == kind)
    if not include_archived:
        where.append(notes_service.not_archived())

    rank = func.ts_rank_cd(col(Note.search_vector), match)
    rows = session.exec(
        select(Note)
        .where(*where)
        .order_by(rank.desc(), col(Note.updated_at).desc())
        .limit(limit)
    ).all()
    return _listing(session, rows, total=len(rows))


# --- notes ------------------------------------------------------------------


def _listing(session: SessionDep, rows: Sequence[Note], *, total: int) -> NotesPublic:
    tags = notes_service.tags_for(session, [n.id for n in rows])
    names = notes_service.namespace_names(
        session, [n.namespace_id for n in rows if n.namespace_id]
    )
    return NotesPublic(
        data=[
            notes_service.summary(
                n,
                namespace_name=names.get(n.namespace_id) if n.namespace_id else None,
                tags=tags.get(n.id, []),
            )
            for n in rows
        ],
        count=total,
    )


@router.get("/", response_model=NotesPublic)
def read_notes(
    session: SessionDep,
    auth: AuthDep,
    namespace_id: uuid.UUID | None = None,
    kind: NoteKind | None = None,
    tag_id: uuid.UUID | None = None,
    archived: bool = False,
    pinned: bool | None = None,
    skip: int = 0,
    limit: int = Query(default=50, le=100),
) -> Any:
    """This person's notes, pinned first and newest after."""
    where = [notes_service.owned_notes(auth.user)]
    if archived:
        where.append(col(Note.archived_at).is_not(None))
    else:
        where.append(notes_service.not_archived())
    if namespace_id is not None:
        where.append(col(Note.namespace_id) == namespace_id)
    if kind is not None:
        where.append(col(Note.kind) == kind)
    if pinned is not None:
        where.append(
            col(Note.pinned_at).is_not(None)
            if pinned
            else col(Note.pinned_at).is_(None)
        )

    statement = select(Note).where(*where)
    counter = select(func.count()).select_from(Note).where(*where)
    if tag_id is not None:
        link = col(NoteTagLink.note_id) == col(Note.id)
        statement = statement.join(NoteTagLink, link).where(
            col(NoteTagLink.tag_id) == tag_id
        )
        counter = counter.join(NoteTagLink, link).where(
            col(NoteTagLink.tag_id) == tag_id
        )

    total = int(session.exec(counter).one())
    rows = session.exec(
        statement.order_by(
            # Pinned first, most recently pinned at the top of those, then
            # everything else by when it was last touched.
            col(Note.pinned_at).is_(None),
            col(Note.pinned_at).desc(),
            col(Note.updated_at).desc(),
        )
        .offset(skip)
        .limit(limit)
    ).all()
    return _listing(session, rows, total=total)


@router.post("/", response_model=NotePublic)
def create_note(session: SessionDep, auth: WriteAuth, body: NoteCreate) -> Any:
    try:
        quota.ensure_note_capacity(session, auth.user.id)
    except quota.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _check_space(session, auth, body.namespace_id)

    note = Note(
        user_id=auth.user.id,
        namespace_id=body.namespace_id,
        kind=body.kind,
        color=body.color,
    )
    notes_service.apply_content(
        note,
        content=body.content,
        content_format=body.content_format,
        content_json=body.content_json,
        title=body.title,
    )
    session.add(note)
    crud.enqueue_note_embedding_job(session=session, note=note)
    session.commit()
    session.refresh(note)
    if body.tag_ids:
        notes_service.set_tags(session, note, body.tag_ids, user=auth.user)
        session.commit()
        session.refresh(note)
    return _detail(session, note)


@router.get("/{note_id}", response_model=NotePublic)
def read_note(session: SessionDep, auth: AuthDep, note_id: uuid.UUID) -> Any:
    return _detail(session, notes_service.owned_note(session, auth.user, note_id))


@router.patch("/{note_id}", response_model=NotePublic)
def update_note(
    session: SessionDep, auth: WriteAuth, note_id: uuid.UUID, body: NoteUpdate
) -> Any:
    """Save a note, refusing if somebody saved a newer one first.

    The 409 carries the version that is actually stored, which is what lets the
    editor offer "reload" or "overwrite" rather than just losing the typing.
    """
    note = notes_service.owned_note(session, auth.user, note_id)
    if body.expected_version is not None and body.expected_version != note.version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This note changed somewhere else since you opened it.",
                "current_version": note.version,
            },
        )

    changed = notes_service.apply_content(
        note,
        content=body.content,
        content_format=body.content_format,
        content_json=body.content_json,
        title=body.title,
    )
    if body.color is not None:
        note.color = body.color or None
    if body.tag_ids is not None:
        notes_service.set_tags(session, note, body.tag_ids, user=auth.user)

    if changed:
        note.version += 1
        # Only when the meaning moved. A ticked checkbox changes the HTML and
        # not a word of the text, and re-embedding for that is spend for
        # nothing.
        crud.enqueue_note_embedding_job(session=session, note=note)
    note.updated_at = _now()
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/pin", response_model=NotePublic)
def pin_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    note = notes_service.owned_note(session, auth.user, note_id)
    if note.archived_at is not None:
        raise HTTPException(
            status_code=409, detail="Restore this note before pinning it"
        )
    note.pinned_at = note.pinned_at or _now()
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/unpin", response_model=NotePublic)
def unpin_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    note = notes_service.owned_note(session, auth.user, note_id)
    note.pinned_at = None
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/archive", response_model=NotePublic)
def archive_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    """Put a note away. It stays findable by search; it leaves the list.

    Pinning is cleared, because an archived note that claims to be pinned is a
    note somebody will look for at the top of a list it is not in.
    """
    note = notes_service.owned_note(session, auth.user, note_id)
    note.archived_at = note.archived_at or _now()
    note.pinned_at = None
    # And stop nagging about it. Paused rather than deleted, so restoring the
    # note brings its reminder back rather than silently losing it.
    _set_reminder_status(
        session, note.id, ReminderStatus.paused, "the note is archived"
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/unarchive", response_model=NotePublic)
def unarchive_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    note = notes_service.owned_note(session, auth.user, note_id)
    note.archived_at = None
    _set_reminder_status(session, note.id, ReminderStatus.active, None)
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/move", response_model=NotePublic)
def move_note(
    session: SessionDep, auth: WriteAuth, note_id: uuid.UUID, body: NoteMove
) -> Any:
    """Refile a note. Null is a real destination: it means unfiled."""
    note = notes_service.owned_note(session, auth.user, note_id)
    _check_space(session, auth, body.namespace_id)
    note.namespace_id = body.namespace_id
    session.add(note)
    session.commit()
    session.refresh(note)
    return _detail(session, note)


@router.post("/{note_id}/clone", response_model=NotePublic)
def clone_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    """Copy a note. The copy is charged to whoever made it, like a page clone.

    The copy arrives neither pinned nor archived: it is new, and it should not
    turn up already put away or already at the top.
    """
    source = notes_service.owned_note(session, auth.user, note_id)
    try:
        quota.ensure_note_capacity(session, auth.user.id)
    except quota.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    clone = Note(
        user_id=auth.user.id,
        namespace_id=source.namespace_id,
        kind=source.kind,
        title=f"{source.title} (copy)" if source.title else "",
        content_html=source.content_html,
        content_json=source.content_json,
        content_text=source.content_text,
        color=source.color,
    )
    session.add(clone)
    crud.enqueue_note_embedding_job(session=session, note=clone)
    session.commit()
    session.refresh(clone)

    tags = notes_service.tags_for(session, [source.id]).get(source.id, [])
    if tags:
        notes_service.set_tags(session, clone, [t.id for t in tags], user=auth.user)
        session.commit()
        session.refresh(clone)
    return _detail(session, clone)


@router.delete("/{note_id}", response_model=Message)
def delete_note(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    """Really delete it. Archive is the reversible one; this is not.

    Deleting is also how a place is freed, which is why the archive does not
    have to expire on its own.
    """
    note = notes_service.owned_note(session, auth.user, note_id)
    # The chunks and jobs go with the row; the vectors live in Qdrant and have
    # to be swept. Archiving enqueues nothing - an archived note stays findable.
    session.add(
        CleanupTask(
            kind=CleanupKind.qdrant_note,
            payload={"note_id": str(note.id)},
        )
    )
    session.delete(note)
    session.commit()
    return Message(message="Note deleted")


# --- reminders --------------------------------------------------------------


def _reminder_public(reminder: NoteReminder) -> NoteReminderPublic:
    return NoteReminderPublic(
        id=reminder.id,
        note_id=reminder.note_id,
        next_run_at=reminder.next_run_at,
        local_time=reminder.local_time,
        timezone=reminder.timezone,
        recurrence=reminder.recurrence,
        ends=reminder.ends,
        ends_on=reminder.ends_on,
        ends_after=reminder.ends_after,
        status=reminder.status,
        sent_count=reminder.sent_count,
        last_sent_at=reminder.last_sent_at,
        last_error=reminder.last_error,
    )


@router.get("/{note_id}/reminder", response_model=NoteReminderPublic | None)
def read_reminder(session: SessionDep, auth: AuthDep, note_id: uuid.UUID) -> Any:
    note = notes_service.owned_note(session, auth.user, note_id)
    reminder = session.exec(
        select(NoteReminder).where(col(NoteReminder.note_id) == note.id)
    ).first()
    return _reminder_public(reminder) if reminder else None


@router.put("/{note_id}/reminder", response_model=NoteReminderPublic)
def set_reminder(
    session: SessionDep,
    auth: WriteAuth,
    note_id: uuid.UUID,
    body: NoteReminderUpsert,
) -> Any:
    """Set or replace this note's reminder.

    `at` is a naive local wall clock and `timezone` says which clock. An
    instant plus a zone would be ambiguous about which reading was meant, and
    that ambiguity is precisely what drifts across a daylight-saving change.
    """
    note = notes_service.owned_note(session, auth.user, note_id)
    if body.at.tzinfo is not None:
        raise HTTPException(
            status_code=422,
            detail="Send a local wall clock without an offset, and the zone it is in.",
        )
    if not reminder_rules.is_valid_timezone(body.timezone):
        raise HTTPException(status_code=422, detail="Unknown time zone")
    if body.ends == ReminderEnds.on_date and body.ends_on is None:
        raise HTTPException(status_code=422, detail="Say which date it ends on")
    if body.ends == ReminderEnds.after and body.ends_after is None:
        raise HTTPException(status_code=422, detail="Say how many times it runs")

    first = reminder_rules.instant_for(body.at.date(), body.at.time(), body.timezone)
    if body.recurrence == ReminderRecurrence.none and first <= _now():
        raise HTTPException(status_code=422, detail="That time has already passed")

    reminder = session.exec(
        select(NoteReminder).where(col(NoteReminder.note_id) == note.id)
    ).first()
    if reminder is None:
        reminder = NoteReminder(note_id=note.id, user_id=auth.user.id)

    reminder.local_time = body.at.time()
    reminder.timezone = body.timezone
    reminder.anchor_date = body.at.date()
    reminder.recurrence = body.recurrence
    reminder.ends = body.ends
    reminder.ends_on = body.ends_on
    reminder.ends_after = body.ends_after
    reminder.next_local_date = body.at.date()
    reminder.next_run_at = first
    reminder.status = ReminderStatus.active
    reminder.sent_count = 0
    reminder.attempts = 0
    reminder.last_error = None
    reminder.locked_until = None
    reminder.updated_at = _now()
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return _reminder_public(reminder)


@router.delete("/{note_id}/reminder", response_model=Message)
def cancel_reminder(session: SessionDep, auth: WriteAuth, note_id: uuid.UUID) -> Any:
    note = notes_service.owned_note(session, auth.user, note_id)
    reminder = session.exec(
        select(NoteReminder).where(col(NoteReminder.note_id) == note.id)
    ).first()
    if reminder is not None:
        session.delete(reminder)
        session.commit()
    return Message(message="Reminder removed")
