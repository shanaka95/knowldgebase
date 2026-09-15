"""Names within a space, and who is told they are an admin of it.

A file manager lets you call two things the same name as long as they are not
side by side. That is the rule here too, and it was not being enforced: two
folders called "Invoices" could sit in the same folder, and two pages called
"Notes" in the same one.

Spaces are different again: the *name* is the user's own business, but the URL
identifies one space in the whole installation, so it is the slug that has to
give way.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import NamespaceMember
from tests.utils.kb import (
    API,
    create_namespace,
    create_user_with_password,
    login,
)

FOLDERS = f"{API}/folders/"
DOCUMENTS = f"{API}/documents/"
NAMESPACES = f"{API}/namespaces/"


def _folder(
    client: TestClient, headers: dict[str, str], ns_id: str, name: str, parent=None
):
    return client.post(
        FOLDERS,
        headers=headers,
        json={"namespace_id": ns_id, "name": name, "parent_id": parent},
    )


def _document(
    client: TestClient, headers: dict[str, str], ns_id: str, title: str, folder=None
):
    return client.post(
        DOCUMENTS,
        headers=headers,
        json={
            "namespace_id": ns_id,
            "title": title,
            "content": "<p>x</p>",
            "content_format": "html",
            "folder_id": folder,
        },
    )


# --------------------------------------------------------------------- folders


def test_two_folders_cannot_share_a_name_in_one_place(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)

    assert _folder(client, headers, str(ns.id), "Invoices").status_code == 200
    clash = _folder(client, headers, str(ns.id), "Invoices")
    assert clash.status_code == 409
    assert "already a folder" in clash.json()["detail"]


def test_the_same_name_is_fine_in_a_different_folder(
    client: TestClient, db: Session
) -> None:
    """Exactly as on a computer: /2025/Invoices and /2026/Invoices are two folders."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)

    y2025 = _folder(client, headers, str(ns.id), "2025").json()
    y2026 = _folder(client, headers, str(ns.id), "2026").json()
    assert (
        _folder(client, headers, str(ns.id), "Invoices", y2025["id"]).status_code == 200
    )
    assert (
        _folder(client, headers, str(ns.id), "Invoices", y2026["id"]).status_code == 200
    )


