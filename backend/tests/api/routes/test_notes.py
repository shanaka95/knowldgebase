"""Notes on a page: who may write them, and whether they can be found again.

The claim worth testing hardest is the second one. A note that is stored but
not searchable is a note nobody will read again, and that failure is silent -
everything looks right until somebody searches for what they wrote.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Document, DocumentNote, User
from app.services import notes as notes_service
from tests.utils.kb import (
    API,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)


def _notes_url(document_id: uuid.UUID) -> str:
    return f"{API}/documents/{document_id}/notes/"


def _owner(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    user, password = create_user_with_password(db)
    return user, login(client, user, password)


def _page(db: Session, owner: User) -> Document:
    ns = create_namespace(db, owner)
    return create_document(db, ns, owner, title=f"Invoice {uuid.uuid4().hex[:6]}")


# ------------------------------------------------------------------- writing


def test_a_note_can_be_added_and_read_back(client: TestClient, db: Session) -> None:
    owner, headers = _owner(client, db)
    document = _page(db, owner)

    created = client.post(
        _notes_url(document.id),
        headers=headers,
        json={"body": "Paid in March; this copy is the disputed one."},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["body"].startswith("Paid in March")
    assert body["author"]["email"]
    assert body["can_edit"] is True and body["can_delete"] is True

    listed = client.get(_notes_url(document.id), headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1


def test_an_empty_note_is_refused(client: TestClient, db: Session) -> None:
    owner, headers = _owner(client, db)
    document = _page(db, owner)
    r = client.post(_notes_url(document.id), headers=headers, json={"body": "   "})
    assert r.status_code == 422


def test_a_note_can_be_left_when_a_page_is_written(
    client: TestClient, db: Session
) -> None:
    """One call, so an agent writing through the API need not make two."""
    owner, headers = _owner(client, db)
    ns = create_namespace(db, owner)
    created = client.post(
        f"{API}/documents/",
        headers=headers,
        json={
            "namespace_id": str(ns.id),
            "title": f"With a note {uuid.uuid4().hex[:6]}",
            "content": "<p>Body</p>",
            "note": "Superseded by the 2027 revision.",
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["note_count"] == 1

    document_id = uuid.UUID(created.json()["id"])
    listed = client.get(_notes_url(document_id), headers=headers)
    assert listed.json()["data"][0]["body"] == "Superseded by the 2027 revision."


# ------------------------------------------------------------------- finding


def test_a_note_reaches_the_page_s_search_vector(
    client: TestClient, db: Session
) -> None:
    """The claim the whole design rests on: a note is findable by its words.

    Asserted through the search endpoint rather than by inspecting the column,
    because the generated column is the part that can silently not be updated.
    """
    owner, headers = _owner(client, db)
    document = _page(db, owner)
    sentinel = f"zarquon{uuid.uuid4().hex[:6]}"
    client.post(
        _notes_url(document.id),
        headers=headers,
        json={"body": f"Filed under {sentinel} by the finance team."},
    )

    found = client.get(f"{API}/search/", headers=headers, params={"q": sentinel})
    assert found.status_code == 200, found.text
    assert str(document.id) in {hit["document_id"] for hit in found.json()["data"]}


def test_removing_a_note_removes_it_from_search(
    client: TestClient, db: Session
) -> None:
    owner, headers = _owner(client, db)
    document = _page(db, owner)
    sentinel = f"zarquon{uuid.uuid4().hex[:6]}"
    note = client.post(
        _notes_url(document.id),
        headers=headers,
        json={"body": sentinel},
    ).json()

    gone = client.delete(f"{_notes_url(document.id)}{note['id']}", headers=headers)
    assert gone.status_code == 200, gone.text

    found = client.get(f"{API}/search/", headers=headers, params={"q": sentinel})
    assert str(document.id) not in {hit["document_id"] for hit in found.json()["data"]}


def test_the_indexed_text_marks_where_the_document_ends(db: Session) -> None:
    """A model reading the page has to be able to tell the two apart."""
    notes = [
        DocumentNote(document_id=uuid.uuid4(), body="First"),
        DocumentNote(document_id=uuid.uuid4(), body="Second"),
    ]
    text = notes_service.notes_text(notes)
    assert text.startswith(notes_service.HEADING)
    assert "First" in text and "Second" in text
    # Said once, not per note: repeating it would dilute both the keyword
    # weights and the embedding.
    assert text.count(notes_service.HEADING) == 1
    assert notes_service.notes_text([]) == ""


# --------------------------------------------------------------- permissions


def test_a_reader_may_add_a_note_without_being_able_to_edit_the_page(
    client: TestClient, db: Session
) -> None:
    """The deliberate one: the person with something to add often cannot edit."""
    owner, owner_headers = _owner(client, db)
    document = _page(db, owner)

    reader, reader_pw = create_user_with_password(db)
    shared = client.post(
        f"{API}/documents/{document.id}/shares",
        headers=owner_headers,
        json={"email": reader.email, "role": "viewer"},
    )
    assert shared.status_code in (200, 201), shared.text
    reader_headers = login(client, reader, reader_pw)

    added = client.post(
        _notes_url(document.id),
        headers=reader_headers,
        json={"body": "I am the one who received this."},
    )
    assert added.status_code == 201, added.text
    # They may not edit the page itself, which is the whole point.
    refused = client.put(
        f"{API}/documents/{document.id}",
        headers=reader_headers,
        json={"title": "Renamed"},
    )
    assert refused.status_code == 403


def test_only_the_author_may_change_a_note(client: TestClient, db: Session) -> None:
    owner, owner_headers = _owner(client, db)
    document = _page(db, owner)

    editor, editor_pw = create_user_with_password(db)
    client.post(
        f"{API}/documents/{document.id}/shares",
        headers=owner_headers,
        json={"email": editor.email, "role": "editor"},
    )
    editor_headers = login(client, editor, editor_pw)

    note = client.post(
        _notes_url(document.id), headers=owner_headers, json={"body": "Mine"}
    ).json()

    # An editor of the page still may not put words in somebody's mouth...
    edited = client.patch(
        f"{_notes_url(document.id)}{note['id']}",
        headers=editor_headers,
        json={"body": "Not mine"},
    )
    assert edited.status_code == 403

    # ...but may remove something that should not be there.
    removed = client.delete(
        f"{_notes_url(document.id)}{note['id']}", headers=editor_headers
    )
    assert removed.status_code == 200, removed.text


def test_a_note_cannot_be_reached_through_another_page(
    client: TestClient, db: Session
) -> None:
    """A note id from one page must not be editable via a page you can read."""
    owner, headers = _owner(client, db)
    one = _page(db, owner)
    two = _page(db, owner)
    note = client.post(_notes_url(one.id), headers=headers, json={"body": "One"}).json()

    r = client.patch(
        f"{_notes_url(two.id)}{note['id']}",
        headers=headers,
        json={"body": "Two"},
    )
    assert r.status_code == 404


def test_notes_are_invisible_to_somebody_who_cannot_read_the_page(
    client: TestClient, db: Session
) -> None:
    owner, owner_headers = _owner(client, db)
    document = _page(db, owner)
    client.post(_notes_url(document.id), headers=owner_headers, json={"body": "Secret"})

    stranger, stranger_pw = create_user_with_password(db)
    stranger_headers = login(client, stranger, stranger_pw)
    r = client.get(_notes_url(document.id), headers=stranger_headers)
    assert r.status_code == 404, "not 403 - an invisible page is reported as missing"


# ---------------------------------------------------------------- lifecycle


def test_deleting_a_page_takes_its_notes_with_it(
    client: TestClient, db: Session
) -> None:
    owner, headers = _owner(client, db)
    document = _page(db, owner)
    client.post(_notes_url(document.id), headers=headers, json={"body": "Bye"})
    document_id = document.id

    removed = client.delete(f"{API}/documents/{document_id}", headers=headers)
    assert removed.status_code == 200, removed.text

    db.expire_all()
    remaining = db.exec(
        select(DocumentNote).where(DocumentNote.document_id == document_id)
    ).all()
    assert remaining == []


def test_a_copy_carries_the_notes_over(client: TestClient, db: Session) -> None:
    """Without them a copy loses the part explaining why it was worth copying."""
    owner, headers = _owner(client, db)
    document = _page(db, owner)
    client.post(
        _notes_url(document.id),
        headers=headers,
        json={"body": "Check the totals on page 3."},
    )

    copied = client.post(
        f"{API}/documents/{document.id}/clone",
        headers=headers,
        json={"namespace_id": str(document.namespace_id)},
    )
    assert copied.status_code in (200, 201), copied.text
    clone_id = uuid.UUID(copied.json()["id"])

    listed = client.get(_notes_url(clone_id), headers=headers).json()
    assert listed["count"] == 1
    assert listed["data"][0]["body"] == "Check the totals on page 3."
