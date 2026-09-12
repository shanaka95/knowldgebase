from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.services.model_client import (
    ModelServerError,
    make_http_client,
    post_json_with_cold_start_retry,
)

logger = logging.getLogger(__name__)

# How much room a second attempt gets when the first came back empty.
THINKING_BUDGET_FACTOR = 8
THINKING_BUDGET_FLOOR = 4096

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(ModelServerError):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str = str(settings.LLM_BASE_URL),
        model: str = settings.LLM_MODEL,
        temperature: float = settings.LLM_TEMPERATURE,
        disable_thinking: bool = settings.LLM_DISABLE_THINKING,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.disable_thinking = disable_thinking
        self.api_key = settings.LLM_API_KEY if api_key is None else api_key
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_http_client(settings.LLM_TIMEOUT_SECONDS, self.api_key)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _body(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        max_tokens: int,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if self.disable_thinking:
            # Two switches, because no provider understands both. Local servers
            # (vMLX, vLLM, LM Studio) read the chat template argument; OpenRouter
            # drops unknown fields and reads `reasoning` instead. Whichever is
            # ignored costs nothing, and getting this wrong is expensive: a
            # reasoning model spends the whole token budget thinking and returns
            # an empty completion.
            body["chat_template_kwargs"] = {"enable_thinking": False}
            body["reasoning"] = {"enabled": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        budget = max_tokens
        for attempt in (1, 2):
            body = self._body(
                messages,
                json_mode=json_mode,
                max_tokens=budget,
                temperature=temperature,
            )
            data = await post_json_with_cold_start_retry(
                self.client, f"{self.base_url}/chat/completions", body, what="llm"
            )
            try:
                choice = data["choices"][0]
                content = choice["message"].get("content")
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"llm: malformed response: {str(data)[:300]}") from exc
            if content:
                return clean_completion(str(content))

            reason = choice.get("finish_reason")
            # A model that thinks anyway - because the provider ignored both
            # switches above - burns the budget before writing a word. One
            # larger attempt costs a few cents; failing loses the document.
            if attempt == 1 and reason == "length":
                budget = min(
                    max(budget * THINKING_BUDGET_FACTOR, THINKING_BUDGET_FLOOR),
                    settings.LLM_MAX_OUTPUT_TOKENS,
                )
                if budget > max_tokens:
                    logger.info(
                        "llm: empty completion at max_tokens=%s, retrying with %s",
                        max_tokens,
                        budget,
                    )
                    continue
            raise LLMError(
                f"llm: empty completion (finish_reason={reason}) "
                f"at max_tokens={budget}; the model may be spending its whole "
                "budget on hidden reasoning"
            )
        raise LLMError("llm: empty completion")  # pragma: no cover - unreachable

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yield answer text as the model produces it.

        Answers take tens of seconds on a local model, so the caller streams them
        to the reader instead of showing a spinner. Reasoning models emit their
        thinking in a separate field, which is skipped - only the visible answer
        is yielded.
        """
        body = self._body(
            messages, json_mode=False, max_tokens=max_tokens, temperature=temperature
        )
        body["stream"] = True
        headers = {"Accept": "text/event-stream"}
        async with self.client.stream(
            "POST", f"{self.base_url}/chat/completions", json=body, headers=headers
        ) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode(errors="replace")[:300]
                raise LLMError(f"llm: HTTP {response.status_code}: {detail}")
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"]
                except KeyError, IndexError, TypeError:
                    continue
                piece = delta.get("content")
                if piece:
                    yield str(piece)


def clean_completion(text: str) -> str:
    text = _THINK_RE.sub("", text).strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    return text