def test_case_alone_does_not_make_a_different_folder(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    assert _folder(client, headers, str(ns.id), "Invoices").status_code == 200
    assert _folder(client, headers, str(ns.id), "invoices").status_code == 409


def test_renaming_onto_a_sibling_is_refused(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _folder(client, headers, str(ns.id), "Invoices")
    other = _folder(client, headers, str(ns.id), "Receipts").json()

    renamed = client.patch(
        f"{API}/folders/{other['id']}", headers=headers, json={"name": "Invoices"}
    )
    assert renamed.status_code == 409


def test_moving_onto_a_sibling_is_refused(client: TestClient, db: Session) -> None:
    """The move is what creates the clash, so it is caught after the move applies."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    archive = _folder(client, headers, str(ns.id), "Archive").json()
    _folder(client, headers, str(ns.id), "Invoices", archive["id"])
    loose = _folder(client, headers, str(ns.id), "Invoices").json()

    moved = client.patch(
        f"{API}/folders/{loose['id']}",
        headers=headers,
        json={"parent_id": archive["id"]},
    )
    assert moved.status_code == 409


# ------------------------------------------------------------------- documents


def test_two_pages_cannot_share_a_name_in_one_folder(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    assert _document(client, headers, str(ns.id), "Notes").status_code == 200
    clash = _document(client, headers, str(ns.id), "Notes")
    assert clash.status_code == 409
    assert "already a page" in clash.json()["detail"]


def test_a_page_may_share_a_name_with_a_folder(client: TestClient, db: Session) -> None:
    """They are different kinds of thing; a file manager allows this too."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    assert _folder(client, headers, str(ns.id), "Invoices").status_code == 200
    assert _document(client, headers, str(ns.id), "Invoices").status_code == 200


def test_a_copy_steps_around_the_name_rather_than_failing(
    client: TestClient, db: Session
) -> None:
    """Nobody typed "(copy)", so it is made to fit instead of being refused."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    page = _document(client, headers, str(ns.id), "Runbook").json()

    first = client.post(
        f"{API}/documents/{page['id']}/clone",
        headers=headers,
        json={"namespace_id": str(ns.id)},
    )
    second = client.post(
        f"{API}/documents/{page['id']}/clone",
        headers=headers,
        json={"namespace_id": str(ns.id)},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["title"] == "Runbook (copy)"
    assert second.json()["title"] == "Runbook (copy) (2)"


# ---------------------------------------------------------------------- spaces


def test_two_people_may_both_have_a_space_called_the_same_thing(
    client: TestClient, db: Session
) -> None:
    """The name is theirs; the URL is what has to differ, and only for the second."""
    first_user, first_pw = create_user_with_password(db)
    second_user, second_pw = create_user_with_password(db)

    mine = client.post(
        NAMESPACES,
        headers=login(client, first_user, first_pw),
        json={"name": "Visa appointment"},
    )
    theirs = client.post(
        NAMESPACES,
        headers=login(client, second_user, second_pw),
        json={"name": "Visa appointment"},
    )
    assert mine.status_code == 200 and theirs.status_code == 200
    assert mine.json()["name"] == theirs.json()["name"] == "Visa appointment"
    assert mine.json()["slug"] != theirs.json()["slug"]


def test_a_second_slug_does_not_count_the_first(
    client: TestClient, db: Session
) -> None:
    """`-2` would tell a stranger that somebody already has the plain name."""
    first_user, first_pw = create_user_with_password(db)
    second_user, second_pw = create_user_with_password(db)
    client.post(
        NAMESPACES,
        headers=login(client, first_user, first_pw),
        json={"name": "Tax return"},
    )
    theirs = client.post(
        NAMESPACES,
        headers=login(client, second_user, second_pw),
        json={"name": "Tax return"},
    )
    assert theirs.json()["slug"] != "tax-return-2"
    assert theirs.json()["slug"].startswith("tax-return-")


def test_one_person_still_cannot_have_two_spaces_with_one_name(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    headers = login(client, owner, pw)
    assert (
        client.post(NAMESPACES, headers=headers, json={"name": "Receipts"}).status_code
        == 200
    )
    assert (
        client.post(NAMESPACES, headers=headers, json={"name": "Receipts"}).status_code
        == 409
    )


# ------------------------------------------------- being an admin of the app,
#                                                    not of everybody's spaces


def test_an_administrator_is_not_labelled_an_admin_of_your_space(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The badge describes the relationship, not the account.

    A superuser can open every space in the installation. Calling that "admin
    on this space" put an ADMIN badge on spaces belonging to other people that
    had never been shared with anybody.
    """
    owner, _ = create_user_with_password(db)
    ns = create_namespace(db, owner, name="Visa appointment")

    seen = client.get(f"{API}/namespaces/{ns.id}", headers=superuser_token_headers)
    assert seen.status_code == 200, "an administrator can still open it"
    assert seen.json()["my_role"] is None
    assert seen.json()["shared_with_you"] is True


def test_other_peoples_spaces_are_not_in_an_administrators_own_list(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The switcher is the reader's own working spaces, not the whole database."""
    owner, _ = create_user_with_password(db)
    ns = create_namespace(db, owner, name="Not mine at all")

    listed = client.get(f"{API}/namespaces/", headers=superuser_token_headers).json()
    assert str(ns.id) not in {row["id"] for row in listed["data"]}


def test_a_space_actually_shared_with_you_says_which_role_you_hold(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    guest, guest_pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    db.add(NamespaceMember(namespace_id=ns.id, user_id=guest.id, role="viewer"))
    db.commit()

    headers = login(client, guest, guest_pw)
    listed = client.get(f"{API}/namespaces/", headers=headers).json()
    row = next(r for r in listed["data"] if r["id"] == str(ns.id))
    assert row["my_role"] == "viewer"
    assert row["shared_with_you"] is True
