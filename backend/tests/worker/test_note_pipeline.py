"""Indexing a note: what gets written, and what must never be.

The payload assertions here are the other half of the privacy story. The API
tests prove nobody else's query returns your note; these prove the points
carry the fields those queries filter on, because a point written without an
`owner_id` would be invisible to the filter and therefore invisible to you.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import EmbeddingKind, JobStatus, NoteEmbeddingJob
from app.services.vectors import InMemoryVectorStore
from app.worker import queue
from app.worker.note_pipeline import build_note_points, run_note_job
from app.worker.pipeline import PipelineDeps


class StubEmbedder:
    """Returns a distinct unit vector per input, so order is checkable."""

    batch_size = 16

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, meter=None):  # type: ignore[no-untyped-def]
        self.calls.append(list(texts))
        return [[1.0, float(i)] for i, _ in enumerate(texts)]

    async def embed_batch(self, texts, *, meter=None):  # type: ignore[no-untyped-def]
        return await self.embed(texts, meter=meter)


def snapshot(**overrides) -> queue.NoteSnapshot:  # type: ignore[no-untyped-def]
    base = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "namespace_id": uuid.uuid4(),
        "kind": "text",
        "title": "Rent",
        "content_text": "The disputed figure",
        "version": 3,
    }
    base.update(overrides)
    return queue.NoteSnapshot(**base)  # type: ignore[arg-type]


def claim_mine(note_id: uuid.UUID) -> NoteEmbeddingJob:
    """Claim this note's job specifically.

    A generous limit rather than a handful: other tests in the same session
    leave their own queued note jobs behind, and a small limit claims theirs
    instead of ours purely by ordering.
    """
    for job in queue.claim_note_jobs("test-worker", 500):
        if job.note_id == note_id:
            return job
    raise AssertionError(f"no queued job for note {note_id}")


def test_every_point_says_whose_it_is() -> None:
    note = snapshot()
    points = build_note_points(
        note=note,
        doc_version=3,
        vectors=[[1.0, 0.0]],
        texts=["Rent\n\nThe disputed figure"],
        chunks=[],
    )

    assert len(points) == 1
    payload = points[0].payload
    assert payload["entity_type"] == "note"
    assert payload["owner_id"] == str(note.user_id)
    assert payload["note_id"] == str(note.id)
    assert payload["kind"] == str(EmbeddingKind.document)
    # Never a document id: that is what keeps `delete_document` and the
    # document-id scope filter from reaching a note at all.
    assert "document_id" not in payload


def test_an_unfiled_note_has_no_namespace_key() -> None:
    """Omitted, not null.

    Qdrant treats a missing key as non-matching, which is exactly what an
    unfiled note should be to a space-scoped search. A null would match a
    `MatchAny` on some drivers and leak it into the wrong scope.
    """
    points = build_note_points(
        note=snapshot(namespace_id=None),
        doc_version=1,
        vectors=[[1.0, 0.0]],
        texts=["Rent"],
        chunks=[],
    )
    assert "namespace_id" not in points[0].payload


@pytest.mark.anyio
async def test_a_note_and_a_document_with_the_same_id_do_not_collide() -> None:
    """Point ids are namespaced, and the delete verbs do not cross over."""
    store = InMemoryVectorStore()
    shared = uuid.uuid4()
    note = snapshot(id=shared)

    await store.upsert(
        build_note_points(
            note=note,
            doc_version=1,
            vectors=[[1.0, 0.0]],
            texts=["Rent"],
            chunks=[],
        )
    )
    assert await store.count_note(shared) == 1

    # The document verb, against the same uuid, must do nothing.
    await store.delete_document(shared)
    assert await store.count_note(shared) == 1

    await store.delete_note(shared)
    assert await store.count_note(shared) == 0


@pytest.mark.anyio
async def test_one_persons_notes_are_swept_without_touching_anothers() -> None:
    store = InMemoryVectorStore()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    for owner in (mine, theirs):
        await store.upsert(
            build_note_points(
                note=snapshot(user_id=owner),
                doc_version=1,
                vectors=[[1.0, 0.0]],
                texts=["Rent"],
                chunks=[],
            )
        )

    await store.delete_notes_of_owner(mine)

    remaining = [p.payload["owner_id"] for p in store.points.values()]
    assert remaining == [str(theirs)]


@pytest.mark.anyio
async def test_a_search_for_my_notes_never_returns_anothers() -> None:
    """The fake has to enforce this, or every privacy test passes vacuously."""
    store = InMemoryVectorStore()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    for owner in (mine, theirs):
        await store.upsert(
            build_note_points(
                note=snapshot(user_id=owner),
                doc_version=1,
                vectors=[[1.0, 0.0]],
                texts=["Rent"],
                chunks=[],
            )
        )

    found = await store.search_dense_notes([1.0, 0.0], owner_id=str(mine))

    assert [hit.payload["owner_id"] for hit in found] == [str(mine)]


@pytest.mark.anyio
async def test_the_note_search_cannot_be_called_without_an_owner() -> None:
    """`owner_id` is keyword-only with no default, so this is a TypeError."""
    store = InMemoryVectorStore()
    with pytest.raises(TypeError):
        await store.search_dense_notes([1.0, 0.0])  # type: ignore[call-arg]


@pytest.mark.anyio
async def test_indexing_a_note_writes_its_points_and_marks_it_ready(
    db,  # noqa: ANN001 - the session fixture
) -> None:
    """End to end against the real queue functions and the fake store."""
    from app import crud
    from app.models import EmbeddingStatus, Note, User, UserCreate

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"pipeline-{uuid.uuid4().hex[:8]}@example.com", password="x" * 12
        ),
    )
    note = Note(
        user_id=user.id,
        title="Rent",
        content_html="<p>The disputed figure</p>",
        content_text="The disputed figure",
    )
    db.add(note)
    # force=True skips the debounce, so the job is due immediately. Without
    # it the claim below correctly returns nothing for three seconds.
    job = crud.enqueue_note_embedding_job(session=db, note=note, force=True)
    db.commit()
    db.refresh(note)

    store = InMemoryVectorStore()
    deps = PipelineDeps(
        llm=None,  # type: ignore[arg-type] - a note never calls the LLM
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        vectors=store,
        shutting_down=lambda: False,
    )

    # The job has to be claimed before the pipeline will run it: `checkpoint`
    # refuses anything not in `running`, which is what stops a cancelled job.
    mine = claim_mine(note.id)
    assert mine.id == job.id

    outcome = await run_note_job(mine, deps)

    assert outcome == JobStatus.succeeded
    assert await store.count_note(note.id) == 1
    payload = next(iter(store.points.values())).payload
    assert payload["owner_id"] == str(user.id)

    db.refresh(note)
    assert note.embedding_status == EmbeddingStatus.ready
    assert note.embedding_version == note.version

    db.delete(note)
    db.delete(db.get(User, user.id))
    db.commit()


@pytest.mark.anyio
async def test_an_empty_note_is_finished_rather_than_retried_for_ever(
    db,  # noqa: ANN001
) -> None:
    """Somebody opened a note and has not written yet. That is a real state.

    Without this it stays behind for ever, and the self-healing sweep re-queues
    it on every tick.
    """
    from app import crud
    from app.models import EmbeddingStatus, Note, User, UserCreate

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"empty-{uuid.uuid4().hex[:8]}@example.com", password="x" * 12
        ),
    )
    note = Note(user_id=user.id, title="", content_html="", content_text="")
    db.add(note)
    crud.enqueue_note_embedding_job(session=db, note=note, force=True)
    db.commit()

    store = InMemoryVectorStore()
    deps = PipelineDeps(
        llm=None,  # type: ignore[arg-type]
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        vectors=store,
        shutting_down=lambda: False,
    )
    assert await run_note_job(claim_mine(note.id), deps) == JobStatus.succeeded
    assert await store.count_note(note.id) == 0

    db.refresh(note)
    assert note.embedding_status == EmbeddingStatus.ready

    db.delete(note)
    db.delete(db.get(User, user.id))
    db.commit()


def test_a_note_edited_mid_index_supersedes_the_run(db) -> None:  # noqa: ANN001
    """Two enqueues for one note coalesce rather than racing each other."""
    from app import crud
    from app.models import Note, User, UserCreate

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"super-{uuid.uuid4().hex[:8]}@example.com", password="x" * 12
        ),
    )
    note = Note(user_id=user.id, title="One", content_text="One")
    db.add(note)
    first = crud.enqueue_note_embedding_job(session=db, note=note)
    db.commit()

    note.version += 1
    second = crud.enqueue_note_embedding_job(session=db, note=note)
    db.commit()

    assert second.id == first.id, "a queued job is reused, not duplicated"
    assert second.doc_version == note.version

    live = db.exec(
        __import__("sqlmodel")
        .select(NoteEmbeddingJob)
        .where(NoteEmbeddingJob.note_id == note.id)
    ).all()
    assert len(live) == 1

    db.delete(note)
    db.delete(db.get(User, user.id))
    db.commit()


@pytest.mark.anyio
async def test_a_drawing_is_indexed_by_what_is_in_it(db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The vision pass, which is the only thing that makes a sketch findable.

    A drawing carries no words. Without this it is findable by whatever its
    author typed in the title box, which for most sketches is nothing at all.
    """
    from app import crud
    from app.models import Note, NoteAsset, NoteKind, User, UserCreate
    from app.worker import note_pipeline

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sketch-{uuid.uuid4().hex[:8]}@example.com", password="x" * 12
        ),
    )
    note = Note(
        user_id=user.id,
        kind=NoteKind.drawing,
        title="Kitchen",
        content_json={"caption": "Kitchen", "strokes": []},
        content_text="Kitchen",
    )
    db.add(note)
    db.add(
        NoteAsset(
            note_id=note.id,
            user_id=user.id,
            object_key=f"notes/{user.id}/{note.id}/pic.png",
            content_type="image/png",
            size=8,
        )
    )
    crud.enqueue_note_embedding_job(session=db, note=note, force=True)
    db.commit()
    db.refresh(note)

    class OneObject:
        size = 8
        stream = iter([b"\x89PNG\r\n\x1a\n"])

        def close(self) -> None:
            pass

    class Storage:
        def open(self, key: str):  # type: ignore[no-untyped-def]
            assert key.startswith("notes/"), "read from the shared prefix"
            return OneObject()

    seen: list[bytes] = []

    async def fake_describe(image, **_):  # type: ignore[no-untyped-def]
        seen.append(image)
        return "A floor plan of a kitchen. Labels: sink, fridge, worktop."

    monkeypatch.setattr(note_pipeline, "describe_drawing", fake_describe)

    embedder = StubEmbedder()
    deps = PipelineDeps(
        llm=None,  # type: ignore[arg-type]
        embedder=embedder,  # type: ignore[arg-type]
        vectors=InMemoryVectorStore(),
        storage=Storage(),  # type: ignore[arg-type]
        shutting_down=lambda: False,
    )

    outcome = await run_note_job(claim_mine(note.id), deps)
    assert outcome == JobStatus.succeeded
    assert seen, "the picture was never looked at"

    # The words are what was embedded, not just the title.
    embedded = "\n".join(embedder.calls[0])
    assert "worktop" in embedded
    assert "Kitchen" in embedded

    # And they are on the note, which is what the keyword index reads.
    db.refresh(note)
    assert "worktop" in note.content_text
    # Written without bumping the version: otherwise the description would
    # enqueue a job that would describe it again, for ever.
    assert note.version == 1

    db.delete(note)
    db.delete(db.get(User, user.id))
    db.commit()


