"""Sharing a page: with a person, with someone who is not here yet, or by link.

Three ways to give access, with one rule between them: access is granted to a
*confirmed identity*, or to nobody.

* **An account that exists** gets a share immediately, and an email saying so.
* **An address with no account** gets an invitation. It is not access. It turns
  into a share the moment that address is confirmed on an account, which is the
  first moment anyone can say the person reading the email owns it. Somebody who
  guesses an invitation link gains nothing by opening it.
* **A public link** makes one page readable by anyone holding it. The link is a
  random slug rather than the page id, so revoking and re-sharing produces a new
  link instead of quietly re-publishing to whoever kept the old one.

Nothing here widens what the sharer themselves can reach, and none of it touches
the space around the page: a share is a grant on one page.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Document,
    DocumentShare,
    ShareInvitation,
    ShareRole,
    User,
)

logger = logging.getLogger(__name__)

PUBLIC_SLUG_BYTES = 12


def now() -> datetime:
    return datetime.now(UTC)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def new_public_slug() -> str:
    """Unguessable, and short enough to paste into a message."""
    return secrets.token_urlsafe(PUBLIC_SLUG_BYTES)[:22]


def display_name(user: User | None) -> str:
    """How a sharer is named in an email. Never an empty string."""
    if user is None:
        return settings.APP_NAME
    return (user.full_name or "").strip() or user.email


def document_url(document_id: object) -> str:
    """Where a person goes to read a page they have access to."""
    return f"{settings.FRONTEND_HOST.rstrip('/')}/d/{document_id}"


def invitation_url(token: str) -> str:
    return f"{settings.FRONTEND_HOST.rstrip('/')}/invite?token={token}"


def public_url(slug: str) -> str:
    return f"{settings.FRONTEND_HOST.rstrip('/')}/p/{slug}"


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def pending_invitation(
    session: Session, document_id: object, email: str
) -> ShareInvitation | None:
    return session.exec(
        select(ShareInvitation).where(
            ShareInvitation.document_id == document_id,
            ShareInvitation.email == normalise_email(email),
            col(ShareInvitation.accepted_at).is_(None),
        )
    ).first()


def recipient_count(session: Session, document_id: object) -> int:
    """How many people this page is shared with, counting pending invitations.

    An invitation counts because it is a promise of access: not counting it
    would let somebody invite a thousand addresses and only hit the limit once
    they started signing up.
    """
    shares = session.exec(
        select(DocumentShare).where(DocumentShare.document_id == document_id)
    ).all()
    invitations = session.exec(
        select(ShareInvitation).where(
            ShareInvitation.document_id == document_id,
            col(ShareInvitation.accepted_at).is_(None),
        )
    ).all()
    return len(shares) + len(invitations)


def invite(
    session: Session,
    *,
    document: Document,
    email: str,
    role: ShareRole,
    invited_by: User,
) -> tuple[ShareInvitation, str]:
    """Record an invitation and return it with its one-use token.

    Re-inviting the same address replaces the previous invitation rather than
    stacking another one beside it, so the newest email is the one that works
    and the role is whatever was chosen most recently.
    """
    address = normalise_email(email)
    existing = pending_invitation(session, document.id, address)
    token = new_invitation_token()
    expires = now() + timedelta(days=settings.SHARE_INVITE_TTL_DAYS)

    if existing is not None:
        existing.role = role
        existing.token_hash = hash_token(token)
        existing.expires_at = expires
        existing.invited_by = invited_by.id
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing, token

    record = ShareInvitation(
        document_id=document.id,
        email=address,
        role=role,
        invited_by=invited_by.id,
        token_hash=hash_token(token),
        expires_at=expires,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, token


def find_invitation(session: Session, token: str) -> ShareInvitation | None:
    return session.exec(
        select(ShareInvitation).where(ShareInvitation.token_hash == hash_token(token))
    ).first()


def redeem_for(session: Session, user: User) -> list[DocumentShare]:
    """Turn every pending invitation for this address into a real share.

    Called when an address is confirmed, never before. That is the whole
    security argument: an invitation names an address, and confirming the
    address is what proves the person holding the account owns it.

    Expired invitations are left alone rather than deleted, so the interface can
    still explain why a link did nothing.
    """
    address = normalise_email(user.email)
    pending = session.exec(
        select(ShareInvitation).where(
            ShareInvitation.email == address,
            col(ShareInvitation.accepted_at).is_(None),
            col(ShareInvitation.expires_at) > now(),
        )
    ).all()

    created: list[DocumentShare] = []
    stamped = now()
    for record in pending:
        document = session.get(Document, record.document_id)
        if document is None:
            # The page went away while the invitation sat in a mailbox.
            record.accepted_at = stamped
            record.accepted_user_id = user.id
            session.add(record)
            continue

        already = session.exec(
            select(DocumentShare).where(
                DocumentShare.document_id == record.document_id,
                DocumentShare.user_id == user.id,
            )
        ).first()
        if already is None:
            share = DocumentShare(
                document_id=record.document_id,
                user_id=user.id,
                role=record.role,
                created_by=record.invited_by,
            )
            session.add(share)
            created.append(share)

        record.accepted_at = stamped
        record.accepted_user_id = user.id
        session.add(record)

    if pending:
        session.commit()
    return created


# ---------------------------------------------------------------------------
# Public links
# ---------------------------------------------------------------------------


def publish(session: Session, document: Document, by: User) -> str:
    """Make a page readable by link, and return the slug.

    Publishing twice keeps the existing link: someone re-opening the dialog to
    copy the address again should not silently break the copy they already sent.
    """
    if not document.public_slug:
        document.public_slug = new_public_slug()
        document.public_shared_at = now()
        document.public_shared_by = by.id
        session.add(document)
        session.commit()
        session.refresh(document)
    return str(document.public_slug)


def unpublish(session: Session, document: Document) -> None:
    """Withdraw the link. The old one never works again, by design."""
    document.public_slug = None
    document.public_shared_at = None
    document.public_shared_by = None
    session.add(document)
    session.commit()


def find_public(session: Session, identifier: str) -> Document | None:
    """A publicly shared page, by its slug or by its own id.

    Both work because a page that is public is public: its id is no more secret
    than its slug. Anything *not* currently published is invisible here, which
    is what makes withdrawing a link effective.
    """
    document = session.exec(
        select(Document).where(Document.public_slug == identifier)
    ).first()
    if document is not None:
        return document

    try:
        import uuid as _uuid

        candidate = session.get(Document, _uuid.UUID(identifier))
    except ValueError, AttributeError:
        return None
    if candidate is not None and candidate.public_slug:
        return candidate
    return None
