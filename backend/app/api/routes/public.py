"""The only endpoints in this API that answer without a credential.

Two things are readable without signing in, and both are readable because
somebody deliberately made them so:

* a page shared by link, and the images inside it,
* the bare facts of an invitation, so its landing page can say who shared what.

Everything here is written to give away nothing beyond the one thing that was
shared. No space, no folder, no neighbouring pages, no author ids, no version
history. A link is a credential, so it buys exactly what it names and nothing
around it.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import SessionDep, StorageDep
from app.api.routes.attachments import serve_headers
from app.core.config import settings
from app.models import (
    Attachment,
    Document,
    InvitationPreview,
    Namespace,
    PublicDocument,
    User,
)
from app.services import sharing
from app.services.cloning import referenced_attachment_ids

router = APIRouter(prefix="/public", tags=["public"])

_ATTACHMENT_PATH = re.compile(
    rf"{re.escape(settings.API_V1_STR)}/attachments/([0-9a-fA-F-]{{36}})/download"
)


def _public_html(document: Document) -> str:
    """Rewrite image links so they work without a session.

    The stored markup points at the authenticated download route, which is
    correct for everyone who can open the page normally and useless to a reader
    who only has the link. Rewriting here, rather than storing a second copy,
    means the page has one source of truth and publishing changes nothing about
    it.
    """
    slug = document.public_slug

    def swap(match: re.Match[str]) -> str:
        return f"{settings.API_V1_STR}/public/{slug}/attachments/{match.group(1)}"

    return _ATTACHMENT_PATH.sub(swap, document.content_html or "")


@router.get("/documents/{identifier}", response_model=PublicDocument)
def read_public_document(session: SessionDep, identifier: str) -> Any:
    """Read a page that has been shared by link.

    `identifier` is the link's slug, or the page's own id - a published page is
    published either way. A page that is not currently shared by link is not
    found here, which is what makes withdrawing a link effective immediately.
    """
    document = sharing.find_public(session, identifier)
    if document is None:
        raise HTTPException(status_code=404, detail="No page is shared at this link")

    sharer = (
        session.get(User, document.public_shared_by)
        if document.public_shared_by
        else None
    )
    return PublicDocument(
        id=document.id,
        slug=str(document.public_slug),
        title=document.title,
        doc_type=document.doc_type,
        content_html=_public_html(document),
        updated_at=document.updated_at,
        shared_by=sharing.display_name(sharer) if sharer else None,
    )


@router.get("/{slug}/attachments/{attachment_id}")
def read_public_attachment(
    session: SessionDep,
    storage: StorageDep,
    slug: str,
    attachment_id: uuid.UUID,
) -> Any:
    """An image embedded in a page shared by link.

    Reachable only through the slug of the page that embeds it, and only if the
    page actually references it. Publishing a page does not publish the rest of
    the space's files.
    """
    document = sharing.find_public(session, slug)
    if document is None or document.public_slug != slug:
        raise HTTPException(status_code=404, detail="Not found")
    if attachment_id not in referenced_attachment_ids(document.content_html or ""):
        raise HTTPException(status_code=404, detail="Not found")

    attachment = session.get(Attachment, attachment_id)
    if attachment is None or attachment.namespace_id != document.namespace_id:
        raise HTTPException(status_code=404, detail="Not found")

    stored = storage.open(attachment.object_key)
    media_type, headers = serve_headers(attachment)
    # Public, but not indexed: a shared link is meant for the people it was sent
    # to, not for a search engine.
    headers["Cache-Control"] = "public, max-age=300"
    headers["X-Robots-Tag"] = "noindex"
    return StreamingResponse(
        stored.stream,
        media_type=media_type,
        headers=headers,
        background=None,
    )


@router.get("/invitations/{token}", response_model=InvitationPreview)
def read_invitation(session: SessionDep, token: str) -> Any:
    """What an invitation link is for, so its landing page can explain itself.

    Holding the link is the only way to reach this, and whoever holds it was
    already told by email who shared what. It grants nothing: access still comes
    from creating an account on that address and confirming it.
    """
    record = sharing.find_invitation(session, token)
    if record is None:
        raise HTTPException(status_code=404, detail="This invitation is not valid")
    if record.expires_at <= sharing.now():
        raise HTTPException(
            status_code=410,
            detail="This invitation has expired. Ask for a new one.",
        )

    inviter = session.get(User, record.invited_by) if record.invited_by else None

    if record.namespace_id is not None:
        namespace = session.get(Namespace, record.namespace_id)
        if namespace is None:
            raise HTTPException(
                status_code=404, detail="The shared space no longer exists"
            )
        return InvitationPreview(
            email=record.email,
            target="space",
            namespace_id=namespace.id,
            document_title=namespace.name,
            shared_by=sharing.display_name(inviter),
            role=record.role,
            expires_at=record.expires_at,
            already_accepted=record.accepted_at is not None,
        )

    document = session.get(Document, record.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The shared page no longer exists")
    return InvitationPreview(
        email=record.email,
        target="page",
        document_id=document.id,
        document_title=document.title,
        shared_by=sharing.display_name(inviter),
        role=record.role,
        expires_at=record.expires_at,
        already_accepted=record.accepted_at is not None,
    )