@pytest.mark.anyio
async def test_a_drawing_indexes_anyway_when_nobody_can_look_at_it(db) -> None:  # type: ignore[no-untyped-def]
    """No storage, no vision model, no picture yet: still a note, still indexed.

    A description is an improvement to a drawing. An improvement that fails is
    not a reason to leave the note unfindable by the title it does have.
    """
    from app import crud
    from app.models import EmbeddingStatus, Note, NoteKind, User, UserCreate

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"nosketch-{uuid.uuid4().hex[:8]}@example.com", password="x" * 12
        ),
    )
    note = Note(
        user_id=user.id,
        kind=NoteKind.drawing,
        title="Wiring",
        content_json={"caption": "Wiring"},
        content_text="Wiring",
    )
    db.add(note)
    crud.enqueue_note_embedding_job(session=db, note=note, force=True)
    db.commit()
    db.refresh(note)

    store = InMemoryVectorStore()
    deps = PipelineDeps(
        llm=None,  # type: ignore[arg-type]
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        vectors=store,
        storage=None,
        shutting_down=lambda: False,
    )

    assert await run_note_job(claim_mine(note.id), deps) == JobStatus.succeeded
    assert await store.count_note(note.id) == 1
    db.refresh(note)
    assert note.embedding_status == EmbeddingStatus.ready

    db.delete(note)
    db.delete(db.get(User, user.id))
    db.commit()
