"""Sharing a page: with a person, with a stranger, by link, and by copying it.

The question every test here asks is the same one: *who can read this now, and
did somebody deliberately allow that?*
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import DocumentShare, ShareInvitation, ShareRole
from app.services.email import LoggingEmailSender, get_email_sender
from tests.utils.kb import (
    API,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)
from tests.utils.user import last_email_link_token
from tests.utils.utils import random_email, random_lower_string

DENIED = (401, 403, 404)


@pytest.fixture(autouse=True)
def _clear_mailbox() -> None:
    sender = get_email_sender()
    if isinstance(sender, LoggingEmailSender):
        sender.sent.clear()


def mailbox() -> list[Any]:
    sender = get_email_sender()
    assert isinstance(sender, LoggingEmailSender)
    return sender.sent


@pytest.fixture
def owner(client: TestClient, db: Session) -> dict[str, Any]:
    user, password = create_user_with_password(db)
    user.full_name = "Sam Owner"
    db.add(user)
    db.commit()
    headers = login(client, user, password)
    ns = create_namespace(db, user, "Owner space")
    doc = create_document(
        db, ns, user, title="Quarterly report", html="<p>The number.</p>"
    )
    db.commit()
    return {
        "user": user,
        "headers": headers,
        "namespace": ns,
        "document": doc,
        "url": f"{API}/documents/{doc.id}",
    }


# ---------------------------------------------------------------------------
# Looking somebody up before sharing
# ---------------------------------------------------------------------------


def test_an_exact_address_is_confirmed(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    other, _ = create_user_with_password(db)
    r = client.get(
        f"{API}/users/lookup", headers=owner["headers"], params={"email": other.email}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["user"]["email"] == other.email


def test_an_address_with_no_account_is_not_an_error(
    client: TestClient, owner: dict[str, Any]
) -> None:
    """It can still be invited, so this is information, not a failure."""
    r = client.get(
        f"{API}/users/lookup",
        headers=owner["headers"],
        params={"email": "nobody@example.com"},
    )
    assert r.status_code == 200
    assert r.json()["exists"] is False
    assert r.json()["user"] is None


def test_lookup_matches_the_whole_address_only(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """A prefix search here would be a way to read the user list."""
    other, _ = create_user_with_password(db)
    prefix = other.email.split("@")[0][:4]
    r = client.get(
        f"{API}/users/lookup", headers=owner["headers"], params={"email": prefix}
    )
    # Not a valid address, so it is rejected outright rather than searched.
    assert r.status_code == 422


def test_lookup_needs_a_session(client: TestClient, db: Session) -> None:
    other, _ = create_user_with_password(db)
    r = client.get(f"{API}/users/lookup", params={"email": other.email})
    assert r.status_code in DENIED


# ---------------------------------------------------------------------------
# Sharing with people who are here
# ---------------------------------------------------------------------------


def test_sharing_grants_access_and_says_so_by_email(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["shared"]) == 1
    assert body["invited"] == []

    sent = [m for m in mailbox() if m.to == guest.email]
    assert sent, "the person who was given access is told"
    assert "Quarterly report" in sent[-1].subject
    assert "Sam Owner" in sent[-1].subject

    guest_headers = login(client, guest, password)
    assert client.get(owner["url"], headers=guest_headers).status_code == 200


def test_a_note_from_the_sharer_reaches_the_email(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, _ = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={
            "emails": [guest.email],
            "role": "viewer",
            "message": "The figure on page two is the one to look at.",
        },
    )
    sent = [m for m in mailbox() if m.to == guest.email][-1]
    assert "figure on page two" in sent.text


def test_a_note_cannot_carry_markup_into_somebody_s_mail(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """It is text written by one person and rendered for another."""
    guest, _ = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={
            "emails": [guest.email],
            "role": "viewer",
            "message": "<img src=x onerror=alert(1)>",
        },
    )
    sent = [m for m in mailbox() if m.to == guest.email][-1]
    # Escaped, so the mail client renders the characters rather than a tag.
    # "onerror=" survives as literal text, which is harmless and correct.
    assert "<img" not in sent.html
    assert "&lt;img src=x onerror=alert(1)&gt;" in sent.html


def test_sharing_the_same_page_twice_changes_the_role(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, _ = create_user_with_password(db)
    for role in ("viewer", "editor"):
        r = client.post(
            f"{owner['url']}/shares/batch",
            headers=owner["headers"],
            json={"emails": [guest.email], "role": role},
        )
        assert r.status_code == 200
    shares = db.exec(
        select(DocumentShare).where(
            DocumentShare.document_id == owner["document"].id,
            DocumentShare.user_id == guest.id,
        )
    ).all()
    assert len(shares) == 1, "one person, one share"
    assert shares[0].role == ShareRole.editor


def test_you_cannot_share_a_page_with_yourself(
    client: TestClient, owner: dict[str, Any]
) -> None:
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [owner["user"].email], "role": "viewer"},
    )
    assert r.json()["skipped"][0]["reason"] == "That is your own address"


def test_somebody_who_already_has_the_space_is_skipped(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    from app.models import NamespaceRole
    from tests.utils.kb import add_member

    member, _ = create_user_with_password(db)
    add_member(db, owner["namespace"], member, NamespaceRole.viewer)
    db.commit()

    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [member.email], "role": "viewer"},
    )
    assert "through the space" in r.json()["skipped"][0]["reason"]


def test_a_stranger_cannot_share_somebody_else_s_page(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    stranger, password = create_user_with_password(db)
    headers = login(client, stranger, password)
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=headers,
        json={"emails": [stranger.email], "role": "editor"},
    )
    assert r.status_code in DENIED


# ---------------------------------------------------------------------------
# Inviting people who are not here yet
# ---------------------------------------------------------------------------


def test_an_unknown_address_is_invited_not_refused(
    client: TestClient, owner: dict[str, Any]
) -> None:
    address = random_email()
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shared"] == []
    assert [i["email"] for i in body["invited"]] == [address.lower()]

    sent = [m for m in mailbox() if m.to == address.lower()]
    assert sent, "an invitation is only useful if it is sent"
    assert "Quarterly report" in sent[-1].subject
    assert "/invite?token=" in sent[-1].text


def test_one_request_can_mix_people_and_strangers(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """Which is exactly what the share dialog has to report back."""
    known, _ = create_user_with_password(db)
    unknown = random_email()
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [known.email, unknown], "role": "viewer"},
    )
    body = r.json()
    assert [s["user"]["email"] for s in body["shared"]] == [known.email]
    assert [i["email"] for i in body["invited"]] == [unknown.lower()]


def test_an_invitation_grants_nothing_on_its_own(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """The link is not a key. Access comes from confirming the address."""
    address = random_email()
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "viewer"},
    )
    token = last_email_link_token()

    # Anyone can read what the invitation is about...
    preview = client.get(f"{API}/public/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["document_title"] == "Quarterly report"

    # ...and nobody can read the page with it.
    assert client.get(owner["url"]).status_code in DENIED
    shares = db.exec(select(DocumentShare)).all()
    assert all(s.document_id != owner["document"].id for s in shares)


def test_confirming_the_address_turns_an_invitation_into_access(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    address = random_email()
    password = random_lower_string()
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "editor"},
    )

    signup = client.post(
        f"{API}/users/signup", json={"email": address, "password": password}
    )
    assert signup.status_code == 200
    verification = last_email_link_token()
    confirmed = client.post(f"{API}/login/verify-email", json={"token": verification})
    assert confirmed.status_code == 200, confirmed.text
    assert "waiting" in confirmed.json()["message"]

    from app import crud

    new_user = crud.get_user_by_email(session=db, email=address)
    assert new_user is not None
    headers = login(client, new_user, password)
    assert client.get(owner["url"], headers=headers).status_code == 200

    # Editor, as invited.
    edit = client.put(owner["url"], headers=headers, json={"content": "<p>Edited.</p>"})
    assert edit.status_code == 200


def test_registering_with_a_different_address_grants_nothing(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """The invitation names an address; confirming a different one proves nothing."""
    invited = random_email()
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [invited], "role": "viewer"},
    )

    other = random_email()
    password = random_lower_string()
    client.post(f"{API}/users/signup", json={"email": other, "password": password})
    client.post(f"{API}/login/verify-email", json={"token": last_email_link_token()})

    from app import crud

    user = crud.get_user_by_email(session=db, email=other)
    assert user is not None
    headers = login(client, user, password)
    assert client.get(owner["url"], headers=headers).status_code == 404


def test_an_expired_invitation_does_nothing(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    address = random_email()
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "viewer"},
    )
    token = last_email_link_token()
    record = db.exec(
        select(ShareInvitation).where(ShareInvitation.email == address.lower())
    ).first()
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.add(record)
    db.commit()

    assert client.get(f"{API}/public/invitations/{token}").status_code == 410

    password = random_lower_string()
    client.post(f"{API}/users/signup", json={"email": address, "password": password})
    client.post(f"{API}/login/verify-email", json={"token": last_email_link_token()})

    from app import crud

    user = crud.get_user_by_email(session=db, email=address)
    assert user is not None
    headers = login(client, user, password)
    assert client.get(owner["url"], headers=headers).status_code == 404


def test_a_withdrawn_invitation_stops_working(
    client: TestClient, owner: dict[str, Any]
) -> None:
    address = random_email()
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "viewer"},
    )
    invitation_id = r.json()["invited"][0]["id"]
    token = last_email_link_token()

    cancelled = client.delete(
        f"{owner['url']}/invitations/{invitation_id}", headers=owner["headers"]
    )
    assert cancelled.status_code == 200
    assert client.get(f"{API}/public/invitations/{token}").status_code == 404


def test_a_forged_invitation_token_is_not_found(client: TestClient) -> None:
    assert client.get(f"{API}/public/invitations/{'x' * 40}").status_code == 404


# ---------------------------------------------------------------------------
# How many people
# ---------------------------------------------------------------------------


def test_a_page_cannot_be_shared_past_the_owner_s_limit(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    owner["user"].max_shares_per_document = 2
    db.add(owner["user"])
    db.commit()

    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={
            "emails": [random_email(), random_email(), random_email()],
            "role": "viewer",
        },
    )
    body = r.json()
    assert len(body["invited"]) == 2
    assert len(body["skipped"]) == 1
    assert "limit of 2" in body["skipped"][0]["reason"]
    assert body["max_recipients"] == 2


def test_the_limit_counts_invitations_as_well_as_shares(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """Otherwise a thousand invitations would slip under a limit of two."""
    owner["user"].max_shares_per_document = 1
    db.add(owner["user"])
    db.commit()

    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [random_email()], "role": "viewer"},
    )
    second = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [random_email()], "role": "viewer"},
    )
    assert second.json()["shared"] == []
    assert second.json()["invited"] == []
    assert "limit of 1" in second.json()["skipped"][0]["reason"]


def test_the_limit_belongs_to_the_account_not_the_product(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    owner["user"].max_shares_per_document = 500
    db.add(owner["user"])
    db.commit()
    r = client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [random_email()], "role": "viewer"},
    )
    assert r.json()["max_recipients"] == 500


# ---------------------------------------------------------------------------
# Public links
# ---------------------------------------------------------------------------


def test_a_public_link_is_readable_by_anyone(
    client: TestClient, owner: dict[str, Any]
) -> None:
    r = client.post(f"{owner['url']}/public", headers=owner["headers"])
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]

    # No session, no key, no headers at all.
    page = client.get(f"{API}/public/documents/{slug}")
    assert page.status_code == 200
    assert page.json()["title"] == "Quarterly report"
    assert "The number." in page.json()["content_html"]


def test_a_page_that_was_never_published_is_not_public(
    client: TestClient, owner: dict[str, Any]
) -> None:
    assert (
        client.get(f"{API}/public/documents/{owner['document'].id}").status_code == 404
    )


def test_withdrawing_the_link_takes_effect_at_once(
    client: TestClient, owner: dict[str, Any]
) -> None:
    slug = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()[
        "slug"
    ]
    assert client.get(f"{API}/public/documents/{slug}").status_code == 200

    client.delete(f"{owner['url']}/public", headers=owner["headers"])
    assert client.get(f"{API}/public/documents/{slug}").status_code == 404


def test_re_publishing_issues_a_new_link(
    client: TestClient, owner: dict[str, Any]
) -> None:
    """So a link someone withdrew does not quietly come back to life."""
    first = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()[
        "slug"
    ]
    client.delete(f"{owner['url']}/public", headers=owner["headers"])
    second = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()[
        "slug"
    ]
    assert first != second
    assert client.get(f"{API}/public/documents/{first}").status_code == 404
    assert client.get(f"{API}/public/documents/{second}").status_code == 200


def test_publishing_twice_keeps_the_same_link(
    client: TestClient, owner: dict[str, Any]
) -> None:
    """Re-opening the dialog to copy the address must not break the copy sent."""
    first = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()
    second = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()
    assert first["slug"] == second["slug"]


def test_a_public_page_gives_away_nothing_around_it(
    client: TestClient, owner: dict[str, Any]
) -> None:
    slug = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()[
        "slug"
    ]
    body = client.get(f"{API}/public/documents/{slug}").json()
    for leak in ("namespace_id", "folder_id", "created_by", "version", "summary"):
        assert leak not in body, f"a public page must not expose {leak}"


def test_publishing_one_page_does_not_publish_its_neighbours(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    neighbour = create_document(
        db, owner["namespace"], owner["user"], title="Not shared"
    )
    db.commit()
    client.post(f"{owner['url']}/public", headers=owner["headers"])

    assert client.get(f"{API}/public/documents/{neighbour.id}").status_code == 404
    assert client.get(f"{API}/documents/{neighbour.id}").status_code in DENIED


def test_only_somebody_who_can_share_may_publish(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "editor"},
    )
    headers = login(client, guest, password)
    r = client.post(f"{owner['url']}/public", headers=headers)
    assert r.status_code in DENIED, "a guest editor cannot publish to the world"


def test_a_public_page_serves_only_its_own_images(
    client: TestClient, owner: dict[str, Any]
) -> None:
    upload = client.post(
        f"{API}/attachments/",
        headers=owner["headers"],
        data={"namespace_id": str(owner["namespace"].id)},
        files={"file": ("secret.png", io.BytesIO(b"not really a png"), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]

    slug = client.post(f"{owner['url']}/public", headers=owner["headers"]).json()[
        "slug"
    ]
    # The page does not reference this file, so publishing the page must not
    # publish the space's file store.
    r = client.get(f"{API}/public/{slug}/attachments/{attachment_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cloning
# ---------------------------------------------------------------------------


def test_a_shared_page_can_be_copied_into_your_own_space(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()

    r = client.post(
        f"{owner['url']}/clone",
        headers=headers,
        json={"namespace_id": str(mine.id)},
    )
    assert r.status_code == 200, r.text
    clone = r.json()
    assert clone["id"] != str(owner["document"].id)
    assert clone["title"] == "Quarterly report (copy)"
    assert clone["namespace_id"] == str(mine.id)
    assert "The number." in clone["content_html"]


def test_a_copy_is_a_separate_page(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()
    clone_id = client.post(
        f"{owner['url']}/clone", headers=headers, json={"namespace_id": str(mine.id)}
    ).json()["id"]

    client.put(
        f"{API}/documents/{clone_id}",
        headers=headers,
        json={"content": "<p>My own notes.</p>"},
    )
    original = client.get(owner["url"], headers=owner["headers"]).json()
    assert "The number." in original["content_html"]
    assert "My own notes." not in original["content_html"]


def test_a_copy_is_private_until_its_owner_shares_it(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """The original's shares do not follow the copy. That is the whole point."""
    guest, password = create_user_with_password(db)
    third, third_password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email, third.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()
    clone_id = client.post(
        f"{owner['url']}/clone", headers=headers, json={"namespace_id": str(mine.id)}
    ).json()["id"]

    # Neither the original's owner nor its other guest can see the copy.
    assert (
        client.get(f"{API}/documents/{clone_id}", headers=owner["headers"]).status_code
        == 404
    )
    third_headers = login(client, third, third_password)
    assert (
        client.get(f"{API}/documents/{clone_id}", headers=third_headers).status_code
        == 404
    )


