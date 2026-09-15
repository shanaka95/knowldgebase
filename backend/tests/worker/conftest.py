from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    Document,
    DocumentChunk,
    EmbeddingJob,
    Namespace,
    User,
    UserCreate,
)
from app.services.embeddings import EmbeddingClient
from app.services.llm import LLMClient
from app.services.vectors import InMemoryVectorStore
from app.worker.pipeline import PipelineDeps
from tests.utils.utils import random_email, random_lower_string

LLM_URL = f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions"
EMBED_URL = f"{str(settings.EMBEDDING_BASE_URL).rstrip('/')}/embeddings"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --------------------------------------------------------------------------- data


def make_user(session: Session) -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )


def make_namespace(session: Session, owner: User) -> Namespace:
    name = f"Space {random_lower_string()[:8]}"
    ns = Namespace(
        name=name,
        slug=crud.unique_namespace_slug(session=session, name=name),
        owner_id=owner.id,
    )
    session.add(ns)
    session.commit()
    session.refresh(ns)
    return ns


LONG_HTML = (
    "<h1>Onboarding</h1>"
    + "".join(
        f"<p>Paragraph {i}: new joiners receive a laptop, an account and a buddy. "
        "The first week covers security training, tooling and team rituals.</p>"
        for i in range(8)
    )
    + "<h1>Expenses</h1>"
    + "".join(
        f"<p>Paragraph {i}: expenses are submitted monthly through the portal with receipts. "
        "Approvals come from the line manager within five working days.</p>"
        for i in range(8)
    )
)


def make_document(
    session: Session,
    namespace: Namespace,
    owner: User,
    *,
    html: str = LONG_HTML,
    title: str | None = None,
) -> Document:
    """A page with a title of its own.

    Unique by default: pages are unique among their siblings now, and tests
    that want two pages in one space were relying on being able to create two
    called the same thing.
    """
    from app.core.content import html_to_text, sanitize_html

    clean = sanitize_html(html)
    doc = Document(
        namespace_id=namespace.id,
        title=title or f"Employee handbook {random_lower_string()[:8]}",
        content_html=clean,
        content_text=html_to_text(clean),
        created_by=owner.id,
        updated_by=owner.id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def enqueue_now(session: Session, doc: Document) -> EmbeddingJob:
    job = crud.enqueue_embedding_job(session=session, document=doc, force=True)
    session.commit()
    session.refresh(job)
    session.expunge(job)
    return job


def fresh(session: Session, model: Any, pk: uuid.UUID) -> Any:
    session.expire_all()
    return session.get(model, pk)


def chunk_rows(session: Session, document_id: uuid.UUID) -> list[DocumentChunk]:
    session.expire_all()
    return list(
        session.exec(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)  # type: ignore[arg-type]
        ).all()
    )


@pytest.fixture
def db_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------- fakes


def det_vector(text: str, dim: int = settings.EMBEDDING_DIM) -> list[float]:
    h = abs(hash(text)) % 1000
    return [((h + i) % 97) / 97.0 for i in range(dim)]


def embeddings_response(
    request: httpx.Request, dim: int = settings.EMBEDDING_DIM
) -> httpx.Response:
    body = json.loads(request.content)
    inputs = body["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": body["model"],
            "data": [
                {"object": "embedding", "index": i, "embedding": det_vector(t, dim)}
                for i, t in enumerate(inputs)
            ],
        },
    )


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def is_chunking_request(request: httpx.Request) -> bool:
    body = json.loads(request.content)
    return "split knowledge-base documents" in body["messages"][0]["content"]


def is_suggestion_request(request: httpx.Request) -> bool:
    """The one short call that writes an example search for the search box."""
    body = json.loads(request.content)
    return "example search query" in body["messages"][0]["content"]


def good_chunking_json(n_blocks: int) -> str:
    mid = max(1, n_blocks // 2)
    return json.dumps(
        {
            "chunks": [
                {"title": "Onboarding", "start": 1, "end": mid},
                {"title": "Expenses", "start": mid + 1, "end": n_blocks},
            ]
        }
    )


class ScriptedLLM:
    """Router for respx: chunking → chunk_replies, suggestions → a query, rest → summary."""

    def __init__(
        self,
        chunk_replies: list[str],
        summary: str = "A short summary of the handbook. It covers onboarding and expenses.",
        suggestion: str = "onboarding and expenses handbook",
    ) -> None:
        self.chunk_replies = list(chunk_replies)
        self.summary = summary
        self.suggestion = suggestion
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if is_chunking_request(request):
            self.calls.append("chunk")
            reply = (
                self.chunk_replies.pop(0)
                if self.chunk_replies
                else self.chunk_replies_default()
            )
            return chat_response(reply)
        if is_suggestion_request(request):
            self.calls.append("suggestion")
            return chat_response(self.suggestion)
        self.calls.append("summary")
        return chat_response(self.summary)

    def chunk_replies_default(self) -> str:
        return json.dumps({"chunks": [{"title": "All", "start": 1, "end": 999}]})


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def deps(vector_store: InMemoryVectorStore) -> Generator[PipelineDeps]:
    llm = LLMClient()
    embedder = EmbeddingClient()
    yield PipelineDeps(llm=llm, embedder=embedder, vectors=vector_store)


@pytest.fixture
def mocked_http() -> Generator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router
