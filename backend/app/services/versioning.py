"""A page's history: every version it has had, and its content at each.

The rule for what counts as a version is the one the product already used for
deciding when to re-index: a change to the title or the text. Re-formatting the
same words is not a new version, which keeps the history a list of things
somebody actually did rather than a list of keystrokes.

Recording happens wherever a page's content is written - created, edited,
imported, copied - through `record_version`, so no path can add content the
history does not know about.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, delete, func, select

from app.core.config import settings
from app.models import Document, DocumentVersion
from app.services.language import detect


def detect_document_language(title: str, content_text: str) -> str | None:
    """The language a page is written in, from its own words.

    The title joins the text because a page can be a table of figures with a
    title that is the only prose on it.
    """
    detected = detect(f"{title}\n{content_text}")
    return detected.code if detected else None


def record_version(
    session: Session,
    document: Document,
    *,
    created_by: uuid.UUID | None = None,
) -> DocumentVersion | None:
    """Store the page as it now stands, under its current version number.

    Called after the document row has been updated, so it reads the new content
    from the document itself. Writing the same version twice is not an error -
    the second call simply updates the row - because the alternative is a
    unique-constraint violation on a code path that has nothing to do with
    versioning.
    """
    existing = session.exec(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == document.version,
        )
    ).first()

    if existing is not None:
        existing.title = document.title
        existing.content_html = document.content_html
        existing.content_text = document.content_text
        existing.doc_type = document.doc_type
        existing.language = document.language
        session.add(existing)
        return existing

    version = DocumentVersion(
        document_id=document.id,
        version=document.version,
        title=document.title,
        content_html=document.content_html,
        content_text=document.content_text,
        doc_type=document.doc_type,
        language=document.language,
        created_by=created_by or document.updated_by,
    )
    session.add(version)
    _prune(session, document.id)
    return version


def _prune(session: Session, document_id: uuid.UUID) -> None:
    """Keep the history bounded, oldest first - but never drop version 1.

    Version 1 is what an imported page's original file corresponds to, so
    dropping it would leave the page unable to say what the file it came from
    says.
    """
    keep = settings.DOCUMENT_VERSION_HISTORY
    total = session.exec(
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
    ).one()
    if int(total) <= keep:
        return
    stale = session.exec(
        select(col(DocumentVersion.id))
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version != 1,
        )
        .order_by(col(DocumentVersion.version))
        .limit(int(total) - keep)
    ).all()
    if stale:
        session.exec(delete(DocumentVersion).where(col(DocumentVersion.id).in_(stale)))


def list_versions(session: Session, document_id: uuid.UUID) -> list[DocumentVersion]:
    """Newest first, which is the order a version picker reads in."""
    return list(
        session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(col(DocumentVersion.version).desc())
        ).all()
    )


def get_version(
    session: Session, document_id: uuid.UUID, version: int
) -> DocumentVersion | None:
    return session.exec(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version == version,
        )
    ).first()
