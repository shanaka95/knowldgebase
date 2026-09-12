"""LLM-driven semantic chunking.

The document is presented to the model as numbered blocks ``[1] … [n]`` and the
model answers with *boundaries* only::

    {"chunks": [{"title": "…", "start": 1, "end": 4}, …]}

Chunk text is therefore always taken verbatim from the document; validation is
arithmetic (contiguous, in range, full coverage, no overlap). If the whole
document is one topic the model must return exactly one section, which we map to
"no chunks" (``llm_single_topic``). Invalid answers get one corrective re-ask and
then fall back to the deterministic chunker.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.content import Block
from app.models import ChunkingMethod
from app.services.llm import LLMClient, LLMError
from app.services.model_client import ModelServerError
from app.worker.fallback_chunker import (
    Chunk,
    fallback_chunk,
    render_range,
    title_for_range,
)

logger = logging.getLogger(__name__)

MIN_RANGE_CHARS = 120
BLOCK_DISPLAY_LIMIT = 2500

SYSTEM_PROMPT = """You split knowledge-base documents into sections by SUBJECT so that each section can be stored and retrieved on its own.

You receive the document title and its content as numbered blocks [1] … [N] (headings are marked with (H1), (H2), …).

Step 1 – list the distinct subjects. Judge by the CONTENT of the blocks, never by the document title: a page titled "Team notes", "Meeting minutes", "Handbook", "FAQ", "Weekly update" or "Checklist" is a container and usually holds several unrelated subjects. Two parts belong to different subjects when a reader looking for one of them would have no interest in the other (different project, department, process, product, policy, event or theme).

Step 2 – group CONSECUTIVE blocks into exactly one section per subject.

Rules:
- If every block is about ONE subject (one tool with its setup, configuration and troubleshooting; one project; one concept with its examples), return EXACTLY ONE section spanning blocks 1 to N. Do not split a single subject just because it has several paragraphs, headings or steps.
- If the blocks cover several unrelated subjects, return one section per subject. Example: a weekly team-notes page with a budget review, an office-etiquette reminder and a Python migration update has three subjects and therefore three sections, even though the page has one title.
- A heading starts a new section only when the text under it is about a different subject than the previous section.
- Never split one subject across sections. A section must contain at least one full sentence. The title block (if any) belongs to the first section.
- Sections must be in order, contiguous, non-overlapping and together cover every block from 1 to N.
- Give each section a short descriptive title (max 8 words) that names its subject, not the document.

