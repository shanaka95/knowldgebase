"""Uploading PDFs/images for import: validation, queueing and lifecycle."""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.main import app
from app.models import (
    CleanupKind,
    CleanupTask,
    Folder,
    ImportJob,
    ImportStatus,
    NamespaceRole,
)
from app.services.storage import InMemoryStorage
from tests.utils.kb import (
    API,
    add_member,
    create_namespace,
    create_user_with_password,
    login,
)

IMPORTS = f"{API}/imports/"


def png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (120, 60, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    namespace_id: str,
    *,
    data: bytes | None = None,
    filename: str = "scan.png",
    content_type: str = "image/png",
    **form: str,
):
    form["namespace_id"] = namespace_id
    return client.post(
        IMPORTS,
        headers=headers,
        data=form,
        files={"file": (filename, io.BytesIO(data or png_bytes()), content_type)},
    )


@pytest.fixture
def storage() -> InMemoryStorage:
    store: InMemoryStorage = app.state.storage
    return store


def test_upload_queues_a_job_and_stores_the_file(
    client: TestClient, db: Session, storage: InMemoryStorage
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    payload = png_bytes()

    r = _upload(client, h, str(ns.id), data=payload, title="Scanned invoice")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == ImportStatus.queued
    assert job["title"] == "Scanned invoice"
    assert job["filename"] == "scan.png"
    assert job["content_type"] == "image/png"
    assert job["size"] == len(payload)
    assert job["namespace_slug"] == ns.slug
    assert job["document_id"] is None
    assert job["pages_done"] == 0

    row = db.get(ImportJob, uuid.UUID(job["id"]))
    assert row is not None
    assert storage.exists(row.object_key), "the upload must be in object storage"


def test_title_is_left_unset_for_the_worker_to_decide(
    client: TestClient, db: Session
) -> None:
    """The worker promotes the document's own heading, falling back to the
    filename only when the parsed page has none - so the route must not
    pre-fill a title and hide that heading."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)

    r = _upload(
        client, h, str(ns.id), filename="Q3 report.pdf", content_type="application/pdf"
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] is None

    # an explicit title is of course kept
    r = _upload(
        client,
        h,
        str(ns.id),
        filename="Q3 report.pdf",
        content_type="application/pdf",
        title="Board pack",
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Board pack"


def test_pdf_uploads_are_accepted(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)

    r = _upload(
        client,
        h,
        str(ns.id),
        data=b"%PDF-1.7 fake",
        filename="doc.pdf",
        content_type="application/pdf",
    )
    assert r.status_code == 200, r.text


def test_unsupported_file_type_is_rejected(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)

    r = _upload(
        client,
        h,
        str(ns.id),
        data=b"hello",
        filename="notes.txt",
        content_type="text/plain",
    )
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


def test_oversize_upload_is_rejected(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    monkeypatch.setattr(settings, "MAX_IMPORT_SIZE_MB", 0)

    r = _upload(client, h, str(ns.id))
    assert r.status_code == 413
    assert "limit" in r.json()["detail"]


def test_upload_requires_editor_on_the_namespace(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    viewer, viewer_pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    h = login(client, viewer, viewer_pw)

    assert _upload(client, h, str(ns.id)).status_code == 403


def test_upload_into_a_foreign_namespace_is_hidden(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    stranger, stranger_pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, stranger, stranger_pw)

    assert _upload(client, h, str(ns.id)).status_code == 404


def test_folder_must_belong_to_the_namespace(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    other = create_namespace(db, owner)
    folder = Folder(namespace_id=other.id, name="Elsewhere", created_by=owner.id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    h = login(client, owner, pw)

    r = _upload(client, h, str(ns.id), folder_id=str(folder.id))
    assert r.status_code == 400
    assert "namespace" in r.json()["detail"]


def test_read_scoped_api_key_cannot_upload(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    key = client.post(
        f"{API}/api-keys/", headers=h, json={"name": "ro", "scope": "read"}
    ).json()["key"]

    r = _upload(client, {"Authorization": f"Bearer {key}"}, str(ns.id))
    assert r.status_code == 403
    assert "write scope" in r.json()["detail"]


def test_list_and_get_are_limited_to_your_own_imports(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    other, other_pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    mine = _upload(client, login(client, owner, pw), str(ns.id)).json()

    other_h = login(client, other, other_pw)
    listing = client.get(IMPORTS, headers=other_h).json()
    assert mine["id"] not in {job["id"] for job in listing["data"]}
    assert client.get(f"{IMPORTS}{mine['id']}", headers=other_h).status_code == 404

    own = client.get(f"{IMPORTS}{mine['id']}", headers=login(client, owner, pw))
    assert own.status_code == 200
    assert own.json()["id"] == mine["id"]


def test_list_filters_by_namespace_and_status(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    elsewhere = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    here = client.get(IMPORTS, headers=h, params={"namespace_id": str(ns.id)}).json()
    assert {j["id"] for j in here["data"]} == {job["id"]}

    away = client.get(
        IMPORTS, headers=h, params={"namespace_id": str(elsewhere.id)}
    ).json()
    assert away["data"] == []

    queued = client.get(IMPORTS, headers=h, params={"status": "queued"}).json()
    assert job["id"] in {j["id"] for j in queued["data"]}
    done = client.get(IMPORTS, headers=h, params={"status": "done"}).json()
    assert job["id"] not in {j["id"] for j in done["data"]}


def test_superuser_sees_every_import(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    job = _upload(client, login(client, owner, pw), str(ns.id)).json()

    listing = client.get(IMPORTS, headers=superuser_token_headers).json()
    assert job["id"] in {j["id"] for j in listing["data"]}


def test_retry_resets_a_failed_import(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    row = db.get(ImportJob, uuid.UUID(job["id"]))
    assert row is not None
    row.status = ImportStatus.failed
    row.error = "MinerU unreachable"
    row.attempts = 3
    row.pages_done = 2
    db.add(row)
    db.commit()

    r = client.post(f"{IMPORTS}{job['id']}/retry", headers=h)
    assert r.status_code == 200, r.text
    retried = r.json()
    assert retried["status"] == ImportStatus.queued
    assert retried["attempts"] == 0
    assert retried["pages_done"] == 0
    assert retried["error"] is None


def test_retry_of_a_queued_import_conflicts(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    r = client.post(f"{IMPORTS}{job['id']}/retry", headers=h)
    assert r.status_code == 409
    assert "failed or cancelled" in r.json()["detail"]


def test_cancelling_a_queued_import_stops_it_outright(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    r = client.post(f"{IMPORTS}{job['id']}/cancel", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == ImportStatus.cancelled

    row = db.get(ImportJob, uuid.UUID(job["id"]))
    assert row is not None
    db.refresh(row)
    assert row.cancel_requested is True


def test_cancelling_a_running_import_only_flags_it(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    row = db.get(ImportJob, uuid.UUID(job["id"]))
    assert row is not None
    row.status = ImportStatus.parsing
    db.add(row)
    db.commit()

    r = client.post(f"{IMPORTS}{job['id']}/cancel", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == ImportStatus.parsing, "the worker finishes the job off"
    db.refresh(row)
    assert row.cancel_requested is True


def test_delete_queues_cleanup_of_the_orphaned_upload(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()
    object_key = db.get(ImportJob, uuid.UUID(job["id"])).object_key  # type: ignore[union-attr]

    r = client.delete(f"{IMPORTS}{job['id']}", headers=h)
    assert r.status_code == 200
    assert db.get(ImportJob, uuid.UUID(job["id"])) is None

    tasks = db.exec(
        select(CleanupTask).where(CleanupTask.kind == CleanupKind.minio_object)
    ).all()
    assert object_key in {t.payload.get("object_key") for t in tasks}


def test_delete_keeps_the_file_when_an_attachment_owns_it(
    client: TestClient, db: Session
) -> None:
    from app.models import Attachment

    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    job = _upload(client, h, str(ns.id)).json()

    row = db.get(ImportJob, uuid.UUID(job["id"]))
    assert row is not None
    attachment = Attachment(
        namespace_id=ns.id,
        uploader_id=owner.id,
        filename=row.filename,
        content_type=row.content_type,
        size=row.size,
        object_key=row.object_key,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    row.attachment_id = attachment.id
    db.add(row)
    db.commit()

    before = {
        t.payload.get("object_key")
        for t in db.exec(
            select(CleanupTask).where(CleanupTask.kind == CleanupKind.minio_object)
        ).all()
    }
    assert client.delete(f"{IMPORTS}{job['id']}", headers=h).status_code == 200
    after = {
        t.payload.get("object_key")
        for t in db.exec(
            select(CleanupTask).where(CleanupTask.kind == CleanupKind.minio_object)
        ).all()
    }
    assert after == before, "the attachment still needs the object"


def test_import_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get(IMPORTS).status_code == 401
    assert client.get(f"{IMPORTS}{uuid.uuid4()}").status_code == 401
