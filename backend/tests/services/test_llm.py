"""The chat client, and what it does when a model thinks instead of answering.

Reasoning models emit hidden thinking that counts against the same token budget
as the answer. If that budget runs out first the provider returns a completion
with no content at all, which is how a whole document once failed to be indexed.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.llm import LLMClient, LLMError, LLMTask, clean_completion
from app.services.model_client import ModelServerError

pytestmark = pytest.mark.anyio

URL = f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def completion(content: str | None, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": content}, "finish_reason": finish_reason}
            ]
        },
    )


async def _chat(**kwargs: object) -> str:
    llm = LLMClient()
    try:
        return await llm.chat([{"role": "user", "content": "hi"}], **kwargs)  # type: ignore[arg-type]
    finally:
        await llm.close()


async def test_thinking_is_switched_off_in_both_dialects() -> None:
    """Local servers read the chat template argument; OpenRouter reads `reasoning`."""
    with respx.mock:
        route = respx.post(URL).mock(return_value=completion("done"))
        await _chat()
    body = json.loads(route.calls[0].request.content)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["reasoning"] == {"enabled": False}


async def test_a_model_that_thinks_anyway_gets_a_second_larger_budget() -> None:
    with respx.mock:
        route = respx.post(URL).mock(
            side_effect=[completion(None, "length"), completion("the answer")]
        )
        assert await _chat(max_tokens=200) == "the answer"
    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)["max_tokens"]
    second = json.loads(route.calls[1].request.content)["max_tokens"]
    assert first == 200
    assert second > first, "the retry is only worth making with more room"


async def test_the_larger_budget_is_tried_once_and_then_reported() -> None:
    """Two empty completions are a real failure; retrying forever would hide it."""
    with respx.mock:
        route = respx.post(URL).mock(
            side_effect=[completion(None, "length"), completion(None, "length")]
        )
        with pytest.raises(LLMError, match="hidden reasoning"):
            await _chat(max_tokens=200)
    assert route.call_count == 2


async def test_an_empty_completion_for_any_other_reason_is_not_retried() -> None:
    """Nothing about a content filter or a stop token improves with more tokens."""
    with respx.mock:
        route = respx.post(URL).mock(return_value=completion(None, "content_filter"))
        with pytest.raises(LLMError, match="content_filter"):
            await _chat(max_tokens=200)
    assert route.call_count == 1


async def test_a_request_already_at_the_ceiling_is_not_retried() -> None:
    """There is no more room to give, so a second call would only cost money."""
    with respx.mock:
        route = respx.post(URL).mock(
            side_effect=[completion(None, "length"), completion("ok")]
        )
        with pytest.raises(LLMError):
            await _chat(max_tokens=settings.LLM_MAX_OUTPUT_TOKENS)
    assert route.call_count == 1


async def test_the_retry_stays_within_the_ceiling() -> None:
    with respx.mock:
        route = respx.post(URL).mock(
            side_effect=[completion(None, "length"), completion("ok")]
        )
        await _chat(max_tokens=settings.LLM_MAX_OUTPUT_TOKENS // 2)
    second = json.loads(route.calls[1].request.content)["max_tokens"]
    assert second == settings.LLM_MAX_OUTPUT_TOKENS


async def test_a_malformed_response_says_so() -> None:
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(200, json={"nope": 1}))
        with pytest.raises(LLMError, match="malformed"):
            await _chat()


async def test_thinking_tags_and_code_fences_are_stripped() -> None:
    assert clean_completion("<think>hmm</think>Answer.") == "Answer."
    assert clean_completion('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert clean_completion("plain") == "plain"


# ---------------------------------------------------------------------------
# A model per task
# ---------------------------------------------------------------------------


async def test_each_task_asks_for_its_own_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_TRANSLATION_MODEL", "cheap/translator")
    monkeypatch.setattr(settings, "LLM_TRANSLATION_FALLBACK_MODELS", "")
    llm = LLMClient(task=LLMTask.translation)
    try:
        with respx.mock:
            route = respx.post(URL).mock(return_value=completion("hallo"))
            await llm.chat([{"role": "user", "content": "hi"}])
    finally:
        await llm.close()
    assert json.loads(route.calls[0].request.content)["model"] == "cheap/translator"


async def test_a_model_named_outright_is_not_second_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`model=` is the whole instruction; a fallback would answer as another model."""
    monkeypatch.setattr(settings, "LLM_ANSWER_FALLBACK_MODELS", "some/fallback")
    assert LLMClient(model="exactly/this").fallback_models == []


async def test_the_fallback_model_answers_when_the_first_one_will_not() -> None:
    """A busy provider is a reason to ask another model, not to wait two minutes."""
    llm = LLMClient(model="first/model", fallback_models=["second/model"])
    try:
        with respx.mock:
            route = respx.post(URL).mock(
                side_effect=[
                    httpx.Response(429, json={"error": "busy"}),
                    completion("ok"),
                ]
            )
            assert await llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    finally:
        await llm.close()
    assert route.call_count == 2
    assert json.loads(route.calls[1].request.content)["model"] == "second/model"


async def test_the_original_failure_is_reported_when_every_model_fails() -> None:
    llm = LLMClient(model="first/model", fallback_models=["second/model"])
    try:
        with respx.mock:
            route = respx.post(URL).mock(return_value=httpx.Response(500, text="down"))
            with pytest.raises(ModelServerError):
                await llm.chat([{"role": "user", "content": "hi"}])
    finally:
        await llm.close()
    assert route.call_count == 2, "each model is tried exactly once"


async def test_the_whole_list_travels_so_a_router_can_do_it_server_side() -> None:
    """OpenRouter re-routes without a second round trip when it sees `models`."""
    llm = LLMClient(model="first/model", fallback_models=["second/model"])
    try:
        with respx.mock:
            route = respx.post(URL).mock(return_value=completion("ok"))
            await llm.chat([{"role": "user", "content": "hi"}])
    finally:
        await llm.close()
    body = json.loads(route.calls[0].request.content)
    assert body["models"] == ["first/model", "second/model"]


async def test_one_model_sends_no_models_array() -> None:
    llm = LLMClient(model="only/model")
    try:
        with respx.mock:
            route = respx.post(URL).mock(return_value=completion("ok"))
            await llm.chat([{"role": "user", "content": "hi"}])
    finally:
        await llm.close()
    assert "models" not in json.loads(route.calls[0].request.content)


async def test_a_stream_that_fails_before_a_token_falls_back() -> None:
    llm = LLMClient(model="first/model", fallback_models=["second/model"])
    stream = (
        "".join(
            f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n"
            for piece in ["par", "tial"]
        )
        + "data: [DONE]\n\n"
    )
    try:
        with respx.mock:
            route = respx.post(URL).mock(
                side_effect=[
                    httpx.Response(503, text="no capacity"),
                    httpx.Response(200, content=stream.encode()),
                ]
            )
            pieces = [
                p async for p in llm.stream_chat([{"role": "user", "content": "hi"}])
            ]
    finally:
        await llm.close()
    assert "".join(pieces) == "partial"
    assert route.call_count == 2
