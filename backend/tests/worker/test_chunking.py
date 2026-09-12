from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.content import Block, html_to_blocks
from app.models import ChunkingMethod
from app.services.model_client import ModelServerError
from app.worker import chunking
from app.worker.chunking import (
    ChunkValidationError,
    Range,
    extract_json_object,
    make_windows,
    parse_ranges,
    repair_ranges,
    semantic_chunk,
)


def blocks(*texts: str) -> list[Block]:
    out = []
    for t in texts:
        if t.startswith("# "):
            out.append(Block("heading", t[2:], level=1))
        elif t.startswith("## "):
            out.append(Block("heading", t[3:], level=2))
        else:
            out.append(Block("paragraph", t))
    return out


# --------------------------------------------------------------------- parsing


def test_extract_json_handles_fences_and_think_tags() -> None:
    raw = '<think>hmm</think>```json\n{"chunks": [{"title": "A", "start": 1, "end": 2}]}\n```'
    assert extract_json_object(raw)["chunks"][0]["title"] == "A"


def test_extract_json_finds_embedded_object() -> None:
    raw = 'Sure! Here you go: {"chunks": [{"title": "A", "start": 1, "end": 3}]} hope it helps'
    assert extract_json_object(raw)["chunks"][0]["end"] == 3


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "{}",
        '{"chunks": []}',
        '{"chunks": [{"title": "A"}]}',
        '{"chunks": [{"title": "A", "start": 0, "end": 2}]}',
        '{"chunks": [{"title": "A", "start": 1, "end": 9}]}',
        '{"chunks": [{"title": "A", "start": 3, "end": 1}]}',
        '{"chunks": [{"title": "A", "start": 1, "end": 3}, {"title": "B", "start": 2, "end": 4}]}',
        '{"chunks": [{"start": 1, "end": 1}, {"start": 2, "end": 2}, {"start": 3, "end": 3}, {"start": 4, "end": 4}, {"start": 4, "end": 4}]}',
    ],
)
def test_parse_ranges_rejects_garbage(raw: str) -> None:
    with pytest.raises(ChunkValidationError):
        parse_ranges(raw, n=4)


def test_parse_ranges_accepts_sections_alias_and_sorts() -> None:
    raw = json.dumps(
        {
            "sections": [
                {"title": "B", "start": 3, "end": 4},
                {"title": "A", "start": 1, "end": 2},
            ]
        }
    )
    ranges = parse_ranges(raw, n=4)
    assert [(r.start, r.end) for r in ranges] == [(1, 2), (3, 4)]


# ---------------------------------------------------------------------- repair


def test_repair_fills_gaps_and_extends_to_edges() -> None:
    b = blocks(*[f"paragraph {i} " * 20 for i in range(8)])
    ranges = [Range("A", 2, 3), Range("B", 6, 7)]
    fixed = repair_ranges(ranges, b)
    assert [(r.start, r.end) for r in fixed] == [(1, 5), (6, 8)]


def test_repair_merges_tiny_ranges() -> None:
    b = blocks("x" * 500, "tiny", "y" * 500)
    fixed = repair_ranges([Range("A", 1, 1), Range("t", 2, 2), Range("C", 3, 3)], b)
    assert [(r.start, r.end) for r in fixed] == [(1, 2), (3, 3)]


# ------------------------------------------------------------------- windowing


def test_make_windows_single_when_short() -> None:
    b = blocks("a" * 100, "b" * 100)
    assert make_windows(b, 1000) == [(1, 2)]


def test_make_windows_prefers_heading_cuts_and_covers_everything() -> None:
    b = blocks(
        "# Intro",
        "p" * 300,
        "p" * 300,
        "## Part two",
        "q" * 300,
        "q" * 300,
        "# Three",
        "r" * 300,
        "r" * 300,
    )
    windows = make_windows(b, 800)
    assert windows[0][0] == 1 and windows[-1][1] == len(b)
    for (_s1, e1), (s2, _e2) in zip(windows, windows[1:], strict=False):
        assert s2 == e1 + 1
    # at least one cut lands on a heading
    assert any(b[s - 1].is_heading for s, _ in windows[1:])


def test_make_windows_never_infinite_loops_on_huge_block() -> None:
    b = blocks("z" * 5000, "small", "small")
    assert make_windows(b, 1000)[0] == (1, 1)


# ------------------------------------------------------------- semantic_chunk


class FakeLLM:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict[str, str]]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
    ) -> str:
        self.messages.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return str(reply)


