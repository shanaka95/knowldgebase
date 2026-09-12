import io

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import NamespaceRole, ShareRole
from tests.utils.kb import (
    API,
    add_member,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
    share_document,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload(
    client: TestClient,
    headers: dict[str, str],
    ns_id: str,
    doc_id: str | None = None,
    data: bytes = PNG,
):
    form = {"namespace_id": ns_id}
    if doc_id:
        form["document_id"] = doc_id
    return client.post(
        f"{API}/attachments/",
        headers=headers,
        data=form,
        files={"file": ("pic.png", io.BytesIO(data), "image/png")},
    )


def test_upload_download_delete_roundtrip(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    h = login(client, owner, pw)
    r = _upload(client, h, str(ns.id), str(doc.id))
    assert r.status_code == 200, r.text
    att = r.json()
    assert att["filename"] == "pic.png"
    assert att["content_type"] == "image/png"
    assert att["size"] == len(PNG)
    assert (
        att["download_url"] == f"{settings.API_V1_STR}/attachments/{att['id']}/download"
    )
    assert att["document_id"] == str(doc.id)

    r = client.get(att["download_url"], headers=h)
    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers["content-type"].startswith("image/png")
    assert "inline" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "private, max-age=3600"

    r = client.get(
        f"{API}/attachments/", headers=h, params={"document_id": str(doc.id)}
    )
    assert [a["id"] for a in r.json()["data"]] == [att["id"]]
    r = client.get(f"{API}/attachments/{att['id']}", headers=h)
    assert r.status_code == 200

    assert client.delete(f"{API}/attachments/{att['id']}", headers=h).status_code == 200
    assert client.get(att["download_url"], headers=h).status_code == 404


def test_upload_size_limit(client: TestClient, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    r = _upload(client, h, str(ns.id), data=b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413


def test_attachment_permissions(client: TestClient, db: Session) -> None:
    owner, opw = create_user_with_password(db)
    viewer, vpw = create_user_with_password(db)
    guest, gpw = create_user_with_password(db)
    stranger, spw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    add_member(db, ns, viewer, NamespaceRole.viewer)
    doc = create_document(db, ns, owner)
    share_document(db, doc, guest, ShareRole.viewer)
    oh = login(client, owner, opw)
    att = _upload(client, oh, str(ns.id), str(doc.id)).json()

    # viewer of the namespace / shared viewer can download, stranger cannot
    assert (
        client.get(att["download_url"], headers=login(client, viewer, vpw)).status_code
        == 200
    )
    assert (
        client.get(att["download_url"], headers=login(client, guest, gpw)).status_code
        == 200
    )
    assert (
        client.get(
            att["download_url"], headers=login(client, stranger, spw)
        ).status_code
        == 404
    )
    # no auth at all
    assert client.get(att["download_url"]).status_code == 401
    # viewer cannot upload or delete
    assert _upload(client, login(client, viewer, vpw), str(ns.id)).status_code == 403
    assert (
        client.delete(
            f"{API}/attachments/{att['id']}", headers=login(client, viewer, vpw)
        ).status_code
        == 403
    )
    # document must belong to the namespace given
    ns2 = create_namespace(db, owner)
    assert _upload(client, oh, str(ns2.id), str(doc.id)).status_code == 400


def test_an_uploaded_file_cannot_become_a_page_on_this_site(
    client: TestClient, db: Session
) -> None:
    """The uploader picks the content type; the browser must not act on it.

    Otherwise uploading an HTML file and sending somebody the link it gets - an
    ordinary-looking address on this very site - runs the uploader's script on
    this origin, against whatever the application keeps there.
    """
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    h = login(client, owner, pw)
    att = client.post(
        f"{API}/attachments/",
        headers=h,
        data={"namespace_id": str(ns.id)},
        files={
            "file": (
                "invoice.html",
                io.BytesIO(b"<script>alert(document.domain)</script>"),
                "text/html",
            )
        },
    ).json()

    r = client.get(att["download_url"], headers=h)
    assert r.status_code == 200
    assert not r.headers["content-type"].startswith("text/html"), (
        "a stored HTML file must not be handed back as a document"
    )
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]


def test_a_public_link_cannot_serve_script_from_this_origin(
    client: TestClient, db: Session
) -> None:
    """The same, for the one attachment route that answers without a session."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(db, ns, owner)
    h = login(client, owner, pw)

    for filename, content_type in (
        ("payload.html", "text/html"),
        ("logo.svg", "image/svg+xml"),
    ):
        att = client.post(
            f"{API}/attachments/",
            headers=h,
            data={"namespace_id": str(ns.id)},
            files={
                "file": (
                    filename,
                    io.BytesIO(
                        b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'
                    ),
                    content_type,
                )
            },
        ).json()
        client.put(
            f"{API}/documents/{doc.id}",
            headers=h,
            json={
                "content": (
                    f'<p><img src="{API}/attachments/{att["id"]}/download" alt=""></p>'
                )
            },
        )
        slug = client.post(f"{API}/documents/{doc.id}/public", headers=h).json()["slug"]

        r = client.get(f"{API}/public/{slug}/attachments/{att['id']}")
        assert r.status_code == 200, r.text
        assert not r.headers["content-type"].startswith("text/html")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in r.headers["content-security-policy"], (
            f"{filename} is served without an origin of its own"
        )