Respond with JSON only, no explanations:
{"topics": ["subject 1", "subject 2"], "chunks": [{"title": "string", "start": <first block number>, "end": <last block number>}]}"""


class ChunkValidationError(ValueError):
    pass


@dataclass(slots=True)
class Range:
    title: str
    start: int
    end: int


@dataclass(slots=True)
class ChunkingResult:
    chunks: list[Chunk]
    method: ChunkingMethod
    stats: dict[str, Any] = field(default_factory=dict)


Checkpoint = Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def format_blocks(blocks: list[Block], offset: int = 0) -> str:
    lines = []
    for i, b in enumerate(blocks, start=1 + offset):
        text = b.text
        if len(text) > BLOCK_DISPLAY_LIMIT:
            text = text[:BLOCK_DISPLAY_LIMIT].rstrip() + " …"
        prefix = f"[{i}] "
        if b.is_heading:
            prefix += f"(H{b.level}) "
        lines.append(prefix + text)
    return "\n".join(lines)


def user_prompt(title: str, blocks: list[Block]) -> str:
    return (
        f"Title: {title}\nN = {len(blocks)}\n\n"
        f"{format_blocks(blocks)}\n\n"
        "List the distinct subjects, then return the JSON with one section per subject "
        f"covering blocks 1 to {len(blocks)} (exactly one section if it is all one subject)."
    )


# ---------------------------------------------------------------------------
# Parsing + validation
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    text = _THINK_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # locate the first balanced {...}
        start = text.find("{")
        if start == -1:
            raise ChunkValidationError("no JSON object in response") from None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : i + 1])
                        break
                    except json.JSONDecodeError as exc:
                        raise ChunkValidationError(f"invalid JSON: {exc.msg}") from None
        else:
            raise ChunkValidationError("unbalanced JSON object in response")
    if not isinstance(data, dict):
        raise ChunkValidationError("top-level JSON must be an object")
    return data


def parse_ranges(text: str, n: int) -> list[Range]:
    data = extract_json_object(text)
    raw = data.get("chunks", data.get("sections"))
    if not isinstance(raw, list) or not raw:
        raise ChunkValidationError('"chunks" must be a non-empty list')
    if len(raw) > n:
        raise ChunkValidationError(f"more sections ({len(raw)}) than blocks ({n})")
    ranges: list[Range] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChunkValidationError(f"section {i + 1} is not an object")
        try:
            start = int(item["start"])
            end = int(item["end"])
        except KeyError, TypeError, ValueError:
            raise ChunkValidationError(
                f"section {i + 1} must have integer start and end"
            ) from None
        if start < 1 or end > n or start > end:
            raise ChunkValidationError(
                f"section {i + 1} range {start}-{end} is outside 1..{n} or reversed"
            )
        title = str(item.get("title") or "").strip()
        ranges.append(Range(title=title, start=start, end=end))
    ranges.sort(key=lambda r: (r.start, r.end))
    for prev, cur in zip(ranges, ranges[1:], strict=False):
        if cur.start <= prev.end:
            raise ChunkValidationError(
                f"sections overlap: {prev.start}-{prev.end} and {cur.start}-{cur.end}"
            )
    return ranges


def repair_ranges(ranges: list[Range], blocks: list[Block]) -> list[Range]:
    """Fill gaps (extend the previous range) and merge tiny ranges into a neighbour."""
    n = len(blocks)
    fixed: list[Range] = []
    for r in ranges:
        if not fixed:
            r.start = 1
        else:
            prev = fixed[-1]
            if r.start > prev.end + 1:
                prev.end = r.start - 1
        fixed.append(r)
    if fixed:
        fixed[-1].end = n

    def size(r: Range) -> int:
        return len(render_range(blocks, r.start, r.end))

    merged: list[Range] = []
    for r in fixed:
        if merged and size(r) < MIN_RANGE_CHARS:
            merged[-1].end = r.end
        elif merged and size(merged[-1]) < MIN_RANGE_CHARS:
            merged[-1].end = r.end
            if not merged[-1].title:
                merged[-1].title = r.title
        else:
            merged.append(r)
    return merged


def ranges_to_chunks(ranges: list[Range], blocks: list[Block]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for r in ranges:
        title = (r.title or title_for_range(blocks, r.start, r.end))[:200]
        text = render_range(blocks, r.start, r.end, title=title)
        if not text:
            # A range that was only its heading still belongs to the document.
            text = render_range(blocks, r.start, r.end)
        if not text:
            continue
        chunks.append(Chunk(title=title, text=text, start=r.start, end=r.end))
    return chunks


# ---------------------------------------------------------------------------
# Windowing for very long documents
# ---------------------------------------------------------------------------


def make_windows(blocks: list[Block], max_chars: int) -> list[tuple[int, int]]:
    """Split blocks into windows of <= max_chars (1-based inclusive ranges).

    Cuts land on block boundaries and, where possible, right before a heading in
    the second half of the window.
    """
    total = sum(len(b.text) + 2 for b in blocks)
    if total <= max_chars or len(blocks) <= 1:
        return [(1, len(blocks))]
    windows: list[tuple[int, int]] = []
    start = 1
    size = 0
    last_heading: int | None = None
    i = 1
    while i <= len(blocks):
        b = blocks[i - 1]
        if b.is_heading and i > start:
            last_heading = i
        block_size = len(b.text) + 2
        if size + block_size > max_chars and i > start:
            # prefer cutting at a heading in the second half of the window
            if last_heading is not None and (last_heading - start) >= (i - start) / 2:
                cut = last_heading
            else:
                cut = i
            windows.append((start, cut - 1))
            start = cut
            size = 0
            last_heading = None
            i = cut
            continue
        size += block_size
        i += 1
    windows.append((start, len(blocks)))
    return [w for w in windows if w[1] >= w[0]]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _ask_llm_for_ranges(
    llm: LLMClient, title: str, blocks: list[Block], stats: dict[str, Any]
) -> list[Range]:
    """One LLM call plus at most one corrective re-ask. Raises ChunkValidationError."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt(title, blocks)},
    ]
    last_error: ChunkValidationError | None = None
    for attempt in range(2):
        stats["llm_calls"] = stats.get("llm_calls", 0) + 1
        try:
            answer = await llm.chat(messages, json_mode=True, max_tokens=1500)
        except (
            LLMError
        ) as exc:  # empty/malformed completion → treat like invalid output
            last_error = ChunkValidationError(str(exc))
            answer = ""
        else:
            try:
                return parse_ranges(answer, len(blocks))
            except ChunkValidationError as exc:
                last_error = exc
        if attempt == 0:
            logger.info("chunking: invalid LLM answer (%s), re-asking", last_error)
            messages = [
                *messages,
                {"role": "assistant", "content": answer or "(empty)"},
                {
                    "role": "user",
                    "content": (
                        f"Your previous answer was invalid because: {last_error}. "
                        f"Reply again with valid JSON only, using block numbers between 1 and {len(blocks)}, "
                        "with contiguous non-overlapping sections that cover every block."
                    ),
                },
            ]
    assert last_error is not None
    raise last_error