LONG = blocks(
    "# Onboarding",
    *[
        ("New joiners get a laptop, an account and a buddy. " * 6).strip()
        for _ in range(4)
    ],
    "# Expenses",
    *[
        (
            "Expenses are submitted monthly through the portal with receipts attached. "
            * 5
        ).strip()
        for _ in range(4)
    ],
)


@pytest.mark.anyio
async def test_single_topic_yields_no_chunks() -> None:
    llm = FakeLLM(
        [json.dumps({"chunks": [{"title": "All", "start": 1, "end": len(LONG)}]})]
    )
    result = await semantic_chunk(llm, "Doc", LONG, window_chars=100_000)  # type: ignore[arg-type]
    assert result.chunks == []
    assert result.method == ChunkingMethod.llm_single_topic
    assert result.stats["llm_calls"] == 1


@pytest.mark.anyio
async def test_multi_topic_yields_chunks_with_verbatim_text() -> None:
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "chunks": [
                        {"title": "Onboarding", "start": 1, "end": 5},
                        {"title": "Expenses", "start": 6, "end": len(LONG)},
                    ]
                }
            )
        ]
    )
    result = await semantic_chunk(llm, "Doc", LONG, window_chars=100_000)  # type: ignore[arg-type]
    assert result.method == ChunkingMethod.llm
    assert [c.title for c in result.chunks] == ["Onboarding", "Expenses"]
    # A section's own heading lives in the title, not repeated in the body - it
    # is prepended again when the chunk is embedded. The bodies therefore open
    # with their first paragraph.
    assert result.chunks[0].text.startswith("New joiners get a laptop")
    assert result.chunks[1].text.startswith("Expenses are submitted monthly")

    # The anti-hallucination guarantee: title + body reproduces the document
    # exactly, because the model only ever chose boundaries, never wrote text.
    rebuilt = "\n\n".join(f"{c.title}\n\n{c.text}" for c in result.chunks)
    assert rebuilt == "\n\n".join(b.text for b in LONG)


@pytest.mark.anyio
async def test_invalid_then_valid_uses_corrective_reask() -> None:
    llm = FakeLLM(
        [
            "garbage",
            json.dumps(
                {
                    "chunks": [
                        {"title": "A", "start": 1, "end": 5},
                        {"title": "B", "start": 6, "end": len(LONG)},
                    ]
                }
            ),
        ]
    )
    result = await semantic_chunk(llm, "Doc", LONG, window_chars=100_000)  # type: ignore[arg-type]
    assert result.method == ChunkingMethod.llm
    assert len(llm.messages) == 2
    assert "invalid because" in llm.messages[1][-1]["content"]


@pytest.mark.anyio
async def test_garbage_twice_falls_back_to_headings() -> None:
    llm = FakeLLM(["nope", "still nope"])
    result = await semantic_chunk(llm, "Doc", LONG, window_chars=100_000)  # type: ignore[arg-type]
    assert result.method == ChunkingMethod.fallback_headings
    assert [c.title for c in result.chunks] == ["Onboarding", "Expenses"]
    assert "fallback_reason" in result.stats


@pytest.mark.anyio
async def test_short_text_skips_llm() -> None:
    llm = FakeLLM([])
    result = await semantic_chunk(llm, "Doc", blocks("short text"), min_chars=600)  # type: ignore[arg-type]
    assert result.method == ChunkingMethod.none_short
    assert llm.messages == []


@pytest.mark.anyio
async def test_windowed_documents_offset_ranges() -> None:
    big = blocks(*[f"Paragraph number {i}. " * 15 for i in range(20)])
    windows = make_windows(big, 1200)
    assert len(windows) > 1
    replies = []
    for s, e in windows:
        n = e - s + 1
        replies.append(
            json.dumps({"chunks": [{"title": f"W{s}", "start": 1, "end": n}]})
        )
    llm = FakeLLM(replies)
    result = await semantic_chunk(llm, "Doc", big, window_chars=1200)  # type: ignore[arg-type]
    assert result.method == ChunkingMethod.llm_windowed
    assert [(c.start, c.end) for c in result.chunks] == windows
    assert result.stats["windows"] == len(windows)


@pytest.mark.anyio
async def test_server_errors_propagate_for_retry() -> None:
    llm = FakeLLM([ModelServerError("llm: model server unreachable")])
    with pytest.raises(ModelServerError):
        await semantic_chunk(llm, "Doc", LONG, window_chars=100_000)  # type: ignore[arg-type]


def test_html_blocks_roundtrip_into_prompt() -> None:
    b = html_to_blocks("<h2>Title</h2><p>Body</p>")
    prompt = chunking.user_prompt("Doc", b)
    assert "[1] (H2) Title" in prompt and "[2] Body" in prompt
