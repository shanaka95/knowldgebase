"""Copying a page so that the copy stands on its own.

The hard part is not the text. A page usually embeds images, and those images
are attachments belonging to the *original's* space. A copy that kept pointing
at them would render for the person who already had access and break for
everybody else - which is most of the reason anyone clones a shared page in the
first place.

So the images come too: each referenced attachment is copied into the
destination space, under a new key, and the markup is rewritten to point at the
copy. The originals are untouched.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from pathlib import PurePosixPath

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import Attachment
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

# Matches the download path the editor writes into img src, and the data
# attribute the image node keeps alongside it.
_REF = re.compile(
    rf"{re.escape(settings.API_V1_STR)}/attachments/"
    r"([0-9a-fA-F-]{36})/download"
)
_DATA_ATTR = re.compile(r'data-attachment-id="([0-9a-fA-F-]{36})"')


def referenced_attachment_ids(html: str) -> list[uuid.UUID]:
    """Every attachment the markup points at, in the order it first appears."""
    found: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for pattern in (_REF, _DATA_ATTR):
        for match in pattern.finditer(html or ""):
            try:
                value = uuid.UUID(match.group(1))
            except ValueError:
                continue
            if value not in seen:
                seen.add(value)
                found.append(value)
    return found


def copy_embedded_attachments(
    session: Session,
    storage: ObjectStorage,
    *,
    html: str,
    source_namespace_id: uuid.UUID,
    target_namespace_id: uuid.UUID,
    uploader_id: uuid.UUID | None,
) -> tuple[str, list[Attachment]]:
    """Duplicate the images a page embeds, and rewrite the page to use them.

    Returns the rewritten markup and the new attachments, which the caller
    attaches to the new page once it has an id.

    Attachments that belong to a different space than the page are skipped
    rather than copied: they are not the page's to duplicate. An object missing
    from storage is skipped too, leaving that one image pointing at the original
    - a copy with one broken image beats refusing to copy at all.
    """
    if not html:
        return html, []

    ids = referenced_attachment_ids(html)
    if not ids:
        return html, []

    rows = session.exec(
        select(Attachment).where(
            col(Attachment.id).in_(ids),
            Attachment.namespace_id == source_namespace_id,
        )
    ).all()
    by_id = {row.id: row for row in rows}

    created: list[Attachment] = []
    mapping: dict[str, str] = {}

    for old_id in ids:
        original = by_id.get(old_id)
        if original is None:
            continue
        try:
            stored = storage.open(original.object_key)
            try:
                payload = b"".join(stored.stream)
            finally:
                stored.close()
        except Exception as exc:  # noqa: BLE001 - storage drivers vary
            logger.warning(
                "clone: could not read %s, leaving the reference alone: %s",
                original.object_key,
                exc,
            )
            continue

        new_id = uuid.uuid4()
        suffix = PurePosixPath(original.filename).suffix.lower()[:16]
        key = f"ns/{target_namespace_id}/{new_id}{suffix}"
        storage.put(key, io.BytesIO(payload), len(payload), original.content_type)

        copy = Attachment(
            id=new_id,
            namespace_id=target_namespace_id,
            uploader_id=uploader_id,
            filename=original.filename,
            content_type=original.content_type,
            size=len(payload),
            object_key=key,
        )
        session.add(copy)
        created.append(copy)
        mapping[str(old_id)] = str(new_id)

    if not mapping:
        return html, []

    def swap(match: re.Match[str]) -> str:
        old = match.group(1)
        return match.group(0).replace(old, mapping.get(old, old))

    rewritten = _REF.sub(swap, html)
    rewritten = _DATA_ATTR.sub(swap, rewritten)
    return rewritten, created
