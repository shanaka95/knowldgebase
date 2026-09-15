"""What actually reaches the usage table when somebody uses the product.

`tests/services/test_usage.py` proves the meter reads and writes correctly.
This proves the meter is *wired in* - that asking a question and running a
search leave rows behind, attributed to the right account, naming the model
that answered rather than the one that was asked for.
"""

import json
import uuid
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.api.deps import get_embedding_client
from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.models import UsageDaily, UsageFeature, UsageKind
from app.services import usage
from app.services.model_client import ModelServerError
from app.services.vectors import InMemoryVectorStore
from tests.api.routes.test_ask import _seed
from tests.api.routes.test_retrieve import StubEmbeddings
from tests.utils.kb import API, create_user_with_password, login

ASK = f"{API}/ask/"
ASK_STREAM = f"{API}/ask/stream"
RETRIEVE = f"{API}/search/retrieve"
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


def _completion(text: str, *, model: str = "qwen/qwen3.7-flash") -> dict[str, Any]:
    """A completion carrying the usage block a real provider sends."""
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 64,
            "cost": 1.5e-05,
            "prompt_tokens_details": {"cached_tokens": 900},
        },
    }


def _sse(pieces: list[str], *, model: str = "qwen/qwen3.8-flash") -> bytes:
    """A stream ending the way OpenRouter's does: usage on the last chunk."""
    lines = [
        f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n"
        for p in pieces
    ]
    lines.append(
        "data: "
        + json.dumps(
            {
                "model": model,
                "choices": [{"delta": {"content": ""}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 800,
                    "completion_tokens": 25,
                    "cost": 7.32e-06,
                },
            }
        )
        + "\n\n"
    )
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _rows(user_id: uuid.UUID) -> list[UsageDaily]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(UsageDaily)
                .where(UsageDaily.user_id == user_id)
                .order_by(col(UsageDaily.kind))
            ).all()
        )


def _one(rows: list[UsageDaily], kind: UsageKind) -> UsageDaily:
    matching = [r for r in rows if r.kind == kind]
    assert len(matching) == 1, f"expected one {kind} row, got {len(matching)}"
    return matching[0]


@pytest.mark.anyio
async def test_asking_a_question_records_what_it_cost(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("Ask IT [1]."))
        )
        r = client.post(ASK, headers=headers, json={"q": "what does vpn 407 mean"})
    assert r.status_code == 200, r.text

    rows = _rows(owner.id)
    assert {row.feature for row in rows} == {UsageFeature.ask}

    assert _one(rows, UsageKind.feature).requests == 1, "one question asked"

    chat = _one(rows, UsageKind.chat)
    assert chat.input_tokens == 1200
    assert chat.output_tokens == 64
    assert chat.cached_tokens == 900
    assert chat.cost_nanos == 15_000
    # The model that answered, not the one configured. These differ on purpose.
    assert chat.model == "qwen/qwen3.7-flash" != settings.LLM_ANSWER_MODEL


@pytest.mark.anyio
async def test_a_streamed_answer_is_billed_from_its_final_chunk(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """The chunk that used to be dropped for having no text in it."""
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sse(["Request ", "a token [1]."]),
                headers={"Content-Type": "text/event-stream"},
            )
        )
        with client.stream(
            "POST", ASK_STREAM, headers=headers, json={"q": "vpn 407"}
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode()
    assert "Request " in body

    chat = _one(_rows(owner.id), UsageKind.chat)
    assert (chat.input_tokens, chat.output_tokens) == (800, 25)
    assert chat.cost_nanos == 7_320
    assert chat.model == "qwen/qwen3.8-flash"


@pytest.mark.anyio
async def test_searching_is_counted_even_when_the_embedding_was_cached(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    """The stub never makes an HTTP call, and the search still shows up.

    This is why there is a `feature` row at all: counting only model calls
    would make a cached search vanish from somebody's dashboard.
    """
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    for _ in range(3):
        r = client.get(RETRIEVE, headers=headers, params={"q": "vpn"})
        assert r.status_code == 200, r.text

    rows = [r for r in _rows(owner.id) if r.feature == UsageFeature.search]
    assert _one(rows, UsageKind.feature).requests == 3


@pytest.mark.anyio
async def test_usage_is_attributed_to_the_person_who_asked(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)
    bystander, _ = create_user_with_password(db)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("Ask IT [1]."))
        )
        client.post(ASK, headers=headers, json={"q": "what does vpn 407 mean"})

    assert _rows(owner.id)
    assert _rows(bystander.id) == []


@pytest.mark.anyio
async def test_a_model_that_will_not_answer_is_recorded_as_a_failure(
    client: TestClient, db: Session, store: InMemoryVectorStore
) -> None:
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    # The error propagates - a model that will not answer is a failed request,
    # not an empty answer. What matters here is that the attempt was recorded
    # on the way out.
    with respx.mock, pytest.raises(ModelServerError):
        respx.post(LLM_URL).mock(return_value=httpx.Response(400, json={"error": "no"}))
        client.post(ASK, headers=headers, json={"q": "what does vpn 407 mean"})

    chat = [row for row in _rows(owner.id) if row.kind == UsageKind.chat]
    assert chat, "a question that failed halfway still spent what it spent"
    assert sum(row.failures for row in chat) >= 1
    assert sum(row.cost_nanos for row in chat) == 0


@pytest.mark.anyio
async def test_a_broken_meter_does_not_break_the_answer(
    client: TestClient,
    db: Session,
    store: InMemoryVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounting is worth less than the thing it accounts for."""
    owner, pw = create_user_with_password(db)
    await _seed(db, store, (owner, pw))
    headers = login(client, owner, pw)

    def explode(*_: object, **__: object) -> None:
        raise RuntimeError("the usage table is on fire")

    monkeypatch.setattr(usage, "_upsert", explode)

    with respx.mock:
        respx.post(LLM_URL).mock(
            return_value=httpx.Response(200, json=_completion("Ask IT [1]."))
        )
        r = client.post(ASK, headers=headers, json={"q": "what does vpn 407 mean"})

    assert r.status_code == 200, r.text
    assert r.json()["answer"].startswith("Ask IT")
    assert _rows(owner.id) == []
