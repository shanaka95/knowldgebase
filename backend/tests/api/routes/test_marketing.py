"""Sending to a list, and everything that must not happen while doing it.

The pacing, the at-most-once guarantee and the unsubscribe are the three things
worth proving here. They are also the three that fail quietly: a campaign that
sends twice, or keeps sending to somebody who left, looks exactly like a
working one from the inside.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    CampaignStatus,
    DeliveryStatus,
    MarketingCampaign,
    MarketingContact,
    MarketingDelivery,
)
from app.services import marketing
from app.worker import queue
from tests.utils.kb import API, create_user_with_password, login

ADMIN = f"{API}/admin/marketing"
PUBLIC = f"{API}/public/marketing"


@pytest.fixture
def people(db: Session) -> list[MarketingContact]:
    """Three contacts, cleaned up afterwards so counts stay predictable."""
    made = [
        marketing.ensure_contact(
            db, email=f"person-{uuid.uuid4().hex[:8]}@example.com", name=name
        )
        for name in ("Gagan S", "asdf", "Paweł Franczak")
    ]
    db.commit()
    for row in made:
        db.refresh(row)
    yield made
    for row in made:
        fresh = db.get(MarketingContact, row.id)
        if fresh is not None:
            db.delete(fresh)
    db.commit()


def make_campaign(
    client: TestClient,
    headers: dict[str, str],
    contacts: list[MarketingContact],
    **overrides: Any,
) -> dict[str, Any]:
    body = {
        "from_email": settings.MARKETING_FROM_ADDRESSES[0],
        "subject": "Would you try something I built?",
        "body_html": "<p>Hi {{name}}</p>",
        "contact_ids": [str(c.id) for c in contacts],
    }
    body.update(overrides)
    response = client.post(f"{ADMIN}/campaigns", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- who may touch any of this ----------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/settings"),
        ("get", "/contacts"),
        ("post", "/contacts"),
        ("get", "/campaigns"),
        ("post", "/campaigns"),
        ("post", "/preview"),
    ],
)
def test_an_ordinary_account_cannot_reach_the_marketing_area(
    client: TestClient, db: Session, method: str, path: str
) -> None:
    user, password = create_user_with_password(db)
    headers = login(client, user, password)
    call = getattr(client, method)
    extra = {"json": {}} if method == "post" else {}
    response = call(f"{ADMIN}{path}", headers=headers, **extra)
    assert response.status_code == 403


def test_a_superusers_api_key_cannot_either(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """The admin dependency chains off a session, not a credential.

    Worth asserting rather than assuming: a marketing router that accepted API
    keys would put "email everybody" behind a long-lived bearer token.
    """
    made = client.post(
        f"{API}/api-keys/",
        headers=superuser_token_headers,
        json={"name": "test", "scope": "write"},
    )
    assert made.status_code == 200, made.text
    key = made.json()["key"]
    response = client.get(
        f"{ADMIN}/contacts", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 403


# --- creating a campaign -----------------------------------------------------


def test_a_campaign_writes_one_delivery_per_person_a_second_apart(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """The send rate, which is a fact in the table rather than a sleep."""
    campaign = make_campaign(client, superuser_token_headers, people)
    assert campaign["total"] == 3
    assert campaign["status"] == CampaignStatus.sending

    rows = db.exec(
        select(MarketingDelivery)
        .where(MarketingDelivery.campaign_id == uuid.UUID(campaign["id"]))
        .order_by(col(MarketingDelivery.send_after))
    ).all()
    assert len(rows) == 3
    gaps = [
        (rows[i + 1].send_after - rows[i].send_after).total_seconds()
        for i in range(len(rows) - 1)
    ]
    assert gaps == [1.0, 1.0]


def test_somebody_who_unsubscribed_gets_no_delivery_at_all(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    marketing.unsubscribe(db, people[0].unsubscribe_token)
    db.commit()
    campaign = make_campaign(client, superuser_token_headers, people)
    assert campaign["total"] == 2

    addresses = {
        row.to_email
        for row in db.exec(
            select(MarketingDelivery).where(
                MarketingDelivery.campaign_id == uuid.UUID(campaign["id"])
            )
        ).all()
    }
    assert people[0].email not in addresses


def test_an_address_this_deployment_cannot_send_from_is_refused(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """An unverified sender fails every message in the campaign, one at a time."""
    response = client.post(
        f"{ADMIN}/campaigns",
        headers=superuser_token_headers,
        json={
            "from_email": "somebody@elsewhere.example",
            "subject": "s",
            "body_html": "<p>x</p>",
            "contact_ids": [str(people[0].id)],
        },
    )
    assert response.status_code == 422


def test_a_campaign_to_nobody_is_refused(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{ADMIN}/campaigns",
        headers=superuser_token_headers,
        json={
            "from_email": settings.MARKETING_FROM_ADDRESSES[0],
            "subject": "s",
            "body_html": "<p>x</p>",
            "contact_ids": [],
        },
    )
    assert response.status_code == 422


# --- the claim ---------------------------------------------------------------


def test_only_what_is_due_is_claimed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """The first message is due now; the others are one and two seconds out."""
    campaign = make_campaign(client, superuser_token_headers, people)
    campaign_id = uuid.UUID(campaign["id"])

    claimed = [
        item
        for item in queue.claim_marketing_sends(10)
        if item.campaign_id == campaign_id
    ]
    assert len(claimed) == 1


def test_a_claimed_message_is_not_claimed_again(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """The lease. Two workers polling together must not both send."""
    campaign = make_campaign(client, superuser_token_headers, people)
    campaign_id = uuid.UUID(campaign["id"])

    first = [i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id]
    second = [
        i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id
    ]
    assert len(first) == 1
    assert second == []


def test_unsubscribing_mid_campaign_stops_the_rest(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """Message one has gone. Messages two and three must not.

    This is the case a create-time filter cannot cover: at eleven minutes for a
    real list, somebody reads the first message and leaves before the last one
    is sent.
    """
    campaign = make_campaign(client, superuser_token_headers, people)
    campaign_id = uuid.UUID(campaign["id"])

    marketing.unsubscribe(db, people[1].unsubscribe_token)
    marketing.unsubscribe(db, people[2].unsubscribe_token)
    db.commit()

    # Everything is due by the time the worker next looks.
    db.exec(
        select(MarketingDelivery).where(MarketingDelivery.campaign_id == campaign_id)
    ).all()
    for row in db.exec(
        select(MarketingDelivery).where(MarketingDelivery.campaign_id == campaign_id)
    ).all():
        row.send_after = marketing.now()
        db.add(row)
    db.commit()

    claimed = [
        i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id
    ]
    assert len(claimed) == 1  # only the one who is still subscribed

    skipped = db.exec(
        select(MarketingDelivery).where(
            MarketingDelivery.campaign_id == campaign_id,
            MarketingDelivery.status == DeliveryStatus.skipped,
        )
    ).all()
    assert len(skipped) == 2
    assert {row.error for row in skipped} == {"unsubscribed"}


def test_a_cancelled_campaign_sends_nothing_more(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    campaign = make_campaign(client, superuser_token_headers, people)
    campaign_id = uuid.UUID(campaign["id"])

    stopped = client.post(
        f"{ADMIN}/campaigns/{campaign_id}/cancel", headers=superuser_token_headers
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == CampaignStatus.cancelled

    for row in db.exec(
        select(MarketingDelivery).where(MarketingDelivery.campaign_id == campaign_id)
    ).all():
        row.send_after = marketing.now()
        db.add(row)
    db.commit()

    assert [
        i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id
    ] == []


def test_a_campaign_closes_itself_when_the_last_one_lands(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    campaign = make_campaign(client, superuser_token_headers, people[:1])
    campaign_id = uuid.UUID(campaign["id"])
    claimed = [
        i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id
    ]
    assert len(claimed) == 1

    queue.complete_marketing_send(claimed[0].delivery_id, campaign_id)
    db.expire_all()
    row = db.get(MarketingCampaign, campaign_id)
    assert row is not None
    assert row.status == CampaignStatus.sent
    assert row.sent_count == 1
    assert row.finished_at is not None


def test_a_failure_is_retried_and_then_parked(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    campaign = make_campaign(client, superuser_token_headers, people[:1])
    campaign_id = uuid.UUID(campaign["id"])
    claimed = [
        i for i in queue.claim_marketing_sends(10) if i.campaign_id == campaign_id
    ][0]

    for _ in range(settings.MARKETING_MAX_ATTEMPTS):
        queue.fail_marketing_send(claimed.delivery_id, campaign_id, "SES said no")

    db.expire_all()
    delivery = db.get(MarketingDelivery, claimed.delivery_id)
    assert delivery is not None
    assert delivery.status == DeliveryStatus.failed
    assert delivery.error == "SES said no"
    campaign_row = db.get(MarketingCampaign, campaign_id)
    assert campaign_row is not None and campaign_row.failed_count == 1


# --- the unsubscribe link ----------------------------------------------------


def test_the_link_unsubscribes_and_says_so(
    client: TestClient, db: Session, people: list[MarketingContact]
) -> None:
    response = client.post(f"{PUBLIC}/unsubscribe/{people[0].unsubscribe_token}")
    assert response.status_code == 200
    db.refresh(people[0])
    assert people[0].unsubscribed_at is not None

    # Twice is fine. Somebody with two of our messages open has not erred.
    assert (
        client.post(f"{PUBLIC}/unsubscribe/{people[0].unsubscribe_token}").status_code
        == 200
    )


def test_an_unknown_link_is_a_404(client: TestClient) -> None:
    assert client.post(f"{PUBLIC}/unsubscribe/nope").status_code == 404


def test_a_scanner_cannot_spend_the_link(
    client: TestClient, people: list[MarketingContact]
) -> None:
    """Mail scanners fetch every URL in a message before anybody reads it.

    If GET acted, a large part of the list would unsubscribe itself within
    minutes of the send. The endpoint is POST-only, so a prefetch is a 405 and
    changes nothing.
    """
    response = client.get(f"{PUBLIC}/unsubscribe/{people[0].unsubscribe_token}")
    assert response.status_code == 405


def test_it_needs_no_credential(
    client: TestClient, people: list[MarketingContact]
) -> None:
    """The link arrives in a mailbox, not in a session."""
    response = client.post(
        f"{PUBLIC}/unsubscribe/{people[1].unsubscribe_token}",
        headers={"Authorization": ""},
    )
    assert response.status_code == 200


# --- preview and import ------------------------------------------------------


def test_the_preview_is_the_message(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    response = client.post(
        f"{ADMIN}/preview",
        headers=superuser_token_headers,
        json={
            "subject": "Hello",
            "body_html": "<p>Hi {{name}}</p>",
            "contact_id": str(people[0].id),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Hi Gagan" in body["html"]
    assert "unsubscribe" in body["html"].lower()


def test_an_upload_lands_on_the_list(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    csv = b"name,email\nJo Bloggs,upload-test@example.com\n"
    response = client.post(
        f"{ADMIN}/contacts/import",
        headers=superuser_token_headers,
        files={"file": ("contacts.csv", csv, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["added"] == 1

    row = db.exec(
        select(MarketingContact).where(
            MarketingContact.email == "upload-test@example.com"
        )
    ).one()
    db.delete(row)
    db.commit()


def test_a_new_account_joins_the_list(db: Session) -> None:
    """Signing up puts you on it. Nobody has to remember to do that by hand."""
    user, _ = create_user_with_password(db)
    row = db.exec(
        select(MarketingContact).where(MarketingContact.email == user.email)
    ).first()
    assert row is not None
    assert row.user_id == user.id
    db.delete(row)
    db.commit()


# --- editing a contact -------------------------------------------------------


def test_a_typo_in_an_address_can_be_fixed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    fixed = f"fixed-{uuid.uuid4().hex[:8]}@example.com"
    response = client.patch(
        f"{ADMIN}/contacts/{people[0].id}",
        headers=superuser_token_headers,
        json={"email": fixed.upper(), "name": "  Gagan Sharma  "},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Normalised on the way in, like every other address in the system.
    assert body["email"] == fixed
    assert body["name"] == "Gagan Sharma"


def test_editing_keeps_the_unsubscribe_link_working(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """A link already sitting in somebody's inbox has to survive a tidy-up."""
    token = people[0].unsubscribe_token
    client.patch(
        f"{ADMIN}/contacts/{people[0].id}",
        headers=superuser_token_headers,
        json={"name": "Renamed"},
    )
    assert client.post(f"{PUBLIC}/unsubscribe/{token}").status_code == 200


