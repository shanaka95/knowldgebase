"""Ask: hybrid search feeds the model, and the answer is grounded in what it found."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_embedding_client
from app.core.config import settings
from app.main import app
from app.services.answering import NO_CONTEXT_ANSWER
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
ASK_CONTEXT = f"{API}/ask/context"
ASK_STREAM = f"{API}/ask/stream"
LLM_URL = f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions"


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


def _completion(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {},
    }


def _sse(pieces: list[str]) -> bytes:
    lines = []
    for piece in pieces:
        chunk = {"choices": [{"delta": {"content": piece}}]}
        lines.append(f"data: {json.dumps(chunk)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


async def _seed(
    db: Session, store: InMemoryVectorStore, headers_owner: Any
) -> tuple[Any, Any]:
    """One space with a VPN page (chunked) and an unrelated budget page."""
    owner, pw = headers_owner
    ns = create_namespace(db, owner)
    vpn = create_document(
        db,
        ns,
        owner,
        title="Connecting to the VPN",
        html="<p>Error 407 means your token expired; request a new one.</p>",
    )
    budget = create_document(
        db,
        ns,
        owner,
        title="Budget review",
        html="<p>Cloud budget rose because of GPU nodes.</p>",
    )
    await _index(
        store,
        db,
        vpn,
        chunks=["Error 407 means your vpn token expired; request a new one."],
        summary="How to connect to the vpn and fix common errors.",
    )
    await _index(store, db, budget, summary="Why the budget for cloud went up.")
    db.commit()
    return ns, vpn


@pytest.mark.anyio
async def test_answer_is_grounded_and_cites_the_page_it_used(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    ns, vpn = await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200, json=_completion("Request a new token from the IT portal [1].")
            )
        )
        r = client.post(
            ASK, headers=headers, json={"q": "what does vpn error 407 mean"}
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].startswith("Request a new token")
    assert body["used"] >= 1
    assert body["model"] == settings.LLM_MODEL

    # the excerpt the model cited is flagged, and points at a real page
    cited = [c for c in body["citations"] if c["cited"]]
    assert len(cited) == 1
    assert cited[0]["index"] == 1
    assert cited[0]["namespace_slug"] == ns.slug
    assert cited[0]["text"]

    # the model only ever saw the excerpts we handed it
    sent = json.loads(route.calls[0].request.content)
    prompt = "\n".join(m["content"] for m in sent["messages"])
    assert "what does vpn error 407 mean" in prompt
    assert "Error 407" in prompt
    assert "[1]" in prompt


@pytest.mark.anyio
async def test_uncited_excerpts_are_returned_but_not_marked(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("Only this one [1]."))
        )
        body = client.post(ASK, headers=headers, json={"q": "vpn budget"}).json()

    assert len(body["citations"]) >= 1
    assert sum(1 for c in body["citations"] if c["cited"]) == 1, (
        "the reader still sees every excerpt, but only the used one is marked"
    )


@pytest.mark.anyio
async def test_nothing_found_refuses_instead_of_calling_the_model(
    client: TestClient,
    db: Session,
    store: InMemoryVectorStore,  # noqa: ARG001 - empties the vector store
) -> None:
    """An empty knowledge base must not produce an invented answer."""
    owner, pw = create_user_with_password(db)
    create_namespace(db, owner)
    headers = login(client, owner, pw)

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("I know everything!"))
        )
        body = client.post(
            ASK, headers=headers, json={"q": "what is the capital of peru"}
        ).json()

    assert body["answer"] == NO_CONTEXT_ANSWER
    assert body["citations"] == []
    assert body["used"] == 0
    assert not route.called, "with no excerpts there is nothing to ask the model"


@pytest.mark.anyio
async def test_other_peoples_pages_are_never_used_as_context(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, _ = create_user_with_password(db)
    stranger, stranger_pw = create_user_with_password(db)
    await _seed(db, store, (owner, "x"))
    headers = login(client, stranger, stranger_pw)

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("nothing"))
        )
        body = client.post(ASK, headers=headers, json={"q": "vpn error 407"}).json()

    assert body["citations"] == []
    assert body["answer"] == NO_CONTEXT_ANSWER
    assert not route.called


@pytest.mark.anyio
async def test_top_k_limits_how_many_pages_reach_the_model(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("short [1]"))
        )
        body = client.post(
            ASK, headers=headers, json={"q": "vpn budget", "top_k": 1}
        ).json()

    assert body["used"] == 1, "one page reached the model"
    assert {c["document_id"] for c in body["citations"]} == {
        c["document_id"] for c in body["citations"]
    }


def test_an_empty_question_is_rejected(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    headers = login(client, owner, pw)
    assert client.post(ASK, headers=headers, json={"q": "   "}).status_code == 422
    assert client.post(ASK, headers=headers, json={"q": ""}).status_code == 422


def test_asking_requires_authentication(client: TestClient) -> None:
    assert client.post(ASK, json={"q": "anything"}).status_code == 401


@pytest.mark.anyio
async def test_a_page_that_matched_in_several_places_is_sent_once_and_whole(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Chunks find a page; the whole page is what gets read.

    Sending an excerpt per match spends the budget on one document several
    times, invites the model to cite it as though it were several sources, and
    still omits what sits between the matches - the sentence qualifying the
    figure, the row above the total.
    """
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    invoice = create_document(
        db,
        ns,
        owner,
        title="Invoice",
        html=(
            "<p>Customer address and contact details for the vpn account.</p>"
            "<p>Total due is 262.12 EUR for the vpn service period.</p>"
            "<p>Payment history and mandate details for the vpn contract.</p>"
        ),
    )
    await _index(
        store,
        db,
        invoice,
        chunks=[
            "Customer address and contact details for the vpn account.",
            "Total due is 262.12 EUR for the vpn service period.",
            "Payment history and mandate details for the vpn contract.",
        ],
        summary="An invoice for the vpn service.",
    )
    db.commit()
    headers = login(client, owner, pw)

    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["prompt"] = request.content.decode()
        return httpx.Response(200, json=_completion("262.12 EUR [1]."))

    with respx.mock:
        respx.post(LLM_URL).mock(side_effect=_capture)
        body = client.post(ASK, headers=headers, json={"q": "vpn total due"}).json()

    assert body["used"] == 1, "one page"
    assert body["passages"] == 1, "sent once, not once per matching section"
    assert len(body["citations"]) == 1

    # And the model saw the parts that did not match, not only the one that did.
    prompt = captured["prompt"]
    assert "Total due is 262.12 EUR" in prompt
    assert "Customer address" in prompt, "the whole page, including what did not match"
    assert "Payment history" in prompt


