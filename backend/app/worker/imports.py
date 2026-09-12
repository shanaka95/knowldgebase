"""Turn an uploaded PDF or image into a page.

    queued → rendering → parsing (page by page) → creating → done

The upload is fetched from object storage, rendered to page images, parsed by
MinerU (or the LLM fallback), and written as a normal document - which then flows
into the usual embedding pipeline. The original file is kept as the page's source
attachment, so it can be opened at any time.

Cancellation and retries mirror the embedding pipeline: the job row is polled
between pages, and transient failures back off and requeue.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.content import html_to_text
from app.models import ImportStatus
from app.services.parsing import (
    LLMPageParser,
    MinerUParser,
    UnsupportedFileType,
    parse_document,
    split_leading_heading,
)
from app.services.storage import ObjectStorage
from app.worker import queue
from app.worker.errors import JobCancelled

logger = logging.getLogger(__name__)


def _read_object(storage: ObjectStorage, key: str) -> bytes:
    stored = storage.open(key)
    try:
        return b"".join(stored.stream)
    finally:
        stored.close()


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _title_and_body(job: queue.ImportSnapshot, content_html: str) -> tuple[str, str]:
    """Decide the page title and strip a duplicated leading heading.

    * No title given -> the document's own opening heading becomes the title.
    * Title given that matches the heading -> drop the heading, keep the title.
    * Title given that differs -> keep both; the heading is real content.
    """
    heading, rest = split_leading_heading(content_html)
    given = (job.title or "").strip()

    if given:
        if heading and _normalize(heading) == _normalize(given):
            return given, rest
        return given, content_html
    if heading:
        return heading[:300], rest

    # Last resort. For a combined import `job.filename` is a summary label
    # ("scan-1.pdf +2 more"), so the first part's own name reads better.
    source = job.parts[0].filename if job.parts else job.filename
    stem = source.rsplit(".", 1)[0].strip()
    return stem or "Imported document", content_html


def _join(parts: list[str]) -> str:
    """Put several parsed files together as one page.

    A horizontal rule between them, because the seam is real: the reader should
    be able to see where one uploaded file ended and the next began. Nothing
    else is inserted - no filenames, no headings - since the parts are usually
    one document that happened to arrive in pieces, and an invented heading
    would then appear in the middle of it.
    """
    kept = [p.strip() for p in parts if p and p.strip()]
    if not kept:
        return ""
    return '\n<hr data-import-seam="true">\n'.join(kept)


async def run_import(
    job: queue.ImportSnapshot,
    *,
    storage: ObjectStorage,
    mineru: MinerUParser | None = None,
    llm: LLMPageParser | None = None,
) -> ImportStatus:
    """Run one claimed import job to a terminal state. Never raises."""
    log = logging.LoggerAdapter(logger, {"import": str(job.id)[:8]})

    async def ensure_active() -> None:
        if await asyncio.to_thread(queue.import_cancel_requested, job.id):
            raise JobCancelled()

    try:
        await ensure_active()

        # --- fetch + render ---------------------------------------------------
        await asyncio.to_thread(
            queue.set_import_progress, job.id, status=ImportStatus.rendering
        )
        # An ordinary import is one file; a combined one is several, parsed in
        # the order they were chosen and joined into a single page.
        uploads = job.parts or [
            queue.ImportPart(
                position=0,
                filename=job.filename,
                content_type=job.content_type,
                size=job.size,
                object_key=job.object_key,
            )
        ]

        # Page counts are reported across the whole set, so a person watching a
        # five-file import sees one honest progress figure rather than five that
        # each restart at zero.
        pages_before = 0
        html_parts: list[str] = []
        parsers: list[str] = []
        total_pages = 0

        for part in uploads:
            await ensure_active()
            data = await asyncio.to_thread(_read_object, storage, part.object_key)

            async def on_page(
                done: int, total: int, _before: int = pages_before
            ) -> None:
                await asyncio.to_thread(
                    queue.set_import_progress,
                    job.id,
                    status=ImportStatus.parsing,
                    pages_total=_before + total,
                    pages_done=_before + done,
                )
                await ensure_active()

            parsed = await parse_document(
                data,
                part.content_type,
                filename=part.filename,
                prompt=job.prompt,
                mineru=mineru,
                llm=llm,
                on_page=on_page,
            )
            html_parts.append(parsed.html)
            parsers.append(str(parsed.parser))
            pages_before += parsed.page_count
            total_pages += parsed.page_count

        parser_used = parsers[0] if parsers else None
        await asyncio.to_thread(
            queue.set_import_progress,
            job.id,
            status=ImportStatus.creating,
            pages_total=total_pages,
            pages_done=total_pages,
            parser=parser_used,
        )
        await ensure_active()

        # --- create the page --------------------------------------------------
        title, content_html = _title_and_body(job, _join(html_parts))
        content_text = html_to_text(content_html)
        if not content_text.strip():
            raise UnsupportedFileType(
                "No text could be extracted from this file. If it is a scan, "
                "try a higher-resolution copy."
            )

        document_id, attachment_id = await asyncio.to_thread(
            queue.create_document_from_import,
            job,
            title=title,
            content_html=content_html,
            content_text=content_text,
        )
        await asyncio.to_thread(
            queue.finish_import,
            job.id,
            ImportStatus.done,
            document_id=document_id,
            attachment_id=attachment_id,
        )
        log.info(
            "imported %s (%s pages, parser=%s) → doc %s",
            job.filename,
            total_pages,
            parser_used,
            str(document_id)[:8],
        )
        return ImportStatus.done

    except JobCancelled, asyncio.CancelledError:
        await asyncio.to_thread(
            queue.finish_import,
            job.id,
            ImportStatus.cancelled,
            error="cancelled",
        )
        return ImportStatus.cancelled

    except UnsupportedFileType as exc:
        # Not retryable: the file will not become parseable on a second attempt.
        await asyncio.to_thread(
            queue.finish_import, job.id, ImportStatus.failed, error=str(exc)
        )
        log.warning("import %s rejected: %s", job.filename, exc)
        return ImportStatus.failed

    except Exception as exc:  # noqa: BLE001 - model server hiccups, storage, …
        status = await asyncio.to_thread(queue.retry_or_fail_import, job.id, str(exc))
        log.warning(
            "import %s failed (%s); %s",
            job.filename,
            exc,
            "will retry" if status == ImportStatus.queued else "giving up",
        )
        return status
