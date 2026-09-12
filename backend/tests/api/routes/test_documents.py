import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.models import (
    CleanupKind,
    CleanupTask,
    Document,
    EmbeddingJob,
    EmbeddingStatus,
    JobStatus,
    NamespaceRole,
    ShareRole,
)
from tests.utils.kb import (
    API,
    add_member,
    api_create_document,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
    share_document,
)


def _jobs(db: Session, doc_id: str) -> list[EmbeddingJob]:
    return db.exec(select(EmbeddingJob).where(EmbeddingJob.document_id == doc_id)).all()  # type: ignore[arg-type]


def test_create_document_html_sanitized_and_job_enqueued(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    doc = api_create_document(
        client,
        h,
        str(ns.id),
        title="  Hello  ",
        content='<h2>Intro</h2><p onclick="x()">Hi <script>alert(1)</script><b>there</b></p>'
        '<div data-panel data-panel-type="warning" class="kb-panel"><p>Careful</p></div>',
    )
    assert doc["title"] == "Hello"
    assert "<script" not in doc["content_html"]
    assert "onclick" not in doc["content_html"]
    assert 'data-panel-type="warning"' in doc["content_html"]
    assert doc["content_text"] == "Intro\n\nHi there\n\nCareful"
    assert doc["version"] == 1
    assert doc["embedding_status"] == "pending"
    assert doc["is_stale"] is True
    assert doc["my_role"] == "editor"
    assert doc["namespace_slug"] == ns.slug
    assert doc["created_by_user"]["email"] == owner.email
    jobs = _jobs(db, doc["id"])
    assert (
        len(jobs) == 1
        and jobs[0].status == JobStatus.queued
        and jobs[0].doc_version == 1
    )


def test_create_document_markdown_and_text(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    md = api_create_document(
        client,
        h,
        str(ns.id),
        content="# Title\n\nSome *emphasis*\n\n- a\n- b",
        content_format="markdown",
    )
    assert md["content_html"].startswith("<h1>Title</h1>")
    assert "<em>emphasis</em>" in md["content_html"]
    assert "- a" in md["content_text"]
    txt = api_create_document(
        client,
        h,
        str(ns.id),
        content="line one\nline two\n\n<b>para</b>",
        content_format="text",
    )
    assert (
        txt["content_html"]
        == "<p>line one<br>line two</p><p>&lt;b&gt;para&lt;/b&gt;</p>"
    )
    assert "<b>para</b>" in txt["content_text"]


def test_update_versioning_rules(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    doc = api_create_document(
        client, h, str(ns.id), title="T", content="<p>Hello world</p>"
    )
    url = f"{API}/documents/{doc['id']}"

    # formatting-only change: same text -> no version bump, html still updated
    r = client.put(
        url, headers=h, json={"content": "<p>Hello <strong>world</strong></p>"}
    )
    assert r.status_code == 200
    assert r.json()["version"] == 1
    assert "<strong>" in r.json()["content_html"]
    assert len(_jobs(db, doc["id"])) == 1

    # text change -> bump + job coalesced (still one queued job, retargeted to v2)
    r = client.put(url, headers=h, json={"content": "<p>Hello there world</p>"})
    assert r.json()["version"] == 2
    jobs = _jobs(db, doc["id"])
    assert (
        len(jobs) == 1
        and jobs[0].doc_version == 2
        and jobs[0].status == JobStatus.queued
    )

    # title change -> bump
    r = client.put(url, headers=h, json={"title": "New title"})
    assert r.json()["version"] == 3

    # optimistic locking
    r = client.put(url, headers=h, json={"title": "Conflict", "expected_version": 2})
    assert r.status_code == 409
    r = client.put(url, headers=h, json={"title": "Fine", "expected_version": 3})
    assert r.status_code == 200 and r.json()["version"] == 4
    assert r.json()["updated_by_user"]["email"] == owner.email


def test_regenerate_supersedes_queued_job(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    doc = api_create_document(client, h, str(ns.id))
    first = _jobs(db, doc["id"])[0]
    r = client.post(f"{API}/documents/{doc['id']}/embeddings/regenerate", headers=h)
    assert r.status_code == 200, r.text
    new_job = r.json()
    assert new_job["status"] == "queued"
    db.expire_all()
    jobs = {str(j.id): j for j in _jobs(db, doc["id"])}
    assert jobs[str(first.id)].status == JobStatus.superseded
    assert jobs[str(first.id)].cancel_requested is True
    assert jobs[new_job["id"]].status == JobStatus.queued

    r = client.get(f"{API}/documents/{doc['id']}/embeddings", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["current_job"]["id"] == new_job["id"]
    assert len(body["jobs"]) == 2
    assert body["is_stale"] is True
    assert body["chunks"] == []
    assert set(body["kinds"]) == {"document", "summary", "chunk"}


def test_embeddings_view_after_worker_results(client: TestClient, db: Session) -> None:
    """Simulate what the worker writes and check the read model."""
    from app.models import DocumentChunk

    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    doc.embedding_status = EmbeddingStatus.ready
    doc.embedding_version = doc.version
    doc.summary = "A summary."
    doc.chunk_count = 2
    doc.chunking_method = "llm"
    db.add(doc)
    for i in range(2):
        db.add(
            DocumentChunk(
                document_id=doc.id,
                doc_version=doc.version,
                chunk_index=i,
                title=f"c{i}",
                text=f"text {i}",
                char_count=6,
            )
        )
    db.commit()
    h = login(client, owner, pw)
    r = client.get(f"{API}/documents/{doc.id}/embeddings", headers=h)
    body = r.json()
    assert body["is_stale"] is False
    assert body["summary"] == "A summary."
    assert [c["title"] for c in body["chunks"]] == ["c0", "c1"]
    r = client.get(f"{API}/documents/{doc.id}", headers=h)
    assert r.json()["is_stale"] is False and r.json()["summary"] == "A summary."


def test_list_recent_and_root_filters(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    f = client.post(
        f"{API}/folders/", headers=h, json={"namespace_id": str(ns.id), "name": "F"}
    ).json()
    a = api_create_document(client, h, str(ns.id), title="A")
    b = api_create_document(client, h, str(ns.id), title="B", folder_id=f["id"])
    r = client.get(
        f"{API}/documents/",
        headers=h,
        params={"namespace_id": str(ns.id), "root_only": True},
    )
    assert [d["id"] for d in r.json()["data"]] == [a["id"]]
    r = client.get(f"{API}/documents/", headers=h, params={"folder_id": f["id"]})
    assert [d["id"] for d in r.json()["data"]] == [b["id"]]
    r = client.get(f"{API}/documents/recent", headers=h)
    ids = [d["id"] for d in r.json()["data"]]
    assert ids[:2] == [b["id"], a["id"]]


def test_move_document(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns1 = create_namespace(db, owner)
    ns2 = create_namespace(db, owner)
    h = login(client, owner, pw)
    f2 = client.post(
        f"{API}/folders/", headers=h, json={"namespace_id": str(ns2.id), "name": "F2"}
    ).json()
    doc = api_create_document(client, h, str(ns1.id))
    # folder from another namespace without switching namespace -> 400
    r = client.post(
        f"{API}/documents/{doc['id']}/move", headers=h, json={"folder_id": f2["id"]}
    )
    assert r.status_code == 400
    r = client.post(
        f"{API}/documents/{doc['id']}/move",
        headers=h,
        json={"namespace_id": str(ns2.id), "folder_id": f2["id"]},
    )
    assert r.status_code == 200
    assert r.json()["namespace_id"] == str(ns2.id) and r.json()["folder_id"] == f2["id"]
    assert r.json()["version"] == 1  # moving does not bump


def test_permission_matrix(client: TestClient, db: Session) -> None:
    owner, opw = create_user_with_password(db)
    viewer, vpw = create_user_with_password(db)
    editor, epw = create_user_with_password(db)
    shared_viewer, svpw = create_user_with_password(db)
    shared_editor, sepw = create_user_with_password(db)
    stranger, spw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    add_member(db, ns, editor, NamespaceRole.editor)
    doc = create_document(db, ns, owner)
    share_document(db, doc, shared_viewer, ShareRole.viewer)
    share_document(db, doc, shared_editor, ShareRole.editor)
    url = f"{API}/documents/{doc.id}"
    upd = {"content": "<p>changed text</p>"}

    for user, pw, get_code, put_code in [
        (owner, opw, 200, 200),
        (editor, epw, 200, 200),
        (viewer, vpw, 200, 403),
        (shared_viewer, svpw, 200, 403),
        (shared_editor, sepw, 200, 200),
        (stranger, spw, 404, 404),
    ]:
        h = login(client, user, pw)
        assert client.get(url, headers=h).status_code == get_code, user.email
        assert client.put(url, headers=h, json=upd).status_code == put_code, user.email

    # roles reported
    assert (
        client.get(url, headers=login(client, viewer, vpw)).json()["my_role"]
        == "viewer"
    )
    assert (
        client.get(url, headers=login(client, shared_editor, sepw)).json()["my_role"]
        == "editor"
    )

    # create in namespace: viewer 403, stranger 404
    body = {"namespace_id": str(ns.id), "title": "x", "content": ""}
    assert (
        client.post(
            f"{API}/documents/", headers=login(client, viewer, vpw), json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/documents/", headers=login(client, stranger, spw), json=body
        ).status_code
        == 404
    )

    # delete: shared editor cannot, namespace editor can
    assert (
        client.delete(url, headers=login(client, shared_editor, sepw)).status_code
        == 403
    )
    assert client.delete(url, headers=login(client, editor, epw)).status_code == 200
    tasks = db.exec(
        select(CleanupTask).where(CleanupTask.kind == CleanupKind.qdrant_document)
    ).all()
    assert any(t.payload.get("document_id") == str(doc.id) for t in tasks)
    assert db.exec(select(Document).where(Document.id == doc.id)).first() is None


def test_creator_can_delete_own_document_when_only_shared_editor(
    client: TestClient, db: Session
) -> None:
    owner, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    # owner is namespace admin anyway; check the "created_by" path via a member demoted later
    editor, epw = create_user_with_password(db)
    m = add_member(db, ns, editor, NamespaceRole.editor)
    h = login(client, editor, epw)
    mine = api_create_document(client, h, str(ns.id))
    # demote to viewer; still may delete own doc
    m.role = NamespaceRole.viewer
    db.add(m)
    db.commit()
    assert client.delete(f"{API}/documents/{mine['id']}", headers=h).status_code == 200
    assert client.delete(f"{API}/documents/{doc.id}", headers=h).status_code == 403


def test_shared_with_me(client: TestClient, db: Session) -> None:
    owner, _ = create_user_with_password(db)
    me, mpw = create_user_with_password(db)
    ns_member = create_namespace(db, owner, name="Team")
    ns_other = create_namespace(db, owner, name="Other")
    add_member(db, ns_member, me, NamespaceRole.viewer)
    doc = create_document(db, ns_other, owner)
    share_document(db, doc, me, ShareRole.editor)
    r = client.get(f"{API}/documents/shared-with-me", headers=login(client, me, mpw))
    assert r.status_code == 200
    body = r.json()
    assert [n["id"] for n in body["namespaces"]] == [str(ns_member.id)]
    assert [d["id"] for d in body["documents"]] == [str(doc.id)]
    assert body["documents"][0]["my_role"] == "editor"


def test_embedding_summary_counts(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    d1 = create_document(db, ns, owner)  # pending, never indexed
    d2 = create_document(db, ns, owner)
    d2.embedding_status = EmbeddingStatus.ready
    d2.embedding_version = d2.version
    d3 = create_document(db, ns, owner)
    d3.embedding_status = EmbeddingStatus.ready
    d3.embedding_version = 0  # stale
    d4 = create_document(db, ns, owner)
    d4.embedding_status = EmbeddingStatus.failed
    d5 = create_document(db, ns, owner)
    d5.embedding_status = EmbeddingStatus.embedding
    db.add_all([d2, d3, d4, d5])
    db.commit()
    r = client.get(
        f"{API}/documents/embeddings/summary", headers=login(client, owner, pw)
    )
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 5 and s["pending"] == 1 and s["ready"] == 1
    assert s["stale"] == 1 and s["failed"] == 1 and s["in_progress"] == 1
    assert d1.embedding_status == EmbeddingStatus.pending


def test_reindex_all_queues_every_document(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    create_document(db, ns, owner)
    create_document(db, ns, owner)

    r = client.post(
        f"{API}/documents/embeddings/reindex-all", headers=superuser_token_headers
    )
    assert r.status_code == 200, r.text
    total = db.exec(select(func.count()).select_from(Document)).one()
    assert f"{total} documents" in r.json()["message"]
    queued = db.exec(
        select(func.count())
        .select_from(EmbeddingJob)
        .where(EmbeddingJob.status == JobStatus.queued)
    ).one()
    assert queued >= total


def test_reindex_all_is_superuser_only(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    r = client.post(
        f"{API}/documents/embeddings/reindex-all", headers=login(client, owner, pw)
    )
    assert r.status_code == 403


def test_source_attachment_is_exposed_on_an_imported_document(
    client: TestClient, db: Session
) -> None:
    from app.models import Attachment

    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    attachment = Attachment(
        namespace_id=ns.id,
        document_id=doc.id,
        uploader_id=owner.id,
        filename="report.pdf",
        content_type="application/pdf",
        size=1234,
        object_key=f"imports/{uuid.uuid4()}.pdf",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    doc.source_attachment_id = attachment.id
    db.add(doc)
    db.commit()

    r = client.get(f"{API}/documents/{doc.id}", headers=login(client, owner, pw))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_attachment_id"] == str(attachment.id)
    assert body["source_attachment"]["filename"] == "report.pdf"
    assert body["source_attachment"]["download_url"].endswith(
        f"/attachments/{attachment.id}/download"
    )
