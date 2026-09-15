from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

import httpx

from app.core.config import settings
from app.models import UsageKind
from app.services.model_client import (
    ModelServerError,
    make_http_client,
    post_json_with_cold_start_retry,
)
from app.services.usage import Counts, UsageMeter, read_usage, response_model

logger = logging.getLogger(__name__)


class LLMTask(StrEnum):
    """What the model is being asked to do, which decides which model answers."""

    answer = "answer"  # Ask: reading pages and writing a reply for a person
    translation = "translation"  # rewriting one page in another language
    indexing = "indexing"  # chunking and summarising, in the worker


def task_models(task: LLMTask | None) -> tuple[str, list[str]]:
    """The model for a task, and the ones to try if it fails."""
    if task is None:
        return settings.LLM_MODEL, _split(settings.LLM_FALLBACK_MODELS)
    match task:
        case LLMTask.answer:
            return settings.LLM_ANSWER_MODEL, _split(
                settings.LLM_ANSWER_FALLBACK_MODELS
            )
        case LLMTask.translation:
            return settings.LLM_TRANSLATION_MODEL, _split(
                settings.LLM_TRANSLATION_FALLBACK_MODELS
            )
        case LLMTask.indexing:
            return settings.LLM_INDEXING_MODEL, _split(
                settings.LLM_INDEXING_FALLBACK_MODELS
            )


def _split(value: str) -> list[str]:
    return [m.strip() for m in (value or "").split(",") if m.strip()]


# How much room a second attempt gets when the first came back empty.
THINKING_BUDGET_FACTOR = 8
THINKING_BUDGET_FLOOR = 4096

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(ModelServerError):
    pass


