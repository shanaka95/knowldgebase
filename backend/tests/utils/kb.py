"""Factories for knowledge-base fixtures used across API tests."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.content import normalize_content
from app.models import (
    ContentFormat,
    Document,
    DocumentShare,
    Namespace,
    NamespaceMember,
    NamespaceRole,
    ShareRole,
    User,
    UserCreate,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR


def create_user_with_password(db: Session) -> tuple[User, str]:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    return user, password


def login(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def create_namespace(db: Session, owner: User, name: str | None = None) -> Namespace:
    name = name or f"Space {random_lower_string()[:8]}"
    ns = Namespace(
        name=name,
        slug=crud.unique_namespace_slug(session=db, name=name),
        owner_id=owner.id,
    )
    db.add(ns)
    db.commit()
    db.refresh(ns)
    return ns


def add_member(
    db: Session, ns: Namespace, user: User, role: NamespaceRole
) -> NamespaceMember:
    m = NamespaceMember(
        namespace_id=ns.id, user_id=user.id, role=role, created_by=ns.owner_id
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def create_document(
    db: Session,
    ns: Namespace,
    author: User,
    title: str | None = None,
    html: str = "<p>Hello world</p>",
    folder_id: uuid.UUID | None = None,
) -> Document:
    clean, text = normalize_content(html, ContentFormat.html)
    doc = Document(
        namespace_id=ns.id,
        folder_id=folder_id,
        title=title or f"Doc {random_lower_string()[:8]}",
        content_html=clean,
        content_text=text,
        created_by=author.id,
        updated_by=author.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def share_document(
    db: Session, doc: Document, user: User, role: ShareRole
) -> DocumentShare:
    share = DocumentShare(
        document_id=doc.id, user_id=user.id, role=role, created_by=doc.created_by
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


def api_create_namespace(
    client: TestClient, headers: dict[str, str], **body: Any
) -> dict[str, Any]:
    body.setdefault("name", f"Space {random_lower_string()[:8]}")
    r = client.post(f"{API}/namespaces/", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def api_create_document(
    client: TestClient, headers: dict[str, str], namespace_id: str, **body: Any
) -> dict[str, Any]:
    body.setdefault("title", f"Doc {random_lower_string()[:8]}")
    body.setdefault("content", "<p>Some <b>content</b> here</p>")
    body["namespace_id"] = namespace_id
    r = client.post(f"{API}/documents/", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()
