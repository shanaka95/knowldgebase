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
from app.services.llm import LLMClient, LLMError, clean_completion

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
