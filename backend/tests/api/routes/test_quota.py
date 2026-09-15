"""The page limit, at every door a page can come through.

There are three ways to make a page - write one, copy one, import one - and the
import path queues work that becomes a page minutes later. A check on only the
first would be no check at all.
"""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import (
    DocumentShare,
    ImportJob,
    ImportStatus,
    NamespaceMember,
    User,
)
from app.services import quota
from tests.utils.kb import (
    API,
    api_create_document,
    create_namespace,
    create_user_with_password,
    login,
)

DOCUMENTS = f"{API}/documents/"
IMPORTS = f"{API}/imports/"


def _set_limit(db: Session, user: User, pages: int) -> None:
    user.max_pages = pages
    db.add(user)
    db.commit()


def _new_page(client: TestClient, headers: dict[str, str], ns_id: str, title: str):
    return client.post(
        DOCUMENTS,
        headers=headers,
        json={
            "namespace_id": ns_id,
            "title": title,
            "content": "<p>x</p>",
            "content_format": "html",
        },
    )


def _png() -> tuple[str, io.BytesIO, str]:
    return ("scan.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), "image/png")


# --------------------------------------------------------------- writing one


def test_a_page_cannot_be_created_past_the_accounts_limit(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 1)

    assert _new_page(client, headers, str(ns.id), "First").status_code == 200
    refused = _new_page(client, headers, str(ns.id), "Second")
    assert refused.status_code == 409
    assert "limit of 1 page." in refused.json()["detail"], "singular, not '1 pages'"


def test_the_refusal_never_mentions_groups(client: TestClient, db: Session) -> None:
    """An account is told its own number, never where the number came from."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 0)

    refused = _new_page(client, headers, str(ns.id), "Nope")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "group" not in detail.lower()
    assert "cannot create pages" in detail, "zero is stated plainly, not as 0 pages"


def test_a_limit_of_zero_really_means_none(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 0)
    assert _new_page(client, headers, str(ns.id), "Nope").status_code == 409


def test_deleting_a_page_makes_room_for_another(
    client: TestClient, db: Session
) -> None:
    """Counted live from the rows, so a delete frees its place immediately."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 1)

    first = _new_page(client, headers, str(ns.id), "First").json()
    assert _new_page(client, headers, str(ns.id), "Second").status_code == 409

    assert (
        client.delete(f"{API}/documents/{first['id']}", headers=headers).status_code
        == 200
    )
    assert _new_page(client, headers, str(ns.id), "Second").status_code == 200


def test_a_page_written_in_someone_elses_space_counts_against_its_author(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    guest, guest_pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    db.add(NamespaceMember(namespace_id=ns.id, user_id=guest.id, role="editor"))
    db.commit()
    _set_limit(db, guest, 1)

    headers = login(client, guest, guest_pw)
    assert _new_page(client, headers, str(ns.id), "Guest one").status_code == 200
    assert _new_page(client, headers, str(ns.id), "Guest two").status_code == 409

    # The space owner is untouched by what a guest spent.
    db.refresh(owner)
    assert quota.page_count(db, owner.id) == 0


# ---------------------------------------------------------------- copying one


def test_a_copy_is_refused_when_the_copier_is_full(
    client: TestClient, db: Session
) -> None:
    """Cloning needs only *viewer* on the original, so it is the open door."""
    author, author_pw = create_user_with_password(db)
    copier, copier_pw = create_user_with_password(db)
    source_ns = create_namespace(db, author)
    page = api_create_document(
        client, login(client, author, author_pw), str(source_ns.id), title="Shared"
    )
    db.add(DocumentShare(document_id=page["id"], user_id=copier.id, role="viewer"))
    db.commit()

    own_ns = create_namespace(db, copier)
    _set_limit(db, copier, 0)
    headers = login(client, copier, copier_pw)

    refused = client.post(
        f"{API}/documents/{page['id']}/clone",
        headers=headers,
        json={"namespace_id": str(own_ns.id)},
    )
    assert refused.status_code == 409


# --------------------------------------------------------------- importing


def test_a_batch_is_refused_whole_when_only_part_of_it_fits(
    client: TestClient, db: Session
) -> None:
    """An import has no "skipped" channel, so half a set of scans is worse."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 2)

    refused = client.post(
        f"{API}/imports/batch",
        headers=headers,
        data={"namespace_id": str(ns.id)},
        files=[("files", _png()), ("files", _png()), ("files", _png())],
    )
    assert refused.status_code == 409
    # Nothing was queued, so nothing arrives later - and nothing was written to
    # object storage either, because the check runs before the upload loop.
    assert quota.pending_page_count(db, owner.id) == 0


def test_combining_several_files_is_charged_as_the_one_page_it_becomes(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 1)

    accepted = client.post(
        f"{API}/imports/batch",
        headers=headers,
        data={"namespace_id": str(ns.id), "combine": "true"},
        files=[("files", _png()), ("files", _png()), ("files", _png())],
    )
    assert accepted.status_code == 200, accepted.text
    assert quota.pending_page_count(db, owner.id) == 1


def test_queued_imports_count_before_they_become_pages(
    client: TestClient, db: Session
) -> None:
    """Otherwise five hundred files slip under a limit of a hundred."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 1)

    first = client.post(
        IMPORTS,
        headers=headers,
        data={"namespace_id": str(ns.id)},
        files={"file": _png()},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        IMPORTS,
        headers=headers,
        data={"namespace_id": str(ns.id)},
        files={"file": _png()},
    )
    assert second.status_code == 409, "the queued one already spent the place"


def test_cancelling_an_import_returns_the_headroom(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    _set_limit(db, owner, 1)

    job = client.post(
        IMPORTS,
        headers=headers,
        data={"namespace_id": str(ns.id)},
        files={"file": _png()},
    ).json()
    assert (
        client.post(f"{API}/imports/{job['id']}/cancel", headers=headers).status_code
        == 200
    )
    assert quota.pending_page_count(db, owner.id) == 0
    assert (
        _new_page(client, headers, str(ns.id), "Now there is room").status_code == 200
    )


def test_retrying_an_import_is_refused_when_the_account_is_now_full(
    client: TestClient, db: Session
) -> None:
    """A retry adds a page and inserts no row, so an insert-time check misses it."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)

    job_row = ImportJob(
        namespace_id=ns.id,
        created_by=owner.id,
        filename="scan.png",
        content_type="image/png",
        size=10,
        object_key=f"imports/{ns.id}/retry-test",
        status=ImportStatus.failed,
    )
    db.add(job_row)
    db.commit()
    db.refresh(job_row)

    _set_limit(db, owner, 0)
    refused = client.post(f"{API}/imports/{job_row.id}/retry", headers=headers)
    assert refused.status_code == 409


# ------------------------------------------------------------------ API keys


def test_a_write_scoped_api_key_is_held_to_the_same_limit(
    client: TestClient, db: Session
) -> None:
    """Agents and MCP write with a key; the limit belongs to the key's owner."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    headers = login(client, owner, pw)
    key = client.post(
        f"{API}/api-keys/",
        headers=headers,
        json={"name": "agent", "scope": "write"},
    ).json()
    _set_limit(db, owner, 0)

    refused = _new_page(
        client, {"Authorization": f"Bearer {key['key']}"}, str(ns.id), "Via key"
    )
    assert refused.status_code == 409


# -------------------------------------------------------------- what is shown


def test_an_account_is_told_its_own_number_and_nothing_about_groups(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    headers = login(client, owner, pw)
    me: dict[str, Any] = client.get(f"{API}/users/me", headers=headers).json()

    assert me["max_pages"] == 100, "the inherited number, served as a plain int"
    assert "pages_used" in me
    assert "group_id" not in me and "group" not in me