@pytest.mark.anyio
async def test_context_hands_over_the_pages_without_writing_an_answer(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """The caller that will phrase the reply gets the sources, not a summary.

    Every MCP caller is itself a model with a reply to write. Answering here
    and letting it rewrite that answer spends a second generation to say the
    same thing slightly less accurately, so this endpoint stops at the pages.
    """
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        llm = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("should not be called"))
        )
        body = client.post(
            ASK_CONTEXT, headers=headers, json={"q": "vpn error 407"}
        ).json()

    assert not llm.called, "no answer is written, so no model is paid for"
    assert body["documents"], "the pages it would have answered from"
    assert body["used"] >= 1
    titles = [d["title"] for d in body["documents"]]
    assert "Connecting to the VPN" in titles


@pytest.mark.anyio
async def test_context_returns_whole_pages_not_excerpts(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """A caller answering from these needs the parts that did not match too."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    invoice = create_document(
        db,
        ns,
        owner,
        title="Invoice",
        html=(
            "<p>Customer address and contact details for the vpn account.</p>"
            "<p>Total due is 262.12 EUR for the vpn service period.</p>"
            "<p>Payment history and mandate details for the vpn contract.</p>"
        ),
    )
    await _index(
        store,
        db,
        invoice,
        chunks=[
            "Customer address and contact details for the vpn account.",
            "Total due is 262.12 EUR for the vpn service period.",
            "Payment history and mandate details for the vpn contract.",
        ],
        summary="An invoice for the vpn service.",
    )
    db.commit()
    headers = login(client, owner, pw)

    body = client.post(ASK_CONTEXT, headers=headers, json={"q": "vpn total due"}).json()

    assert body["passages"] == 1, "one page, sent once"
    text = body["documents"][0]["text"]
    assert "Total due is 262.12 EUR" in text
    assert "Customer address" in text, "including what did not match"
    assert "Payment history" in text


@pytest.mark.anyio
async def test_context_is_scoped_to_the_caller(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Skipping the answer must not skip the access check."""
    owner, owner_pw = create_user_with_password(db)
    await _seed(db, store, (owner, owner_pw))
    stranger, stranger_pw = create_user_with_password(db)
    headers = login(client, stranger, stranger_pw)

    body = client.post(ASK_CONTEXT, headers=headers, json={"q": "vpn error 407"}).json()

    assert body["documents"] == [], "another account's pages are not context"
    assert body["used"] == 0


def test_context_rejects_an_empty_question(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    headers = login(client, owner, pw)
    assert client.post(ASK_CONTEXT, headers=headers, json={"q": "   "}).status_code in (
        422,
    )


@pytest.mark.anyio
async def test_a_read_scoped_api_key_can_ask(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """Asking reads the knowledge base; it must not need write access."""
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)
    key = client.post(
        f"{API}/api-keys/", headers=headers, json={"name": "ro", "scope": "read"}
    ).json()["key"]

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("answer [1]"))
        )
        r = client.post(
            ASK,
            headers={"Authorization": f"Bearer {key}"},
            json={"q": "vpn error 407"},
        )
    assert r.status_code == 200


