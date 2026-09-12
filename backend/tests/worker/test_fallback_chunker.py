from __future__ import annotations

from app.core.content import Block
from app.models import ChunkingMethod
from app.worker.fallback_chunker import chunk_by_paragraphs, fallback_chunk


def para(n: int, size: int = 200) -> list[Block]:
    return [Block("paragraph", f"Paragraph {i} " + "x" * size) for i in range(n)]


def test_headings_split_with_introduction() -> None:
    blocks = [
        Block("paragraph", "Preamble text before any heading."),
        Block("heading", "Alpha", level=1),
        Block("paragraph", "alpha body"),
        Block("heading", "Beta", level=1),
        Block("paragraph", "beta body"),
        Block("heading", "Sub", level=2),
        Block("paragraph", "sub body"),
    ]
    chunks, method = fallback_chunk(blocks)
    assert method == ChunkingMethod.fallback_headings
    assert [c.title for c in chunks] == ["Introduction", "Alpha", "Beta"]
    assert chunks[2].text == "Beta\n\nbeta body\n\nSub\n\nsub body"


def test_single_heading_falls_through_to_paragraphs() -> None:
    blocks = [Block("heading", "Only", level=1), *para(2)]
    chunks, method = fallback_chunk(blocks)
    assert method == ChunkingMethod.fallback_paragraphs
    assert chunks == []  # fits in one group → single topic


def test_paragraph_groups_respect_target_size_and_no_tiny_tail() -> None:
    blocks = para(30, size=300)
    chunks = chunk_by_paragraphs(blocks)
    assert len(chunks) > 1
    assert chunks[0].start == 1 and chunks[-1].end == 30
    for prev, cur in zip(chunks, chunks[1:], strict=False):
        assert cur.start == prev.end + 1
    assert all(len(c.text) >= 700 for c in chunks)
    chunks2, method = fallback_chunk(blocks)
    assert method == ChunkingMethod.fallback_paragraphs and len(chunks2) == len(chunks)


def test_a_chunk_body_does_not_repeat_its_own_heading() -> None:
    """The heading is stored as the title and prepended when embedding, so
    keeping it in the body too would show and embed it twice."""
    from app.worker.fallback_chunker import render_range

    section = [
        Block("heading", "Kitchen etiquette", 2),
        Block("paragraph", "Label your food."),
    ]
    assert render_range(section, 1, 2, title="Kitchen etiquette") == "Label your food."
    # without a title nothing is stripped
    assert render_range(section, 1, 2).startswith("Kitchen etiquette")


def test_the_page_title_above_a_section_heading_is_kept() -> None:
    """A chunk starting at the top of a page opens with the page title; only the
    heading that became this chunk's title is removed."""
    from app.worker.fallback_chunker import render_range

    blocks = [
        Block("heading", "Team notes", 1),
        Block("heading", "Budget review", 2),
        Block("paragraph", "Cloud spend is over plan."),
    ]
    body = render_range(blocks, 1, 3, title="Budget review")
    assert body == "Team notes\n\nCloud spend is over plan."


def test_a_heading_further_down_is_left_alone() -> None:
    """Only the leading run of headings is considered: a heading in the middle
    introduces different content and belongs in the body."""
    from app.worker.fallback_chunker import render_range

    blocks = [
        Block("paragraph", "Intro."),
        Block("heading", "Details", 2),
        Block("paragraph", "More."),
    ]
    assert render_range(blocks, 1, 3, title="Details") == "Intro.\n\nDetails\n\nMore."
