"""Cold email, from the admin area.

Everything else this application sends is transactional: the recipient asked
for it, it goes to one person, and it needs no unsubscribe link because nobody
subscribed. This is the other kind, and the difference shows up in three
places - a list of addresses that are not accounts, a message somebody writes
and previews before it goes anywhere, and a record of what happened to each
address afterwards.

Superuser only, at the router level like every other admin router, which also
means an API key cannot reach it: the dependency chains off `SessionUser`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlmodel import col, func, or_, select

from app.api.deps import SessionDep, SessionUser, get_current_active_superuser
from app.core.config import settings
from app.models import (
    CampaignCreate,
    CampaignPreview,
    CampaignPreviewRequest,
    CampaignPublic,
    CampaignsPublic,
    CampaignStatus,
    ContactImportResult,
    ContactSource,
    DeliveriesPublic,
    DeliveryPublic,
    DeliveryStatus,
    MarketingCampaign,
    MarketingContact,
    MarketingContactCreate,
    MarketingContactPublic,
    MarketingContactsPublic,
    MarketingDelivery,
    MarketingSettings,
    Message,
)
from app.services import marketing

router = APIRouter(
    prefix="/admin/marketing",
    tags=["admin_marketing"],
    dependencies=[Depends(get_current_active_superuser)],
)

# A file bigger than this is not a contact list.
MAX_IMPORT_BYTES = 8 * 1024 * 1024


def _contact_public(contact: MarketingContact) -> MarketingContactPublic:
    return MarketingContactPublic(
        id=contact.id,
        email=contact.email,
        name=contact.name,
        source=contact.source,
        subscribed=contact.unsubscribed_at is None,
        unsubscribed_at=contact.unsubscribed_at,
        created_at=contact.created_at,
    )


def _campaign_public(campaign: MarketingCampaign) -> CampaignPublic:
    return CampaignPublic(
        id=campaign.id,
        name=campaign.name,
        from_email=campaign.from_email,
        subject=campaign.subject,
        body_html=campaign.body_html,
        status=campaign.status,
        total=campaign.total,
        sent_count=campaign.sent_count,
        failed_count=campaign.failed_count,
        created_at=campaign.created_at,
        started_at=campaign.started_at,
        finished_at=campaign.finished_at,
    )


# --- what the composer needs before it is drawn -----------------------------


@router.get("/settings", response_model=MarketingSettings)
def read_marketing_settings(session: SessionDep) -> Any:
    """The addresses that may be sent from, and how big the list is.

    The from-addresses are a setting rather than free text because each one has
    to be a verified SES identity; an unverified sender fails every message in
    the campaign, one at a time, for eleven minutes.
    """
    total, subscribed = marketing.counts(session)
    return MarketingSettings(
        from_addresses=list(settings.MARKETING_FROM_ADDRESSES),
        contacts=total,
        subscribed=subscribed,
    )


@router.get("/template", response_model=CampaignPreviewRequest)
def read_default_template() -> Any:
    """A starting point for a new campaign, not a fixed message."""
    return CampaignPreviewRequest(
        subject=marketing.DEFAULT_SUBJECT,
        body_html=marketing.DEFAULT_BODY_HTML,
    )


# --- contacts ---------------------------------------------------------------


@router.get("/contacts", response_model=MarketingContactsPublic)
def read_contacts(
    session: SessionDep,
    q: str | None = None,
    subscribed: bool | None = None,
    skip: int = 0,
    limit: Annotated[int, Query(le=500)] = 50,
) -> Any:
    """The list, newest first, filtered the way the screen filters it."""
    where = []
    if q:
        needle = f"%{q.strip().lower()}%"
        where.append(
            or_(
                func.lower(col(MarketingContact.email)).like(needle),
                func.lower(col(MarketingContact.name)).like(needle),
            )
        )
    if subscribed is True:
        where.append(col(MarketingContact.unsubscribed_at).is_(None))
    elif subscribed is False:
        where.append(col(MarketingContact.unsubscribed_at).is_not(None))

    total = session.exec(
        select(func.count()).select_from(MarketingContact).where(*where)
    ).one()
    rows = session.exec(
        select(MarketingContact)
        .where(*where)
        .order_by(col(MarketingContact.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return MarketingContactsPublic(
        data=[_contact_public(row) for row in rows], count=int(total)
    )


@router.get("/contacts/ids", response_model=list[uuid.UUID])
def read_contact_ids(
    session: SessionDep, q: str | None = None, subscribed: bool | None = None
) -> Any:
    """Every id matching the current filter, for "select all".

    Selecting all has to mean everybody, not everybody on this page. The
    alternative is a flag on the create call that the server reinterprets, and
    then the count in the interface and the count that is sent can disagree.
    """
    where = []
    if q:
        needle = f"%{q.strip().lower()}%"
        where.append(
            or_(
                func.lower(col(MarketingContact.email)).like(needle),
                func.lower(col(MarketingContact.name)).like(needle),
            )
        )
    if subscribed is True:
        where.append(col(MarketingContact.unsubscribed_at).is_(None))
    elif subscribed is False:
        where.append(col(MarketingContact.unsubscribed_at).is_not(None))
    return list(session.exec(select(MarketingContact.id).where(*where)).all())


@router.post("/contacts", response_model=MarketingContactPublic)
def create_contact(session: SessionDep, body: MarketingContactCreate) -> Any:
    contact = marketing.ensure_contact(
        session,
        email=str(body.email),
        name=body.name,
        source=ContactSource.manual,
    )
    session.commit()
    session.refresh(contact)
    return _contact_public(contact)


@router.post("/contacts/import", response_model=ContactImportResult)
async def import_contacts(
    session: SessionDep, file: Annotated[UploadFile, File()]
) -> Any:
    """Upload a list.

    An upload rather than a script reading a checked-in file, because a list of
    several hundred real addresses is not something a repository should carry.
    Reports every row it could not use instead of refusing the file over one.
    """
    payload = await file.read(MAX_IMPORT_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=422, detail="That file was empty")
    if len(payload) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Files are limited to {MAX_IMPORT_BYTES // (1024 * 1024)} MB",
        )
    return marketing.import_csv(session, payload)


@router.delete("/contacts/{contact_id}", response_model=Message)
def delete_contact(session: SessionDep, contact_id: uuid.UUID) -> Any:
    """Remove an address entirely.

    Not the same as unsubscribing, and the difference matters: a deleted
    address can be imported again tomorrow, an unsubscribed one cannot. Use
    this for a typo, never for somebody who asked to be left alone.
    """
    contact = session.get(MarketingContact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="No such contact")
    session.delete(contact)
    session.commit()
    return Message(message="Contact deleted")


@router.post(
    "/contacts/{contact_id}/unsubscribe", response_model=MarketingContactPublic
)
def unsubscribe_contact(session: SessionDep, contact_id: uuid.UUID) -> Any:
    """Unsubscribe somebody who asked by replying rather than by clicking."""
    contact = session.get(MarketingContact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="No such contact")
    marketing.unsubscribe(session, contact.unsubscribe_token)
    session.commit()
    session.refresh(contact)
    return _contact_public(contact)


# --- campaigns --------------------------------------------------------------


@router.post("/preview", response_model=CampaignPreview)
def preview_campaign(session: SessionDep, body: CampaignPreviewRequest) -> Any:
    """One person's copy of what is currently in the composer.

    Rendered by the same function that sends it, so the preview is the message
    rather than an approximation of it. Given nobody in particular, it uses a
    stand-in so the greeting is still visible.
    """
    contact: MarketingContact | None = None
    if body.contact_id is not None:
        contact = session.get(MarketingContact, body.contact_id)
    if contact is None:
        contact = session.exec(
            select(MarketingContact)
            .where(col(MarketingContact.unsubscribed_at).is_(None))
            .limit(1)
        ).first()
    if contact is None:
        contact = MarketingContact(
            email="somebody@example.com",
            name="Sam Example",
            unsubscribe_token="preview",
        )

    rendered = marketing.render_for(
        contact, subject=body.subject, body_html=body.body_html
    )
    return CampaignPreview(
        to_email=rendered.to,
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
    )


@router.post("/campaigns", response_model=CampaignPublic)
def create_campaign(
    session: SessionDep, user: SessionUser, body: CampaignCreate
) -> Any:
    """Write the campaign and every delivery, then let the worker send them.

    The deliveries are stamped a second apart here rather than paced by the
    sender: the schedule is then a fact in the database, so it survives a
    restart, a half-sent campaign resumes where it stopped, and nothing
    anywhere has to sleep.
    """
    if body.from_email not in settings.MARKETING_FROM_ADDRESSES:
        raise HTTPException(
            status_code=422,
            detail="That is not one of the addresses this deployment can send from",
        )

    where = [col(MarketingContact.unsubscribed_at).is_(None)]
    if not body.all_subscribed:
        if not body.contact_ids:
            raise HTTPException(status_code=422, detail="Choose who this goes to")
        where.append(col(MarketingContact.id).in_(body.contact_ids))

    contacts = session.exec(select(MarketingContact).where(*where)).all()
    if not contacts:
        raise HTTPException(
            status_code=422, detail="Nobody on that list is still subscribed"
        )
    if len(contacts) > settings.MARKETING_MAX_RECIPIENTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A campaign is limited to {settings.MARKETING_MAX_RECIPIENTS} "
                "recipients"
            ),
        )

    started = marketing.now()
    campaign = MarketingCampaign(
        name=body.name or body.subject[:200],
        from_email=str(body.from_email),
        subject=body.subject,
        body_html=body.body_html,
        status=CampaignStatus.sending,
        created_by=user.id,
        total=len(contacts),
        started_at=started,
    )
    session.add(campaign)
    session.flush()

    for index, contact in enumerate(contacts):
        session.add(
            MarketingDelivery(
                campaign_id=campaign.id,
                contact_id=contact.id,
                to_email=contact.email,
                # One second apart. This single line is the send rate.
                send_after=started + timedelta(seconds=index),
            )
        )
    session.commit()
    session.refresh(campaign)
    return _campaign_public(campaign)


@router.get("/campaigns", response_model=CampaignsPublic)
def read_campaigns(
    session: SessionDep, limit: Annotated[int, Query(le=100)] = 25
) -> Any:
    total = session.exec(select(func.count()).select_from(MarketingCampaign)).one()
    rows = session.exec(
        select(MarketingCampaign)
        .order_by(col(MarketingCampaign.created_at).desc())
        .limit(limit)
    ).all()
    return CampaignsPublic(
        data=[_campaign_public(row) for row in rows], count=int(total)
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignPublic)
def read_campaign(session: SessionDep, campaign_id: uuid.UUID) -> Any:
    campaign = session.get(MarketingCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="No such campaign")
    return _campaign_public(campaign)


@router.get("/campaigns/{campaign_id}/deliveries", response_model=DeliveriesPublic)
def read_deliveries(
    session: SessionDep,
    campaign_id: uuid.UUID,
    status: DeliveryStatus | None = None,
    skip: int = 0,
    limit: Annotated[int, Query(le=500)] = 100,
) -> Any:
    """What happened to each address. Sent first, because that is the progress."""
    campaign = session.get(MarketingCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="No such campaign")

    where = [MarketingDelivery.campaign_id == campaign_id]
    if status is not None:
        where.append(MarketingDelivery.status == status)
    total = session.exec(
        select(func.count()).select_from(MarketingDelivery).where(*where)
    ).one()
    rows = session.exec(
        select(MarketingDelivery)
        .where(*where)
        .order_by(col(MarketingDelivery.send_after))
        .offset(skip)
        .limit(limit)
    ).all()
    return DeliveriesPublic(
        data=[
            DeliveryPublic(
                id=row.id,
                to_email=row.to_email,
                status=row.status,
                send_after=row.send_after,
                sent_at=row.sent_at,
                attempts=row.attempts,
                error=row.error,
            )
            for row in rows
        ],
        count=int(total),
    )


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignPublic)
def cancel_campaign(session: SessionDep, campaign_id: uuid.UUID) -> Any:
    """Stop the rest of it.

    Everything already sent stays sent; there is no unsending. What this buys
    is that the remaining messages never go, and the claim loop confirms that
    for every row it picks up rather than trusting this to have raced ahead.
    """
    campaign = session.get(MarketingCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="No such campaign")
    if campaign.status == CampaignStatus.sending:
        campaign.status = CampaignStatus.cancelled
        campaign.finished_at = marketing.now()
        session.add(campaign)
        session.commit()
        session.refresh(campaign)
    return _campaign_public(campaign)