# ----------------------------------------------------------------- streaming


@pytest.mark.anyio
async def test_streaming_sends_sources_first_then_the_answer(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200,
                stream=httpx.ByteStream(_sse(["Request ", "a new token ", "[1]."])),
                headers={"Content-Type": "text/event-stream"},
            )
        )
        with client.stream(
            "POST", ASK_STREAM, headers=headers, json={"q": "vpn error 407"}
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            body = "".join(response.iter_text())

    events = [line[7:] for line in body.splitlines() if line.startswith("event: ")]
    payloads = [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")
    ]

    assert events[0] == "conversation", "the thread is named before anything else"
    assert payloads[0]["id"]
    assert events[1] == "sources", "citations arrive before the answer is written"
    assert events[-1] == "done"
    assert events.count("delta") == 3
    assert payloads[1]["used"] >= 1
    assert payloads[1]["citations"][0]["title"]

    answer = "".join(
        p["text"] for e, p in zip(events, payloads, strict=True) if e == "delta"
    )
    assert answer == "Request a new token [1]."
    assert payloads[-1]["cited"] == [1]


@pytest.mark.anyio
async def test_a_model_failure_mid_stream_is_reported_not_swallowed(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(side_effect=httpx.ConnectError("model server down"))
        with client.stream(
            "POST", ASK_STREAM, headers=headers, json={"q": "vpn error 407"}
        ) as response:
            body = "".join(response.iter_text())

    events = [line[7:] for line in body.splitlines() if line.startswith("event: ")]
    assert "error" in events, "the reader is told, rather than left with a dead stream"
    assert events[-1] == "done"


@pytest.mark.anyio
async def test_an_unchunked_page_sends_its_text_not_its_summary(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """A summary is written for matching and drops specifics; an answer needs the
    figures that only survive in the page itself."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    page = create_document(
        db,
        ns,
        owner,
        title="Costs",
        html="<p>Compute for the vpn cluster rose to 57,500 EUR this quarter.</p>",
    )
    await _index(store, db, page, summary="A page about vpn cluster spending.")
    db.commit()
    headers = login(client, owner, pw)

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("57,500 EUR [1]."))
        )
        client.post(ASK, headers=headers, json={"q": "vpn cluster cost"})

    sent = json.loads(route.calls[0].request.content)["messages"]
    prompt = "\n".join(m["content"] for m in sent)
    assert "57,500" in prompt, "the figure must reach the model"


# ---------------------------------------------------------------------------
# A pinned page
# ---------------------------------------------------------------------------


class ExplodingEmbeddings:
    """Proves a code path never embeds anything - the call would fail loudly."""

    async def embed(self, texts: list[str], **_: object) -> list[list[float]]:
        raise AssertionError("a pinned page must not embed the question")

    async def embed_query(self, text: str, **_: object) -> list[float]:
        raise AssertionError("a pinned page must not embed the question")


@pytest.mark.anyio
async def test_a_pinned_page_answers_from_that_page_without_searching(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """The reader named the page, so nothing is embedded, retrieved or reranked.

    This is the cheap path: the embedding client is replaced with one that
    raises, so a single vector call anywhere in the request fails the test.
    """
    owner, pw = create_user_with_password(db)
    _, vpn = await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)
    app.dependency_overrides[get_embedding_client] = ExplodingEmbeddings

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("Error 407 [1]."))
        )
        body = client.post(
            ASK,
            headers=headers,
            json={"q": "what does this page say", "document_id": str(vpn.id)},
        ).json()

    assert body["used"] == 1
    assert body["searched"] == 1
    assert body["reranked"] is False, "one chosen page has nothing to rank against"
    assert body["retrieval_ms"] < 50, "no search ran, so there was nothing to wait for"
    assert [c["document_id"] for c in body["citations"]] == [str(vpn.id)]
    assert "Error 407" in body["citations"][0]["text"]


@pytest.mark.anyio
async def test_a_page_the_asker_cannot_read_cannot_be_pinned(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, _ = create_user_with_password(db)
    stranger, stranger_pw = create_user_with_password(db)
    _, vpn = await _seed(db, store, (owner, "x"))
    headers = login(client, stranger, stranger_pw)

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("leaked"))
        )
        r = client.post(
            ASK, headers=headers, json={"q": "anything", "document_id": str(vpn.id)}
        )

    assert r.status_code in (403, 404)
    assert not route.called


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


CONVERSATIONS = f"{API}/ask/conversations"


def _stream(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]]]:
    with client.stream("POST", ASK_STREAM, headers=headers, json=payload) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    events = [line[7:] for line in body.splitlines() if line.startswith("event: ")]
    payloads = [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")
    ]
    return events, payloads


@pytest.mark.anyio
async def test_a_question_starts_a_thread_named_after_it(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["Request a token [1]."]))
        )
        events, payloads = _stream(client, headers, {"q": "what does vpn 407 mean"})

    assert events[0] == "conversation"
    conversation_id = payloads[0]["id"]
    assert payloads[0]["title"] == "what does vpn 407 mean"

    listed = client.get(CONVERSATIONS, headers=headers).json()
    assert listed["count"] == 1
    assert listed["data"][0]["id"] == conversation_id
    assert listed["data"][0]["message_count"] == 2

    detail = client.get(f"{CONVERSATIONS}/{conversation_id}", headers=headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "what does vpn 407 mean"
    assert detail["messages"][1]["content"] == "Request a token [1]."
    assert detail["messages"][1]["citations"][0]["cited"] is True
    assert detail["messages"][1]["stats"]["model"] == settings.LLM_MODEL


@pytest.mark.anyio
async def test_a_follow_up_carries_the_earlier_exchange_but_not_its_excerpts(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["Request a token [1]."]))
        )
        _, payloads = _stream(client, headers, {"q": "what does vpn 407 mean"})
    conversation_id = payloads[0]["id"]

    with respx.mock:
        route = respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["From the IT portal [1]."]))
        )
        _stream(
            client,
            headers,
            {"q": "and where do I get one?", "conversation_id": conversation_id},
        )

    messages = json.loads(route.calls[0].request.content)["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "what does vpn 407 mean"
    assert messages[2]["content"] == "Request a token [1]."
    assert messages[-1]["content"].endswith("and where do I get one?")

    detail = client.get(f"{CONVERSATIONS}/{conversation_id}", headers=headers).json()
    assert detail["message_count"] == 4
    assert [m["seq"] for m in detail["messages"]] == [1, 2, 3, 4]


@pytest.mark.anyio
async def test_a_thread_keeps_the_page_it_was_pinned_to(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    _, vpn = await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["It says 407 [1]."]))
        )
        _, payloads = _stream(
            client,
            headers,
            {"q": "summarise this page", "document_id": str(vpn.id)},
        )

    detail = client.get(f"{CONVERSATIONS}/{payloads[0]['id']}", headers=headers).json()
    assert detail["document_id"] == str(vpn.id)
    assert detail["document_title"] == "Connecting to the VPN"


@pytest.mark.anyio
async def test_a_stored_citation_keeps_a_preview_not_the_whole_page(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """A thread must not become a second copy of the knowledge base."""
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    page = create_document(
        db,
        ns,
        owner,
        title="Long page",
        html="<p>" + ("vpn token renewal steps. " * 400) + "</p>",
    )
    await _index(store, db, page, summary="vpn token renewal")
    db.commit()
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["See the page [1]."]))
        )
        _, payloads = _stream(client, headers, {"q": "vpn token renewal"})

    detail = client.get(f"{CONVERSATIONS}/{payloads[0]['id']}", headers=headers).json()
    stored = detail["messages"][1]["citations"][0]["text"]
    assert len(stored) <= settings.ASK_STORED_CITATION_CHARS + 2
    assert stored.endswith("…")


@pytest.mark.anyio
async def test_threads_are_private_to_the_person_who_asked(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    stranger, stranger_pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["Answer [1]."]))
        )
        _, payloads = _stream(client, headers, {"q": "vpn error 407"})
    conversation_id = payloads[0]["id"]

    other = login(client, stranger, stranger_pw)
    assert (
        client.get(f"{CONVERSATIONS}/{conversation_id}", headers=other).status_code
        == 404
    )
    assert client.get(CONVERSATIONS, headers=other).json()["count"] == 0
    assert (
        client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=other).status_code
        == 404
    )
    assert (
        client.post(
            ASK_STREAM,
            headers=other,
            json={"q": "sneak in", "conversation_id": conversation_id},
        ).status_code
        == 404
    )


@pytest.mark.anyio
async def test_a_thread_can_be_renamed_and_deleted(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, stream=_sse(["Answer [1]."]))
        )
        _, payloads = _stream(client, headers, {"q": "vpn error 407"})
    conversation_id = payloads[0]["id"]

    renamed = client.patch(
        f"{CONVERSATIONS}/{conversation_id}",
        headers=headers,
        json={"title": "VPN troubleshooting"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "VPN troubleshooting"

    assert (
        client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=headers).status_code
        == 200
    )
    assert client.get(CONVERSATIONS, headers=headers).json()["count"] == 0
