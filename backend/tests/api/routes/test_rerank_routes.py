"""Search and Ask both put the reranker between retrieval and the reader.

These tests use a stub reranker rather than a stubbed HTTP endpoint, because
what matters here is not the wire format (covered in test_reranking.py) but that
the routes call it, honour its order, narrow what the model reads, and carry on
without it when it is missing or broken.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_embedding_client, get_reranker
from app.core.config import settings
from app.main import app
from app.services.reranking import RerankedDocument
from app.services.vectors import InMemoryVectorStore
from tests.api.routes.test_retrieve import StubEmbeddings, _index
from tests.utils.kb import (
    API,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)

ASK = f"{API}/ask/"
RETRIEVE = f"{API}/search/retrieve"
LLM_URL = f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions"


class StubReranker:
    """Scores candidates by a caller-supplied rule, and records what it saw."""

    def __init__(self, scorer: Any = None, fail: bool = False) -> None:
        self.scorer = scorer or (lambda i, text: 1.0 / (i + 1))
        self.fail = fail
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedDocument]:
        self.calls.append((query, documents))
        if self.fail:
            raise httpx.ConnectError("reranker down")
        scored = [
            RerankedDocument(index=i, score=float(self.scorer(i, text)))
            for i, text in enumerate(documents)
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored


@pytest.fixture(autouse=True)
def stub_embeddings() -> Generator[None]:
    app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddings()
    yield
    app.dependency_overrides.pop(get_embedding_client, None)


@pytest.fixture
def store() -> Generator[InMemoryVectorStore]:
    previous = app.state.vectors
    vectors = InMemoryVectorStore()
    app.state.vectors = vectors
    yield vectors
    app.state.vectors = previous


def use_reranker(reranker: Any) -> None:
    app.dependency_overrides[get_reranker] = lambda: reranker


@pytest.fixture(autouse=True)
def _clear_reranker() -> Generator[None]:
    yield
    app.dependency_overrides.pop(get_reranker, None)


def _completion(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {},
    }


async def _seed_many(
    db: Session, store: InMemoryVectorStore, owner: Any, count: int = 6
) -> Any:
    """A space of pages that all mention the query terms, so fusion cannot separate them."""
    ns = create_namespace(db, owner)
    for i in range(count):
        doc = create_document(
            db,
            ns,
            owner,
            title=f"Runbook {i}",
            html=f"<p>Standby promotion procedure, variant {i}.</p>",
        )
        await _index(store, db, doc, summary=f"Standby promotion, variant {i}.")
    db.commit()
    return ns


@pytest.mark.anyio
async def test_search_returns_results_in_the_rerankers_order(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner)
    headers = login(client, owner, pw)

    # Score the last candidate highest, which fusion would never do.
    reranker = StubReranker(scorer=lambda i, text: float(i))
    use_reranker(reranker)

    r = client.get(RETRIEVE, headers=headers, params={"q": "standby promotion"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["used_rerank"] is True
    assert reranker.calls, "the route has to actually call it"

    query, documents = reranker.calls[0]
    assert query == "standby promotion"
    assert len(documents) >= 3
    assert all(d.startswith("Runbook") for d in documents), "title leads each candidate"

    # The candidate scored highest is the one that comes back first.
    best = documents[-1].splitlines()[0]
    assert body["data"][0]["title"] == best


@pytest.mark.anyio
async def test_search_survives_a_reranker_that_is_down(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner)
    headers = login(client, owner, pw)
    use_reranker(StubReranker(fail=True))

    r = client.get(RETRIEVE, headers=headers, params={"q": "standby promotion"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] > 0, "results still arrive"
    assert body["used_rerank"] is False, "and the caller is told it did not run"


@pytest.mark.anyio
async def test_search_without_a_reranker_configured_is_unchanged(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner)
    headers = login(client, owner, pw)
    use_reranker(None)

    r = client.get(RETRIEVE, headers=headers, params={"q": "standby promotion"})
    assert r.status_code == 200
    assert r.json()["used_rerank"] is False


@pytest.mark.anyio
async def test_reranking_can_be_turned_off_for_one_request(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Useful for seeing what fusion alone thought."""
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner)
    headers = login(client, owner, pw)
    reranker = StubReranker()
    use_reranker(reranker)

    r = client.get(
        RETRIEVE, headers=headers, params={"q": "standby promotion", "rerank": "false"}
    )
    assert r.status_code == 200
    assert r.json()["used_rerank"] is False
    assert reranker.calls == []


@pytest.mark.anyio
async def test_ask_sends_only_the_top_pages_to_the_model(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Six pages match; the model should be shown three, not six."""
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner, count=6)
    headers = login(client, owner, pw)
    # A clear winner, then a steep drop: nothing qualifies for the extra slots.
    use_reranker(
        StubReranker(scorer=lambda i, text: [0.9, 0.6, 0.5, 0.05, 0.04, 0.03][i])
    )

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200, json=_completion("Promote the standby [1].")
            )
        )
        r = client.post(
            ASK, headers=headers, json={"q": "how do I promote the standby"}
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reranked"] is True
    assert body["searched"] >= 6, "retrieval still cast a wide net"
    assert body["used"] <= settings.RERANK_KEEP_DEFAULT, "but the model read a few"


@pytest.mark.anyio
async def test_ask_sends_three_pages_however_flat_the_scores(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Six near-identical scores, and still three pages reach the model.

    A page carries its whole text now, so three of them already fill a prompt
    somebody is waiting on. The widening rule still exists in `keep_count` and
    is tested there; here the cap is what matters.
    """
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner, count=6)
    headers = login(client, owner, pw)
    use_reranker(
        StubReranker(scorer=lambda i, text: [0.9, 0.89, 0.88, 0.87, 0.86, 0.02][i])
    )

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200, json=_completion("Promote the standby [1].")
            )
        )
        r = client.post(
            ASK, headers=headers, json={"q": "how do I promote the standby"}
        )

    body = r.json()
    assert body["used"] == 3
    assert body["searched"] >= 6, "retrieval still cast a wide net"


@pytest.mark.anyio
async def test_ask_still_answers_when_the_reranker_fails(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed_many(db, store, owner, count=4)
    headers = login(client, owner, pw)
    use_reranker(StubReranker(fail=True))

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200, json=_completion("Promote the standby [1].")
            )
        )
        r = client.post(
            ASK, headers=headers, json={"q": "how do I promote the standby"}
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reranked"] is False
    assert body["answer"].startswith("Promote the standby")
