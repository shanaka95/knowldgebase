"""Hybrid retrieval endpoint: fusion order, scoping and snippets."""

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_embedding_client
from app.main import app
from app.models import (
    Document,
    DocumentChunk,
    EmbeddingKind,
    EmbeddingStatus,
    Namespace,
    NamespaceRole,
    User,
)
from app.services.sparse import encode_document
from app.services.vectors import InMemoryVectorStore, Point, build_payload
from tests.utils.kb import (
    API,
    add_member,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
    share_document,
)

RETRIEVE = f"{API}/search/retrieve"


class StubEmbeddings:
    """Deterministic embeddings so vector search is reproducible in tests."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector(t) for t in texts]


def _vector(text: str) -> list[float]:
    """Crude bag-of-words vector: shared words point in a shared direction."""
    dims = ["budget", "kitchen", "python", "vpn"]
    lowered = text.lower()
    vec = [1.0 if d in lowered else 0.0 for d in dims]
    return vec if any(vec) else [0.1, 0.1, 0.1, 0.1]


@pytest.fixture(autouse=True)
def stub_embeddings() -> Generator[None]:
    app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddings()
    yield
    app.dependency_overrides.pop(get_embedding_client, None)


@pytest.fixture
def store() -> Generator[InMemoryVectorStore]:
    """A per-test vector store, restoring the shared one afterwards."""
    previous = app.state.vectors
    vectors = InMemoryVectorStore()
    app.state.vectors = vectors
    yield vectors
    app.state.vectors = previous


async def _index(
    store: InMemoryVectorStore,
    db: Session,
    doc: Document,
    *,
    chunks: list[str] | None = None,
    summary: str | None = None,
) -> None:
    """Mimic what the worker writes: a document point plus optional summary/chunks."""
    doc.embedding_status = EmbeddingStatus.ready
    doc.embedding_version = doc.version
    points = [
        Point(
            id=str(uuid.uuid4()),
            vector=_vector(f"{doc.title} {doc.content_text}"),
            sparse=encode_document(f"{doc.title}\n\n{doc.content_text}"),
            payload=build_payload(
                document_id=doc.id,
                namespace_id=doc.namespace_id,
                kind=EmbeddingKind.document,
                doc_version=doc.version,
                title=doc.title,
            ),
        )
    ]
    if summary:
        doc.summary = summary
        points.append(
            Point(
                id=str(uuid.uuid4()),
                vector=_vector(summary),
                sparse=encode_document(summary),
                payload=build_payload(
                    document_id=doc.id,
                    namespace_id=doc.namespace_id,
                    kind=EmbeddingKind.summary,
                    doc_version=doc.version,
                    title=doc.title,
                ),
            )
        )
    for index, text in enumerate(chunks or []):
        db.add(
            DocumentChunk(
                document_id=doc.id,
                doc_version=doc.version,
                chunk_index=index,
                title=f"Section {index}",
                text=text,
                char_count=len(text),
            )
        )
        points.append(
            Point(
                id=str(uuid.uuid4()),
                vector=_vector(text),
                sparse=encode_document(text),
                payload=build_payload(
                    document_id=doc.id,
                    namespace_id=doc.namespace_id,
                    kind=EmbeddingKind.chunk,
                    doc_version=doc.version,
                    title=f"Section {index}",
                    chunk_index=index,
                    char_count=len(text),
                ),
            )
        )
    doc.chunk_count = len(chunks or [])
    db.add(doc)
    db.commit()
    db.refresh(doc)
    await store.upsert(points)


@pytest.fixture
def corpus(
    db: Session, store: InMemoryVectorStore
) -> tuple[User, str, Namespace, Namespace, Document, Document, Document]:
    """Two namespaces: the owner's budget/kitchen pages and a stranger's VPN page."""
    import anyio

    owner, password = create_user_with_password(db)
    stranger, _ = create_user_with_password(db)
    mine = create_namespace(db, owner)
    theirs = create_namespace(db, stranger)

    budget = create_document(
        db,
        mine,
        owner,
        title="Quarterly budget review",
        html="<p>Finance presented the budget. Cloud spend is over plan.</p>",
    )
    kitchen = create_document(
        db,
        mine,
        owner,
        title="Kitchen etiquette",
        html="<p>The kitchen fridge is cleaned every Friday.</p>",
    )
    vpn = create_document(
        db,
        theirs,
        stranger,
        title="Connecting to the VPN",
        html="<p>Open the vpn client and sign in.</p>",
    )

    async def seed() -> None:
        await _index(
            store,
            db,
            budget,
            summary="A budget summary for the quarter",
            chunks=[
                "The budget for compute grew by 19% because of the GPU nodes.",
                "Storage costs were flat this quarter.",
            ],
        )
        await _index(store, db, kitchen)
        await _index(store, db, vpn)

    anyio.run(seed)
    return owner, password, mine, theirs, budget, kitchen, vpn


def test_hybrid_search_ranks_the_matching_document_first(
    client: TestClient, corpus: tuple
) -> None:
    owner, password, _mine, _theirs, budget, _kitchen, _vpn = corpus
    h = login(client, owner, password)

    r = client.get(RETRIEVE, headers=h, params={"q": "budget"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"], "expected at least one hit"
    assert body["data"][0]["document_id"] == str(budget.id)
    assert body["used_bm25"] is True
    assert body["used_vector"] is True
    assert body["query_tokens"] == ["budget"]
    assert body["took_ms"] >= 0
    scores = [hit["score"] for hit in body["data"]]
    assert scores == sorted(scores, reverse=True), "results must be in fused order"


def test_each_hit_explains_which_sources_matched(
    client: TestClient, corpus: tuple
) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "budget"}).json()
    top = body["data"][0]
    assert top["sources"], "every hit must say why it matched"
    methods = {s["method"] for s in top["sources"]}
    targets = {s["target"] for s in top["sources"]}
    # keyword search also runs a Postgres full-text source, which covers
    # pages the worker has not indexed yet
    assert methods <= {"bm25", "vector", "fulltext"}
    assert targets <= {"document", "summary", "chunk", "page"}
    for source in top["sources"]:
        assert source["rank"] >= 1
        assert source["contribution"] > 0
    reports = {(s["method"], s["target"]) for s in body["sources"]}
    assert len(reports) == 7, (
        "3 targets x 2 vector-store methods, plus the full-text source"
    )


def test_chunk_match_is_reported_with_its_snippet(
    client: TestClient, corpus: tuple
) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "GPU nodes compute"}).json()
    top = body["data"][0]
    assert top["matched_chunk_index"] == 0
    assert top["matched_chunk_title"] == "Section 0"
    assert "GPU" in top["snippet"] or "compute" in top["snippet"].lower()


def test_snippets_highlight_query_terms(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "budget"}).json()
    assert any("<mark>" in hit["snippet"] for hit in body["data"])


def test_snippets_escape_html(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    import anyio

    owner, password = create_user_with_password(db)
    ns = create_namespace(db, owner)
    doc = create_document(
        db, ns, owner, title="Injection", html="<p>alert budget &lt;script&gt;</p>"
    )
    anyio.run(lambda: _index(store, db, doc))
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "budget"}).json()
    snippet = body["data"][0]["snippet"]
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet
    assert "<mark>budget</mark>" in snippet


def test_documents_in_other_namespaces_are_invisible(
    client: TestClient, corpus: tuple
) -> None:
    owner, password, _mine, _theirs, _budget, _kitchen, vpn = corpus
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "vpn client"}).json()
    assert str(vpn.id) not in {hit["document_id"] for hit in body["data"]}


def test_a_shared_document_is_retrievable(
    client: TestClient, db: Session, corpus: tuple
) -> None:
    from app.models import ShareRole

    owner, password, _mine, _theirs, _budget, _kitchen, vpn = corpus
    share_document(db, vpn, owner, ShareRole.viewer)
    h = login(client, owner, password)

    body = client.get(RETRIEVE, headers=h, params={"q": "vpn client"}).json()
    assert str(vpn.id) in {hit["document_id"] for hit in body["data"]}


def test_namespace_filter_restricts_results(
    client: TestClient, db: Session, corpus: tuple
) -> None:
    owner, password, mine, theirs, _budget, _kitchen, _vpn = corpus
    add_member(db, theirs, owner, NamespaceRole.viewer)
    h = login(client, owner, password)

    body = client.get(
        RETRIEVE, headers=h, params={"q": "vpn budget", "namespace_id": str(mine.id)}
    ).json()
    assert body["data"], "the owner's own namespace still has matches"
    assert all(hit["namespace_id"] == str(mine.id) for hit in body["data"])


def test_namespace_filter_requires_access(client: TestClient, corpus: tuple) -> None:
    owner, password, _mine, theirs, *_ = corpus
    h = login(client, owner, password)

    r = client.get(
        RETRIEVE, headers=h, params={"q": "vpn", "namespace_id": str(theirs.id)}
    )
    assert r.status_code == 404


def test_targets_can_be_narrowed(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    body = client.get(
        RETRIEVE, headers=h, params={"q": "budget", "targets": ["chunk"]}
    ).json()
    assert {s["target"] for s in body["sources"]} == {"chunk", "page"}, (
        "narrowing targets applies to the vector-store sources; the full-text\n"
        "source always searches whole pages"
    )
    assert body["targets"] == ["chunk"]


def test_bm25_only_skips_vector_sources(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    body = client.get(
        RETRIEVE, headers=h, params={"q": "budget", "vector": "false"}
    ).json()
    assert body["used_vector"] is False
    assert {s["method"] for s in body["sources"]} == {"bm25", "fulltext"}


def test_disabling_both_methods_is_rejected(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    r = client.get(
        RETRIEVE, headers=h, params={"q": "budget", "bm25": "false", "vector": "false"}
    )
    assert r.status_code == 422
    assert "at least one search method" in r.json()["detail"]


def test_unknown_target_is_rejected(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)

    r = client.get(RETRIEVE, headers=h, params={"q": "budget", "targets": ["banana"]})
    assert r.status_code == 422


def test_empty_query_is_rejected(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)
    assert client.get(RETRIEVE, headers=h, params={"q": ""}).status_code == 422


def test_requires_authentication(client: TestClient) -> None:
    assert client.get(RETRIEVE, params={"q": "budget"}).status_code == 401


def test_a_read_scoped_api_key_can_retrieve(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)
    key = client.post(
        f"{API}/api-keys/", headers=h, json={"name": "reader", "scope": "read"}
    ).json()["key"]

    r = client.get(
        RETRIEVE,
        headers={"Authorization": f"Bearer {key}"},
        params={"q": "budget"},
    )
    assert r.status_code == 200
    assert r.json()["data"]


def test_rrf_k_is_echoed_back(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)
    body = client.get(RETRIEVE, headers=h, params={"q": "budget", "rrf_k": 5}).json()
    assert body["rrf_k"] == 5


def test_limit_caps_the_number_of_hits(client: TestClient, corpus: tuple) -> None:
    owner, password, *_ = corpus
    h = login(client, owner, password)
    body = client.get(
        RETRIEVE, headers=h, params={"q": "budget kitchen", "limit": 1}
    ).json()
    assert len(body["data"]) == 1
    assert body["count"] == 1
