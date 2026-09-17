"""A note belongs to one person. These tests are the reason to believe that.

The rest of the notes tests ask whether the feature works. These ask whether
anybody else can reach one, and the answer has to be no for every verb, every
credential, and every route that reads note text - including the ones that do
not look like note routes at all, which is where a leak would actually happen.

The fixture is deliberately the hardest case: the victim's note is filed in a
space the *other* person owns. Owning the space is the strongest claim anyone
but the author can have, and it is worth nothing here. If a permission check
ever gets swapped for `accessible_documents_filter`, this is what fails.

404, never 403. A 403 confirms that a note with this id exists, which turns
every endpoint into an oracle for other people's private notes.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import NamespaceRole
from tests.utils.kb import (
    API,
    add_member,
    create_namespace,
    create_user_with_password,
    login,
)

# A word that appears nowhere else in the corpus, so finding it anywhere is
# proof the note leaked rather than a coincidence of ranking.
NONCE = "pomegranate-ledger-7719"


@pytest.fixture
def world(client: TestClient, db: Session) -> dict[str, Any]:
    """A private note, filed in a space belonging to somebody else."""
    victim, victim_password = create_user_with_password(db)
    victim_headers = login(client, victim, victim_password)

    landlord, landlord_password = create_user_with_password(db)
    landlord_headers = login(client, landlord, landlord_password)

    member, member_password = create_user_with_password(db)
    member_headers = login(client, member, member_password)

    # The landlord's space. The victim and a third person are both in it, so
    # everyone involved has a genuine claim on the *space* and none on the note.
    space = create_namespace(db, landlord, "Shared space")
    add_member(db, space, victim, NamespaceRole.editor)
    add_member(db, space, member, NamespaceRole.viewer)

    created = client.post(
        f"{API}/notes/",
        headers=victim_headers,
        json={
            "namespace_id": str(space.id),
            "title": "Rent",
            "content": f"<p>{NONCE} is the disputed figure.</p>",
        },
    )
    assert created.status_code == 200, created.text
    note = created.json()

    return {
        "note_id": note["id"],
        "space_id": str(space.id),
        "victim": victim_headers,
        "landlord": landlord_headers,
        "member": member_headers,
    }


def strangers(world: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """Everyone who is not the author, named so a failure says who got in."""
    return [
        ("the space's owner", world["landlord"]),
        ("a member of the space", world["member"]),
    ]


# --- the note's own routes --------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("patch", "", {"title": "Mine now"}),
        ("delete", "", None),
        ("post", "/pin", None),
        ("post", "/unpin", None),
        ("post", "/archive", None),
        ("post", "/unarchive", None),
        ("post", "/move", {"namespace_id": None}),
        ("post", "/clone", None),
    ],
)
def test_nobody_else_can_touch_a_note(
    client: TestClient,
    world: dict[str, Any],
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    """Every verb, for everyone who is not the author.

    Parameterised over the verb list on purpose: a route added later without a
    line here shows up as a missing parameter rather than as silence.
    """
    url = f"{API}/notes/{world['note_id']}{suffix}"
    for who, headers in strangers(world):
        call = getattr(client, method)
        response = call(url, headers=headers, **({"json": body} if body else {}))
        assert response.status_code == 404, (
            f"{who} reached {method.upper()} {suffix or '/'} ({response.status_code})"
        )


def test_the_author_can_do_all_of_that(
    client: TestClient, world: dict[str, Any]
) -> None:
    """The mirror image, so the tests above prove scoping and not a broken feature."""
    url = f"{API}/notes/{world['note_id']}"
    assert client.get(url, headers=world["victim"]).status_code == 200
    assert client.post(f"{url}/pin", headers=world["victim"]).status_code == 200
    assert client.post(f"{url}/archive", headers=world["victim"]).status_code == 200
    assert client.post(f"{url}/unarchive", headers=world["victim"]).status_code == 200


# --- listing and search -----------------------------------------------------


def test_the_list_shows_only_your_own(
    client: TestClient, world: dict[str, Any]
) -> None:
    """Even when the note is filed in a space you own."""
    for who, headers in strangers(world):
        listed = client.get(
            f"{API}/notes/", headers=headers, params={"namespace_id": world["space_id"]}
        )
        assert listed.status_code == 200, listed.text
        ids = [row["id"] for row in listed.json()["data"]]
        assert world["note_id"] not in ids, f"{who} saw it in the list"


def test_search_does_not_reach_another_persons_note(
    client: TestClient, world: dict[str, Any]
) -> None:
    """The one that catches a missing `user_id` in the lexical source.

    This runs against Postgres full text alone - no vectors are involved yet -
    which is precisely where a forgotten owner filter would hide.
    """
    for who, headers in strangers(world):
        found = client.get(f"{API}/notes/search", headers=headers, params={"q": NONCE})
        assert found.status_code == 200, found.text
        assert found.json()["count"] == 0, f"{who} found it by searching"
        assert NONCE not in found.text

    mine = client.get(
        f"{API}/notes/search", headers=world["victim"], params={"q": NONCE}
    )
    assert mine.json()["count"] == 1, "the author cannot find their own note"


def test_an_api_key_is_not_a_way_round_it(
    client: TestClient, world: dict[str, Any]
) -> None:
    """The same endpoints with a different credential are the same endpoints."""
    made = client.post(
        f"{API}/api-keys/",
        headers=world["landlord"],
        json={"name": "probe", "scope": "read"},
    )
    assert made.status_code == 200, made.text
    key = {"Authorization": f"Bearer {made.json()['key']}"}

    assert client.get(f"{API}/notes/{world['note_id']}", headers=key).status_code == 404
    found = client.get(f"{API}/notes/search", headers=key, params={"q": NONCE})
    assert found.status_code == 200
    assert found.json()["count"] == 0


# --- the space is not a way in ----------------------------------------------


def test_deleting_the_space_leaves_the_note_alone(
    client: TestClient, world: dict[str, Any]
) -> None:
    """The reason `namespace_id` is SET NULL rather than CASCADE.

    Deleting a space is an act on that space's pages. It must not reach into
    somebody else's private notes, and it must not fail in a way that says
    there are any.
    """
    removed = client.delete(
        f"{API}/namespaces/{world['space_id']}", headers=world["landlord"]
    )
    assert removed.status_code == 200, removed.text
    assert NONCE not in removed.text

    survived = client.get(f"{API}/notes/{world['note_id']}", headers=world["victim"])
    assert survived.status_code == 200, "the note went with the space"
    assert survived.json()["namespace_id"] is None, "it should now be unfiled"
    assert NONCE in survived.json()["content_text"]

    still_findable = client.get(
        f"{API}/notes/search", headers=world["victim"], params={"q": NONCE}
    )
    assert still_findable.json()["count"] == 1


# --- archive ----------------------------------------------------------------


def test_an_archived_note_leaves_the_list_but_not_the_index(
    client: TestClient, world: dict[str, Any]
) -> None:
    """Archiving is "out of my way", not "forgotten"."""
    headers = world["victim"]
    archived = client.post(f"{API}/notes/{world['note_id']}/archive", headers=headers)
    assert archived.status_code == 200, archived.text

    default_list = client.get(f"{API}/notes/", headers=headers).json()
    assert world["note_id"] not in [r["id"] for r in default_list["data"]]

    archive = client.get(
        f"{API}/notes/", headers=headers, params={"archived": True}
    ).json()
    assert world["note_id"] in [r["id"] for r in archive["data"]]

    found = client.get(f"{API}/notes/search", headers=headers, params={"q": NONCE})
    assert found.json()["count"] == 1, "archiving hid it from search"

    excluded = client.get(
        f"{API}/notes/search",
        headers=headers,
        params={"q": NONCE, "include_archived": False},
    )
    assert excluded.json()["count"] == 0


def test_archiving_clears_the_pin(client: TestClient, world: dict[str, Any]) -> None:
    """A pinned note in the archive is one somebody will hunt for at the top."""
    headers = world["victim"]
    client.post(f"{API}/notes/{world['note_id']}/pin", headers=headers)
    archived = client.post(f"{API}/notes/{world['note_id']}/archive", headers=headers)
    assert archived.json()["pinned"] is False


# --- the ordinary promises --------------------------------------------------


def test_a_note_is_findable_the_moment_it_is_saved(
    client: TestClient, world: dict[str, Any]
) -> None:
    """No worker has run. Postgres writes the search vector at COMMIT."""
    word = f"aubergine-{uuid.uuid4().hex[:8]}"
    made = client.post(
        f"{API}/notes/",
        headers=world["victim"],
        json={"title": "Shopping", "content": f"<p>{word}</p>"},
    )
    assert made.status_code == 200, made.text

    found = client.get(
        f"{API}/notes/search", headers=world["victim"], params={"q": word}
    )
    assert found.json()["count"] == 1


def test_saving_over_somebody_elses_edit_is_refused(
    client: TestClient, world: dict[str, Any]
) -> None:
    """The 409 contract the editor's autosave needs to offer a choice."""
    headers = world["victim"]
    url = f"{API}/notes/{world['note_id']}"
    current = client.get(url, headers=headers).json()

    stale = client.patch(
        url,
        headers=headers,
        json={
            "content": "<p>Different</p>",
            "expected_version": current["version"] - 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_version"] == current["version"]


def test_ticking_a_box_does_not_cost_a_new_version(
    client: TestClient, world: dict[str, Any]
) -> None:
    """Re-embedding a shopping list because milk got crossed off is spend for nothing."""
    headers = world["victim"]
    made = client.post(
        f"{API}/notes/",
        headers=headers,
        json={
            "kind": "checklist",
            "title": "Shopping",
            "content": '<ul data-type="taskList">'
            '<li data-checked="false"><div><p>Milk</p></div></li></ul>',
        },
    )
    note = made.json()
    assert note["checklist_total"] == 1
    assert note["checklist_done"] == 0

    ticked = client.patch(
        f"{API}/notes/{note['id']}",
        headers=headers,
        json={
            "content": '<ul data-type="taskList">'
            '<li data-checked="true"><div><p>Milk</p></div></li></ul>'
        },
    )
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["checklist_done"] == 1
    assert ticked.json()["version"] == note["version"], "a tick bumped the version"


def test_a_clone_arrives_neither_pinned_nor_archived(
    client: TestClient, world: dict[str, Any]
) -> None:
    headers = world["victim"]
    client.post(f"{API}/notes/{world['note_id']}/pin", headers=headers)
    client.post(f"{API}/notes/{world['note_id']}/archive", headers=headers)

    clone = client.post(f"{API}/notes/{world['note_id']}/clone", headers=headers)
    assert clone.status_code == 200, clone.text
    body = clone.json()
    assert body["pinned"] is False
    assert body["archived"] is False
    assert body["id"] != world["note_id"]
    assert NONCE in body["content_text"]


def test_a_note_cannot_be_filed_in_a_space_you_cannot_see(
    client: TestClient, db: Session, world: dict[str, Any]
) -> None:
    """Otherwise the response tells you whether a space exists."""
    outsider, password = create_user_with_password(db)
    theirs = create_namespace(db, outsider, "Not yours")

    refused = client.post(
        f"{API}/notes/",
        headers=world["victim"],
        json={"namespace_id": str(theirs.id), "title": "Nice space"},
    )
    assert refused.status_code == 404


def test_the_note_limit_refuses_and_says_why(client: TestClient, db: Session) -> None:
    """Notes are capped by their own number, resolved through the usual tiers.

    Set on the account rather than the group, because the account override is
    the first tier and proves the resolver is being consulted at all.
    """
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    user.max_notes = 1
    db.add(user)
    db.commit()

    first = client.post(f"{API}/notes/", headers=headers, json={"title": "One"})
    assert first.status_code == 200, first.text

    second = client.post(f"{API}/notes/", headers=headers, json={"title": "Two"})
    assert second.status_code == 409
    assert "limit of 1 note" in second.json()["detail"]

    # And a clone is charged the same way, or copying is a way round the limit.
    cloned = client.post(f"{API}/notes/{first.json()['id']}/clone", headers=headers)
    assert cloned.status_code == 409


def test_an_archived_note_still_counts(client: TestClient, db: Session) -> None:
    """Otherwise archiving is a way to keep an unlimited number of notes."""
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    user.max_notes = 1
    db.add(user)
    db.commit()

    first = client.post(f"{API}/notes/", headers=headers, json={"title": "One"})
    client.post(f"{API}/notes/{first.json()['id']}/archive", headers=headers)

    blocked = client.post(f"{API}/notes/", headers=headers, json={"title": "Two"})
    assert blocked.status_code == 409

    # Deleting is what frees a place, which is why the archive need not expire.
    client.delete(f"{API}/notes/{first.json()['id']}", headers=headers)
    allowed = client.post(f"{API}/notes/", headers=headers, json={"title": "Two"})
    assert allowed.status_code == 200