def test_you_cannot_copy_a_page_you_cannot_read(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    stranger, password = create_user_with_password(db)
    headers = login(client, stranger, password)
    mine = create_namespace(db, stranger, "Their space")
    db.commit()
    r = client.post(
        f"{owner['url']}/clone", headers=headers, json={"namespace_id": str(mine.id)}
    )
    assert r.status_code in DENIED


def test_you_cannot_copy_into_a_space_you_cannot_write(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    r = client.post(
        f"{owner['url']}/clone",
        headers=headers,
        json={"namespace_id": str(owner["namespace"].id)},
    )
    assert r.status_code in DENIED


def test_a_copy_keeps_the_type_and_takes_a_new_title(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    client.put(owner["url"], headers=owner["headers"], json={"doc_type": "Report"})
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()

    clone = client.post(
        f"{owner['url']}/clone",
        headers=headers,
        json={"namespace_id": str(mine.id), "title": "Their report, my copy"},
    ).json()
    assert clone["title"] == "Their report, my copy"
    assert clone["doc_type"] == "Report"


def test_a_copy_brings_its_images_with_it(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    """Otherwise the copy renders for its author and nobody else."""
    upload = client.post(
        f"{API}/attachments/",
        headers=owner["headers"],
        data={"namespace_id": str(owner["namespace"].id)},
        files={"file": ("chart.png", io.BytesIO(b"pretend png"), "image/png")},
    )
    attachment_id = upload.json()["id"]
    client.put(
        owner["url"],
        headers=owner["headers"],
        json={
            "content": (
                f'<p>See <img src="{settings.API_V1_STR}/attachments/'
                f'{attachment_id}/download" alt=""></p>'
            )
        },
    )

    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()

    clone = client.post(
        f"{owner['url']}/clone", headers=headers, json={"namespace_id": str(mine.id)}
    ).json()
    assert attachment_id not in clone["content_html"], "it points at its own copy"

    copied = clone["content_html"].split("/attachments/")[1].split("/download")[0]
    readable = client.get(f"{API}/attachments/{copied}/download", headers=headers)
    assert readable.status_code == 200, "and the copy can actually read it"


def test_a_copied_page_is_queued_for_indexing(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    from app.models import EmbeddingJob

    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    mine = create_namespace(db, guest, "My space")
    db.commit()
    clone_id = client.post(
        f"{owner['url']}/clone", headers=headers, json={"namespace_id": str(mine.id)}
    ).json()["id"]

    jobs = db.exec(
        select(EmbeddingJob).where(EmbeddingJob.document_id == uuid.UUID(clone_id))
    ).all()
    assert jobs, "a copy has to be findable in its new owner's search"


# ---------------------------------------------------------------------------
# Where shared pages show up
# ---------------------------------------------------------------------------


def test_a_shared_page_appears_under_shared_with_me(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "editor"},
    )
    headers = login(client, guest, password)

    r = client.get(f"{API}/documents/shared-with-me", headers=headers)
    assert r.status_code == 200
    titles = [d["title"] for d in r.json()["documents"]]
    assert "Quarterly report" in titles
    assert r.json()["documents"][0]["my_role"] == "editor"


def test_unsharing_removes_it_again(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    guest, password = create_user_with_password(db)
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [guest.email], "role": "viewer"},
    )
    headers = login(client, guest, password)
    client.delete(f"{owner['url']}/shares/{guest.id}", headers=owner["headers"])

    r = client.get(f"{API}/documents/shared-with-me", headers=headers)
    assert r.json()["documents"] == []
    assert client.get(owner["url"], headers=headers).status_code == 404


def test_the_owner_can_see_who_is_still_only_invited(
    client: TestClient, owner: dict[str, Any]
) -> None:
    address = random_email()
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [address], "role": "viewer"},
    )
    r = client.get(f"{owner['url']}/invitations", headers=owner["headers"])
    assert r.status_code == 200
    assert [i["email"] for i in r.json()] == [address.lower()]


def test_invitations_are_not_visible_to_strangers(
    client: TestClient, db: Session, owner: dict[str, Any]
) -> None:
    client.post(
        f"{owner['url']}/shares/batch",
        headers=owner["headers"],
        json={"emails": [random_email()], "role": "viewer"},
    )
    stranger, password = create_user_with_password(db)
    headers = login(client, stranger, password)
    assert (
        client.get(f"{owner['url']}/invitations", headers=headers).status_code in DENIED
    )
