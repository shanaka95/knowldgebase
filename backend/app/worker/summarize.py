"""Document summaries via the LLM (map-reduce for long documents)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.content import Block, blocks_to_text
from app.services.llm import LLMClient, LLMError
from app.services.usage import UsageMeter
from app.worker.chunking import make_windows

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM = (
    "You write concise, factual summaries of knowledge-base documents. "
    "Summarise the document in 3 to 6 sentences (at most 150 words). "
    "Mention the main subject and the key facts or decisions. "
    "No preamble, no bullet points, no markdown - plain prose only."
)
PARTIAL_SYSTEM = (
    "You write concise, factual summaries. Summarise this part of a longer document "
    "in at most 80 words of plain prose. No preamble."
)
REDUCE_SYSTEM = (
    "You combine partial summaries of one document into a single coherent summary of "
    "3 to 6 sentences (at most 150 words), plain prose, no preamble."
)

Checkpoint = Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


async def _chat(
    llm: LLMClient,
    system: str,
    user: str,
    max_tokens: int,
    meter: UsageMeter | None = None,
) -> str:
    text = await llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        meter=meter,
    )
    text = text.strip().strip('"').strip()
    if not text:
        raise LLMError("llm: empty summary")
    return text


async def summarize(
    llm: LLMClient,
    title: str,
    blocks: list[Block],
    *,
    checkpoint: Checkpoint | None = None,
    window_chars: int | None = None,
    meter: UsageMeter | None = None,
) -> str | None:
    """Return a 3–6 sentence summary, or ``None`` for an empty document."""
    checkpoint = checkpoint or _noop
    window_chars = window_chars or settings.LLM_WINDOW_CHARS
    text = blocks_to_text(blocks)
    if not text.strip():
        return None

    windows = make_windows(blocks, window_chars)
    if len(windows) == 1:
        await checkpoint()
        return await _chat(
            llm,
            SUMMARY_SYSTEM,
            f"Title: {title}\n\n{text}",
            max_tokens=400,
            meter=meter,
        )

    partials: list[str] = []
    for idx, (start, end) in enumerate(windows, start=1):
        await checkpoint()
        part_text = blocks_to_text(blocks[start - 1 : end])
        partials.append(
            await _chat(
                llm,
                PARTIAL_SYSTEM,
                f"Title: {title}\nPart {idx} of {len(windows)}\n\n{part_text}",
                max_tokens=200,
                meter=meter,
            )
        )
    await checkpoint()
    joined = "\n\n".join(f"Part {i}: {p}" for i, p in enumerate(partials, start=1))
    return await _chat(
        llm, REDUCE_SYSTEM, f"Title: {title}\n\n{joined}", max_tokens=400, meter=meter
    )