async def semantic_chunk(
    llm: LLMClient,
    title: str,
    blocks: list[Block],
    *,
    checkpoint: Checkpoint | None = None,
    window_chars: int | None = None,
    min_chars: int | None = None,
) -> ChunkingResult:
    """Chunk ``blocks`` by topic using the LLM, falling back deterministically.

    ``checkpoint`` is awaited before every LLM call so a cancelled job stops early.
    Transient model-server failures (unreachable, 5xx) propagate as
    ``ModelServerError`` so the job is retried instead of silently degraded.
    """
    checkpoint = checkpoint or _noop
    window_chars = window_chars or settings.LLM_WINDOW_CHARS
    min_chars = settings.LLM_MIN_CHARS_FOR_CHUNKING if min_chars is None else min_chars
    stats: dict[str, Any] = {"llm_calls": 0, "windows": 0}
    started = time.perf_counter()

    text_len = sum(len(b.text) for b in blocks)
    if not blocks or text_len < min_chars:
        stats["chunking_ms"] = round((time.perf_counter() - started) * 1000)
        return ChunkingResult([], ChunkingMethod.none_short, stats)

    windows = make_windows(blocks, window_chars)
    stats["windows"] = len(windows)
    chunks: list[Chunk] = []
    try:
        for w_start, w_end in windows:
            await checkpoint()
            sub_blocks = blocks[w_start - 1 : w_end]
            ranges = await _ask_llm_for_ranges(llm, title, sub_blocks, stats)
            ranges = repair_ranges(ranges, sub_blocks)
            for r in ranges:
                r.start += w_start - 1
                r.end += w_start - 1
            chunks.extend(ranges_to_chunks(ranges, blocks))
    except ChunkValidationError as exc:
        logger.warning(
            "chunking: LLM output unusable (%s); using fallback chunker", exc
        )
        fallback, method = fallback_chunk(blocks)
        stats["fallback_reason"] = str(exc)[:300]
        stats["chunking_ms"] = round((time.perf_counter() - started) * 1000)
        return ChunkingResult(fallback, method, stats)
    except LLMError as exc:  # pragma: no cover - defensive, LLMError handled above
        logger.warning("chunking: LLM error (%s); using fallback chunker", exc)
        fallback, method = fallback_chunk(blocks)
        stats["fallback_reason"] = str(exc)[:300]
        return ChunkingResult(fallback, method, stats)
    except ModelServerError:
        raise

    stats["chunking_ms"] = round((time.perf_counter() - started) * 1000)
    if len(windows) > 1:
        method = ChunkingMethod.llm_windowed
    elif len(chunks) <= 1:
        return ChunkingResult([], ChunkingMethod.llm_single_topic, stats)
    else:
        method = ChunkingMethod.llm
    return ChunkingResult(chunks, method, stats)