class LLMClient:
    """A chat model, chosen by the task it is being used for.

    ``LLMClient(task=LLMTask.translation)`` takes that task's model and its
    fallbacks; passing ``model=`` explicitly overrides both, which is what the
    tests and one-off callers do.
    """

    def __init__(
        self,
        base_url: str = str(settings.LLM_BASE_URL),
        model: str | None = None,
        temperature: float = settings.LLM_TEMPERATURE,
        disable_thinking: bool = settings.LLM_DISABLE_THINKING,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        task: LLMTask | None = None,
        fallback_models: list[str] | None = None,
        meter: UsageMeter | None = None,
    ) -> None:
        chosen, fallbacks = task_models(task)
        self.base_url = base_url.rstrip("/")
        self.task = task
        # A model named outright is the whole instruction: falling back to
        # something else would quietly answer as a model nobody asked for.
        self.model = chosen if model is None else model
        self.fallback_models = (
            fallback_models
            if fallback_models is not None
            else (fallbacks if model is None else [])
        )
        self.temperature = temperature
        self.disable_thinking = disable_thinking
        self.api_key = settings.LLM_API_KEY if api_key is None else api_key
        # Who to bill this to. A client built without one still works; it is
        # simply not counted, which is what tests and one-off scripts want.
        self.meter = meter
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
        model: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if self.fallback_models and model is None:
            # OpenRouter reads this and re-routes server-side, which is faster
            # than a failed round trip and a second request. Providers that do
            # not understand it drop it, and `_with_fallback` below covers them.
            body["models"] = [self.model, *self.fallback_models]
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
        meter: UsageMeter | None = None,
    ) -> str:
        """Ask the task's model, and the ones behind it if that one will not answer.

        A model being unavailable is not the same as a question being
        unanswerable: providers rate-limit, drop capacity and retire model ids,
        and a translation that fails because one id was busy is a worse outcome
        than the same translation from the second model on the list.
        """
        attempts = [self.model, *self.fallback_models]
        last: Exception | None = None
        meter = meter or self.meter
        for position, model in enumerate(attempts):
            final = position + 1 == len(attempts)
            try:
                return await self._chat_once(
                    messages,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    meter=meter,
                    # The first attempt carries the `models` array, so a
                    # provider that routes server-side has already tried the
                    # whole list by the time it fails.
                    model=None if position == 0 else model,
                    # Waiting out a busy or unreachable server is what to do
                    # when there is nothing else to ask - a local server really
                    # is starting a model. With another model on the list,
                    # spending two minutes first is the wrong trade.
                    cold_start_wait=None if final else 0.0,
                )
            except (ModelServerError, httpx.HTTPError) as exc:
                last = exc
                if meter is not None:
                    meter.failure(UsageKind.chat, model)
                if position + 1 < len(attempts):
                    logger.warning(
                        "llm: %s failed (%s); trying %s",
                        model,
                        str(exc)[:160],
                        attempts[position + 1],
                    )
        raise last if last is not None else LLMError("llm: no model to call")

    async def _chat_once(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float | None = None,
        model: str | None = None,
        cold_start_wait: float | None = None,
        meter: UsageMeter | None = None,
    ) -> str:
        budget = max_tokens
        for attempt in (1, 2):
            body = self._body(
                messages,
                json_mode=json_mode,
                max_tokens=budget,
                temperature=temperature,
                model=model,
            )
            data = await post_json_with_cold_start_retry(
                self.client,
                f"{self.base_url}/chat/completions",
                body,
                what="llm",
                max_wait=cold_start_wait,
            )
            # Recorded before the body is inspected: a response that arrived
            # was paid for, whether or not it turns out to be usable. The
            # second attempt below is a second billed call and lands here too.
            if meter is not None:
                meter.record(UsageKind.chat, data, model=model or self.model)
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
        meter: UsageMeter | None = None,
    ) -> AsyncIterator[str]:
        """Yield answer text as the model produces it.

        Answers take tens of seconds on a local model, so the caller streams them
        to the reader instead of showing a spinner. Reasoning models emit their
        thinking in a separate field, which is skipped - only the visible answer
        is yielded.

        Falling back to another model is only possible before the first token:
        once text is on its way to a reader, switching models would splice two
        different answers together, so a failure after that point is raised.
        """
        attempts = [self.model, *self.fallback_models]
        meter = meter or self.meter
        for position, model in enumerate(attempts):
            last = position + 1 == len(attempts)
            try:
                async for piece in self._stream_once(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=None if position == 0 else model,
                    meter=meter,
                ):
                    yield piece
                return
            except (ModelServerError, httpx.HTTPError) as exc:
                if meter is not None:
                    meter.failure(UsageKind.chat, model)
                if last:
                    raise
                logger.warning(
                    "llm: %s failed before writing anything (%s); trying %s",
                    model,
                    str(exc)[:160],
                    attempts[position + 1],
                )

    async def _stream_once(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        model: str | None = None,
        meter: UsageMeter | None = None,
    ) -> AsyncIterator[str]:
        body = self._body(
            messages,
            json_mode=False,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
        )
        body["stream"] = True
        # OpenRouter sends the usage block on the final chunk regardless, but
        # this is the documented switch and other providers want asking.
        body["usage"] = {"include": True}
        headers = {"Accept": "text/event-stream"}
        billed = False
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
                # The last chunk carries the usage block and an empty delta, so
                # it is the one place a streamed answer says what it cost. It
                # used to fall through the `if piece:` below and be lost.
                if isinstance(chunk, dict) and chunk.get("usage"):
                    served = response_model(chunk, model or self.model)
                    counts = read_usage(chunk)
                    if meter is not None:
                        meter.record_counts(UsageKind.chat, served, counts)
                    billed = True
                try:
                    delta = chunk["choices"][0]["delta"]
                except KeyError, IndexError, TypeError:
                    continue
                piece = delta.get("content")
                if piece:
                    yield str(piece)
        if not billed and meter is not None:
            # A provider that streams without ever reporting usage still made a
            # call we paid for; count the call even though the tokens are lost.
            meter.record_counts(UsageKind.chat, model or self.model, Counts(requests=1))


def clean_completion(text: str) -> str:
    text = _THINK_RE.sub("", text).strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    return text