def test_editing_cannot_resubscribe_somebody(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """The one way this could have become a loophole."""
    marketing.unsubscribe(db, people[0].unsubscribe_token)
    db.commit()
    response = client.patch(
        f"{ADMIN}/contacts/{people[0].id}",
        headers=superuser_token_headers,
        json={"email": f"new-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["subscribed"] is False


def test_an_edit_cannot_collide_with_somebody_else(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    response = client.patch(
        f"{ADMIN}/contacts/{people[0].id}",
        headers=superuser_token_headers,
        json={"email": people[1].email},
    )
    assert response.status_code == 409


# --- who a campaign reaches --------------------------------------------------


def test_a_campaign_reaches_exactly_who_was_chosen(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    people: list[MarketingContact],
) -> None:
    """There is no widening. The ids sent are the audience.

    This is asserted against the whole table rather than the three fixtures,
    because the failure being guarded against is a campaign quietly reaching
    everybody who was not named.
    """
    chosen = people[:1]
    campaign = make_campaign(client, superuser_token_headers, chosen)
    assert campaign["total"] == 1

    addresses = {
        row.to_email
        for row in db.exec(
            select(MarketingDelivery).where(
                MarketingDelivery.campaign_id == uuid.UUID(campaign["id"])
            )
        ).all()
    }
    assert addresses == {chosen[0].email}


def test_a_campaign_naming_nobody_is_refused_by_the_schema(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """An empty list used to mean "everybody". Now it means nothing at all."""
    response = client.post(
        f"{ADMIN}/campaigns",
        headers=superuser_token_headers,
        json={
            "from_email": settings.MARKETING_FROM_ADDRESSES[0],
            "subject": "s",
            "body_html": "<p>x</p>",
            "contact_ids": [],
        },
    )
    assert response.status_code == 422
