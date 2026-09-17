"""Saying what is in a sketch, so it can be found.

A drawing has no words. Left alone it is findable only by whatever its author
happened to type in the title box, which for most sketches is nothing at all -
and a note you cannot find is a note you did not keep.

So the worker shows the picture to the vision model once per version and writes
what comes back into the note's text. That is what `content_text` is for: one
column, three kinds of note, one indexing pipeline.

Two deliberate limits:

* **It runs in the worker, not in the request.** Saving a sketch must not wait
  on a vision model, and a failed description must not fail a save. A drawing
  with no description is simply a drawing that is findable by its title until
  the next pass.
* **It uses the chat model, not the parser role.** The parser role is MinerU,
  a document-layout model: it reads a scanned invoice, and a hand-drawn arrow
  between two boxes is not a document. `LLMPageParser` already treats the chat
  model as the general vision model for exactly this reason, and this follows
  it rather than adding a fourth configured endpoint to get wrong.

The description is *written down as text*, not as a caption shown to anybody.
Nobody reads it - the search index does.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.core.config import settings
from app.models import UsageKind
from app.services.model_client import ModelServerError, make_http_client
from app.services.usage import UsageMeter

logger = logging.getLogger(__name__)

# Written for retrieval, not for a reader. What matters is that the words
# somebody would search for appear: the objects, the labels, the handwriting.
PROMPT = """You are describing a hand-drawn note so that it can be found again by search.

Write a short, plain description of what is drawn. Then, on their own lines, transcribe every piece of handwritten or typed text exactly as it appears, including labels, numbers and arrows' captions.

Rules:
- No preamble, no heading, no markdown, no bullet characters.
- Do not guess at meaning the drawing does not have, and do not say "the image shows".
- If there is no text in the drawing, write only the description.
- Keep it under 120 words."""

# Long enough for a description and the writing in a sketch; short enough that a
# model which starts rambling cannot run up a bill.
MAX_TOKENS = 700


def _data_url(image: bytes, content_type: str) -> str:
    kind = (content_type or "image/png").split(";")[0].strip() or "image/png"
    return f"data:{kind};base64,{base64.b64encode(image).decode('ascii')}"


async def describe_drawing(
    image: bytes,
    *,
    content_type: str = "image/png",
    meter: UsageMeter | None = None,
) -> str:
    """What is in this picture, in words. Empty when it could not be read.

    Never raises. A description is an improvement to a note, and an improvement
    that fails is not a reason to leave the note unindexed.
    """
    if not image:
        return ""

    base_url = str(settings.LLM_BASE_URL).rstrip("/")
    model = settings.LLM_MODEL
    api_key = settings.LLM_API_KEY

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(image, content_type)},
                    },
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
    }
    if settings.LLM_DISABLE_THINKING:
        body["chat_template_kwargs"] = {"enable_thinking": False}

    try:
        async with make_http_client(settings.LLM_TIMEOUT_SECONDS, api_key) as client:
            response = await client.post(f"{base_url}/chat/completions", json=body)
        if response.status_code >= 400:
            if meter is not None:
                meter.failure(UsageKind.chat, model)
            raise ModelServerError(
                f"drawing: HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if meter is not None:
            meter.record(UsageKind.chat, data, model=model)
        content = data["choices"][0]["message"].get("content") or ""
    except Exception as exc:  # noqa: BLE001 - a description is not worth a job
        logger.info("drawing: could not describe (%s)", exc)
        return ""

    from app.services.llm import clean_completion

    return clean_completion(str(content)).strip()[:4000]
