"""Import pipeline: upload -> parsed pages -> document + source attachment."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from PIL import Image
from sqlmodel import Session, select

from app.models import (
    Attachment,
    Document,
    EmbeddingJob,
    ImportFile,
    ImportJob,
    ImportParser,
    ImportStatus,
)
from app.services.storage import InMemoryStorage
from app.worker import imports as imports_mod
from app.worker import queue
from tests.worker.conftest import make_namespace, make_user

pytestmark = pytest.mark.anyio


def _png_bytes(size: tuple[int, int] = (40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


def _make_import(
    db: Session,
    *,
    content_type: str = "image/png",
    filename: str = "scan.png",
    title: str | None = None,
    prompt: str | None = None,
    payload: bytes | None = None,
    storage: InMemoryStorage | None = None,
) -> tuple[ImportJob, InMemoryStorage]:
    user = make_user(db)
    ns = make_namespace(db, user)
    payload = payload if payload is not None else _png_bytes()
    storage = storage or InMemoryStorage()
    job = ImportJob(
        namespace_id=ns.id,
        created_by=user.id,
        title=title,
        prompt=prompt,
        filename=filename,
        content_type=content_type,
        size=len(payload),
        object_key=f"imports/{uuid.uuid4()}.png",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    storage.put(job.object_key, io.BytesIO(payload), len(payload), content_type)
    return job, storage


class FakeMinerU:
    """Stands in for the MinerU server; records the pages it was given."""

    def __init__(self, available: bool = True, html: str | None = None) -> None:
        self._available = available
        self._html = html or "<h1>Invoice 42</h1><p>Total due 1,250 EUR</p>"
        self.pages_seen = 0
        self.base_url = "http://fake-mineru/v1"

    async def available(self) -> bool:
        return self._available

    def parse_page(self, image: Any) -> tuple[str, int]:
        self.pages_seen += 1
        return self._html, 2


class FakeLLMParser:
    def __init__(self, html: str = "<p>llm transcription</p>") -> None:
        self._html = html
        self.pages_seen = 0

    async def parse_page(
        self, image: Any, prompt: str | None = None
    ) -> tuple[str, int]:
        self.pages_seen += 1
        return self._html, 1


async def _claim(job: ImportJob) -> queue.ImportSnapshot:
    """Claim until this job comes up.

    Other tests leave queued imports behind, and claiming is first-come: taking
    a single batch would sometimes return somebody else's jobs and never this
    one.
    """
    import asyncio

    for _ in range(50):
        claimed = await asyncio.to_thread(queue.claim_import_jobs, "test-worker", 20)
        if not claimed:
            break
        match = [c for c in claimed if c.id == job.id]
        if match:
            return match[0]
    raise AssertionError("the job should have been claimable")


async def test_import_creates_document_and_keeps_original_file(
    db_session: Session,
) -> None:
    job, storage = _make_import(db_session, title="Invoice 42")
    snapshot = await _claim(job)
    mineru = FakeMinerU()

    status = await imports_mod.run_import(snapshot, storage=storage, mineru=mineru)  # type: ignore[arg-type]

    assert status == ImportStatus.done
    assert mineru.pages_seen == 1
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None
    assert row.status == ImportStatus.done
    assert row.parser == ImportParser.mineru
    assert row.pages_total == 1 and row.pages_done == 1
    assert row.document_id and row.attachment_id

    document = db_session.get(Document, row.document_id)
    assert document is not None
    assert document.title == "Invoice 42"
    # the heading matched the title, so it is not repeated in the body
    assert "<h1>" not in document.content_html
    assert "Total due" in document.content_text

    # the upload survives as the page's source attachment, pointing at the very
    # same object - nothing was copied
    attachment = db_session.get(Attachment, row.attachment_id)
    assert attachment is not None
    assert attachment.object_key == job.object_key
    assert attachment.document_id == document.id
    assert document.source_attachment_id == attachment.id
    assert storage.exists(job.object_key)

    # and the page is queued for embedding like any other
    queued = db_session.exec(
        select(EmbeddingJob).where(EmbeddingJob.document_id == document.id)
    ).all()
    assert len(queued) == 1


async def test_title_falls_back_to_the_filename(db_session: Session) -> None:
    """Only when the parsed page has no heading of its own to promote."""
    job, storage = _make_import(db_session, filename="Quarterly Report.png", title=None)
    snapshot = await _claim(job)

    await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=FakeMinerU(html="<p>Just a body, no heading.</p>"),  # type: ignore[arg-type]
    )

    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.document_id
    document = db_session.get(Document, row.document_id)
    assert document is not None
    assert document.title == "Quarterly Report"


async def test_document_heading_becomes_the_title_and_is_not_repeated(
    db_session: Session,
) -> None:
    """A parsed page opens with its own title; showing it twice reads badly."""
    job, storage = _make_import(db_session, title=None, filename="scan-001.png")
    snapshot = await _claim(job)

    await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=FakeMinerU(html="<h1>Invoice 42</h1><p>Total due 1,250 EUR</p>"),  # type: ignore[arg-type]
    )

    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.document_id
    document = db_session.get(Document, row.document_id)
    assert document is not None
    # the heading is promoted to the title instead of the meaningless filename
    assert document.title == "Invoice 42"
    assert "<h1>" not in document.content_html
    assert "Total due" in document.content_text


async def test_a_given_title_matching_the_heading_drops_the_heading(
    db_session: Session,
) -> None:
    job, storage = _make_import(db_session, title="invoice 42")
    snapshot = await _claim(job)

    await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=FakeMinerU(html="<h1>Invoice 42</h1><p>Total due</p>"),  # type: ignore[arg-type]
    )

    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.document_id
    document = db_session.get(Document, row.document_id)
    assert document is not None
    assert document.title == "invoice 42"
    assert "<h1>" not in document.content_html


async def test_a_different_given_title_keeps_the_heading(db_session: Session) -> None:
    job, storage = _make_import(db_session, title="August invoices")
    snapshot = await _claim(job)

    await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=FakeMinerU(html="<h1>Invoice 42</h1><p>Total due</p>"),  # type: ignore[arg-type]
    )

    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.document_id
    document = db_session.get(Document, row.document_id)
    assert document is not None
    assert document.title == "August invoices"
    assert "<h1>Invoice 42</h1>" in document.content_html, "a real heading is content"


async def test_falls_back_to_the_llm_when_mineru_is_down(db_session: Session) -> None:
    job, storage = _make_import(db_session, prompt="Keep the tables")
    snapshot = await _claim(job)
    mineru = FakeMinerU(available=False)
    llm = FakeLLMParser()

    status = await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=mineru,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
    )

    assert status == ImportStatus.done
    assert mineru.pages_seen == 0
    assert llm.pages_seen == 1
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.parser == ImportParser.llm


async def test_empty_transcription_fails_without_retrying(db_session: Session) -> None:
    job, storage = _make_import(db_session)
    snapshot = await _claim(job)

    status = await imports_mod.run_import(
        snapshot,
        storage=storage,
        mineru=FakeMinerU(html="   "),  # type: ignore[arg-type]
    )

    assert status == ImportStatus.failed
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None
    assert row.attempts == 0, "a hopeless file must not be retried"
    assert row.error and "No text" in row.error
    assert row.document_id is None


async def test_transient_failure_is_retried_with_backoff(db_session: Session) -> None:
    job, storage = _make_import(db_session)
    snapshot = await _claim(job)

    class Exploding(FakeMinerU):
        def parse_page(self, image: Any) -> tuple[str, int]:
            raise RuntimeError("model server exploded")

    status = await imports_mod.run_import(snapshot, storage=storage, mineru=Exploding())  # type: ignore[arg-type]

    assert status == ImportStatus.queued
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None
    assert row.attempts == 1
    assert row.status == ImportStatus.queued
    assert row.error and "exploded" in row.error


async def test_cancellation_stops_before_creating_a_document(
    db_session: Session,
) -> None:
    job, storage = _make_import(db_session)
    snapshot = await _claim(job)
    row = db_session.get(ImportJob, job.id)
    assert row is not None
    row.cancel_requested = True
    db_session.add(row)
    db_session.commit()

    status = await imports_mod.run_import(
        snapshot, storage=storage, mineru=FakeMinerU()
    )  # type: ignore[arg-type]

    assert status == ImportStatus.cancelled
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None
    assert row.status == ImportStatus.cancelled
    assert row.document_id is None


async def test_unsupported_file_type_is_rejected(db_session: Session) -> None:
    job, storage = _make_import(
        db_session,
        content_type="application/zip",
        filename="archive.zip",
        payload=b"PK\x03\x04",
    )
    snapshot = await _claim(job)

    status = await imports_mod.run_import(
        snapshot, storage=storage, mineru=FakeMinerU()
    )  # type: ignore[arg-type]

    assert status == ImportStatus.failed
    db_session.expire_all()
    row = db_session.get(ImportJob, job.id)
    assert row is not None and row.error and "application/zip" in row.error


async def test_claim_is_exclusive_and_skips_cancelled(db_session: Session) -> None:
    job, _ = _make_import(db_session)
    cancelled, _ = _make_import(db_session)
    row = db_session.get(ImportJob, cancelled.id)
    assert row is not None
    row.cancel_requested = True
    db_session.add(row)
    db_session.commit()

    first = await _claim(job)
    assert first.id == job.id

    import asyncio

    again = await asyncio.to_thread(queue.claim_import_jobs, "other-worker", 10)
    ids = {c.id for c in again}
    assert job.id not in ids, "a claimed job must not be handed out twice"
    assert cancelled.id not in ids, "a cancelled job must not be claimed"


# ---------------------------------------------------------------------------
# Several files combined into one page
# ---------------------------------------------------------------------------


def _make_combined_import(
    db: Session, filenames: list[str], *, title: str | None = None
) -> tuple[ImportJob, InMemoryStorage]:
    user = make_user(db)
    ns = make_namespace(db, user)
    storage = InMemoryStorage()
    payload = _png_bytes()

    job = ImportJob(
        namespace_id=ns.id,
        created_by=user.id,
        title=title,
        filename=f"{filenames[0]} +{len(filenames) - 1} more",
        content_type="image/png",
        size=len(payload) * len(filenames),
        object_key=f"imports/{uuid.uuid4()}-0.png",
    )
    db.add(job)
    db.flush()
    for position, name in enumerate(filenames):
        key = f"imports/{job.id}-{position}.png"
        storage.put(key, io.BytesIO(payload), len(payload), "image/png")
        db.add(
            ImportFile(
                job_id=job.id,
                position=position,
                filename=name,
                content_type="image/png",
                size=len(payload),
                object_key=key,
            )
        )
        if position == 0:
            job.object_key = key
    db.add(job)
    db.commit()
    db.refresh(job)
    return job, storage


class CountingParser:
    """Returns a different body for each page so the join can be checked."""

    def __init__(self) -> None:
        self.pages_seen = 0
        self.base_url = "http://fake-mineru/v1"

    async def available(self) -> bool:
        return True

    def parse_page(self, image: Any) -> tuple[str, int]:
        self.pages_seen += 1
        return f"<p>Part {self.pages_seen}</p>", 1


async def test_combined_files_become_one_page_in_order(db_session: Session) -> None:
    job, storage = _make_combined_import(
        db_session, ["a.png", "b.png", "c.png"], title="Site survey"
    )
    parser = CountingParser()

    status = await imports_mod.run_import(
        await _claim(job),
        storage=storage,
        mineru=parser,  # type: ignore[arg-type]
    )
    assert status == ImportStatus.done
    assert parser.pages_seen == 3, "every file was parsed"

    db_session.refresh(job)
    document = db_session.get(Document, job.document_id)
    assert document is not None
    assert document.title == "Site survey"
    # One page, holding all three parts, in the order they were chosen.
    assert document.content_html.index("Part 1") < document.content_html.index("Part 2")
    assert document.content_html.index("Part 2") < document.content_html.index("Part 3")


async def test_every_combined_original_stays_downloadable(
    db_session: Session,
) -> None:
    """The point of keeping the originals is that all of them are kept."""
    job, storage = _make_combined_import(db_session, ["a.png", "b.png", "c.png"])
    await imports_mod.run_import(
        await _claim(job),
        storage=storage,
        mineru=CountingParser(),  # type: ignore[arg-type]
    )
    db_session.refresh(job)

    attachments = db_session.exec(
        select(Attachment).where(Attachment.document_id == job.document_id)
    ).all()
    assert sorted(a.filename for a in attachments) == ["a.png", "b.png", "c.png"]
    for attachment in attachments:
        assert attachment.object_key in storage.objects


async def test_a_combined_page_is_indexed_once(db_session: Session) -> None:
    job, storage = _make_combined_import(db_session, ["a.png", "b.png"])
    await imports_mod.run_import(
        await _claim(job),
        storage=storage,
        mineru=CountingParser(),  # type: ignore[arg-type]
    )
    db_session.refresh(job)

    jobs = db_session.exec(
        select(EmbeddingJob).where(EmbeddingJob.document_id == job.document_id)
    ).all()
    assert len(jobs) == 1, "one page, one indexing job"


async def test_a_combined_page_without_a_title_uses_the_first_file(
    db_session: Session,
) -> None:
    """The job's own filename is a summary label, which would read badly."""
    job, storage = _make_combined_import(db_session, ["survey-part-1.png", "b.png"])

    class Untitled(CountingParser):
        def parse_page(self, image: Any) -> tuple[str, int]:
            self.pages_seen += 1
            return "<p>No heading anywhere.</p>", 1

    await imports_mod.run_import(
        await _claim(job),
        storage=storage,
        mineru=Untitled(),  # type: ignore[arg-type]
    )
    db_session.refresh(job)
    document = db_session.get(Document, job.document_id)
    assert document is not None
    assert document.title == "survey-part-1"


async def test_the_imported_page_keeps_the_type_it_was_filed_under(
    db_session: Session,
) -> None:
    job, storage = _make_import(db_session)
    job.doc_type = "Invoice"
    db_session.add(job)
    db_session.commit()

    await imports_mod.run_import(
        await _claim(job),
        storage=storage,
        mineru=FakeMinerU(),  # type: ignore[arg-type]
    )
    db_session.refresh(job)
    document = db_session.get(Document, job.document_id)
    assert document is not None
    assert document.doc_type == "Invoice"
