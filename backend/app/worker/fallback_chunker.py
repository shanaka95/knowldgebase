"""Deterministic chunking used when the LLM output is unusable.

Strategy
--------
1. If the document has at least two headings at its top-most heading level,
   split at those headings (``fallback_headings``). Text before the first
   heading becomes an "Introduction" chunk.
2. Otherwise group consecutive blocks into ~1500–2500 character chunks without
   splitting a block (``fallback_paragraphs``). A document that fits in a
   single group yields zero chunks (it is one topic by construction).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.content import Block
from app.models import ChunkingMethod

TARGET_CHARS = 2000
MIN_CHARS = 1500
MAX_CHARS = 2500


@dataclass(slots=True)
class Chunk:
    """A contiguous range of blocks (1-based, inclusive) with its rendered text."""

    title: str
    text: str
    start: int
    end: int

    @property
    def char_count(self) -> int:
        return len(self.text)


def _same_heading(text: str, title: str) -> bool:
    return " ".join(text.lower().split()) == " ".join(title.lower().split())


def render_range(blocks: list[Block], start: int, end: int, *, title: str = "") -> str:
    """Join a range of blocks into the chunk body.

    A section almost always opens with the heading that became its title. That
    heading is stored separately and prepended when the chunk is embedded, so
    keeping it in the body too would repeat it - in the excerpt shown to readers,
    and in the text that gets embedded.
    """
    selected = list(blocks[start - 1 : end])
    # The heading is not always the very first block: a chunk that starts at the
    # top of a page opens with the page title, then the section heading. Only the
    # leading run of headings is considered, so a heading further down - which
    # introduces different content - is left alone.
    if title:
        for i, block in enumerate(selected):
            if not block.is_heading:
                break
            if _same_heading(block.text, title):
                selected = selected[:i] + selected[i + 1 :]
                break
    return "\n\n".join(b.text for b in selected if b.text).strip()


def title_for_range(
    blocks: list[Block], start: int, end: int, fallback: str = ""
) -> str:
    for b in blocks[start - 1 : end]:
        if b.is_heading and b.text:
            return b.text[:200]
    if fallback:
        return fallback[:200]
    first = next((b.text for b in blocks[start - 1 : end] if b.text), "")
    return (first[:60].rstrip() + ("…" if len(first) > 60 else "")) or "Section"


def chunk_by_headings(blocks: list[Block]) -> list[Chunk] | None:
    levels = [b.level for b in blocks if b.is_heading and b.level is not None]
    if not levels:
        return None
    top = min(levels)
    cut_points = [
        i + 1 for i, b in enumerate(blocks) if b.is_heading and b.level == top
    ]
    if len(cut_points) < 2:
        return None
    chunks: list[Chunk] = []
    if cut_points[0] > 1:
        text = render_range(blocks, 1, cut_points[0] - 1)
        if text:
            chunks.append(Chunk("Introduction", text, 1, cut_points[0] - 1))
    for idx, start in enumerate(cut_points):
        end = cut_points[idx + 1] - 1 if idx + 1 < len(cut_points) else len(blocks)
        text = render_range(blocks, start, end)
        if text:
            chunks.append(Chunk(title_for_range(blocks, start, end), text, start, end))
    return chunks if len(chunks) >= 2 else None


def chunk_by_paragraphs(blocks: list[Block]) -> list[Chunk]:
    chunks: list[Chunk] = []
    start = 1
    size = 0
    for i, b in enumerate(blocks, start=1):
        size += len(b.text) + 2
        at_end = i == len(blocks)
        if size >= TARGET_CHARS or at_end:
            # avoid a tiny trailing chunk: extend the previous one instead
            if at_end and chunks and size < MIN_CHARS // 2:
                prev = chunks[-1]
                chunks[-1] = Chunk(
                    prev.title, render_range(blocks, prev.start, i), prev.start, i
                )
            else:
                text = render_range(blocks, start, i)
                if text:
                    chunks.append(
                        Chunk(title_for_range(blocks, start, i), text, start, i)
                    )
            start = i + 1
            size = 0
    return chunks


def fallback_chunk(blocks: list[Block]) -> tuple[list[Chunk], ChunkingMethod]:
    by_headings = chunk_by_headings(blocks)
    if by_headings is not None:
        return by_headings, ChunkingMethod.fallback_headings
    by_paragraphs = chunk_by_paragraphs(blocks)
    if len(by_paragraphs) <= 1:
        return [], ChunkingMethod.fallback_paragraphs
    return by_paragraphs, ChunkingMethod.fallback_paragraphs
