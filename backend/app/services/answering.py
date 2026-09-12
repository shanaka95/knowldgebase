"""Turn retrieved pages into a grounded answer.

The Ask feature is retrieval-augmented generation: run the full hybrid search,
take the best pages, and let the model write the answer from those excerpts
only. The model never sees the knowledge base - just the passages handed to it -
so every claim can be traced back to a page, and a question the base cannot
answer gets "I don't know" instead of an invention.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.llm import LLMClient

SYSTEM_PROMPT = """You answer questions using only the knowledge-base excerpts you are given.

Rules:
- Use only the excerpts. Never add facts, numbers, names or dates from your own knowledge.
- If the excerpts do not answer the question, say so plainly and name what is missing. Do not guess.
- Cite the excerpt each claim comes from with a bracketed number at the end of the sentence, like [2]. Use [1][3] when several support it.
- If excerpts disagree, say so and cite both.
- Lead with the answer, then the supporting detail. No preamble, no "based on the excerpts".
- Do not describe your sources in prose ("this comes from excerpt 2"). The bracketed number is the citation; nothing else is needed.
- Use short paragraphs, or a bulleted list when the answer has several parts.
- Answer in the language of the question."""

NO_CONTEXT_ANSWER = (
    "I could not find anything in the knowledge base about that. "
    "Try different wording, or check that the pages you expect have finished indexing."
)


@dataclass(slots=True)
class Passage:
    """One excerpt handed to the model, and the page it came from."""

    index: int  # 1-based; this is the number the model cites
    document_id: uuid.UUID
    title: str
    namespace_name: str
    text: str
    chunk_index: int | None = None
    chunk_title: str | None = None
    score: float = 0.0


@dataclass(slots=True)
class AnswerContext:
    passages: list[Passage] = field(default_factory=list)
    prompt: str = ""
    truncated: bool = False  # a passage was cut, or a page did not fit at all

    def __bool__(self) -> bool:
        return bool(self.passages)


def _tidy(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (text or "").strip())


def build_context(
    candidates: Sequence[Passage],
    *,
    total_budget: int | None = None,
    per_passage_budget: int | None = None,
) -> AnswerContext:
    """Fit the best passages into the model's context window.

    Pages arrive in relevance order, so the budget is spent from the top down: a
    highly-ranked page is never dropped to make room for a weaker one. Each
    passage is capped as well, so one long page cannot crowd out the rest.
    """
    total_budget = total_budget or settings.ASK_CONTEXT_CHARS
    per_passage_budget = per_passage_budget or settings.ASK_PASSAGE_CHARS

    used = 0
    truncated = False
    kept: list[Passage] = []

    for candidate in candidates:
        text = _tidy(candidate.text)
        if not text:
            continue
        if len(text) > per_passage_budget:
            text = text[:per_passage_budget].rsplit(" ", 1)[0] + " …"
            truncated = True
        remaining = total_budget - used
        if remaining <= 200:  # too little left to be worth a partial excerpt
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining].rsplit(" ", 1)[0] + " …"
            truncated = True
        kept.append(
            Passage(
                index=len(kept) + 1,
                document_id=candidate.document_id,
                title=candidate.title,
                namespace_name=candidate.namespace_name,
                text=text,
                chunk_index=candidate.chunk_index,
                chunk_title=candidate.chunk_title,
                score=candidate.score,
            )
        )
        used += len(text)

    return AnswerContext(passages=kept, prompt=render_prompt(kept), truncated=truncated)


def render_prompt(passages: Sequence[Passage]) -> str:
    blocks = []
    for p in passages:
        where = f"{p.title} — {p.namespace_name}"
        if p.chunk_title:
            where += f" — section “{p.chunk_title}”"
        blocks.append(f"[{p.index}] {where}\n{p.text}")
    return "\n\n".join(blocks)


def build_messages(question: str, context: AnswerContext) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {question.strip()}\n\nExcerpts:\n{context.prompt}",
        },
    ]


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def cited_indexes(answer: str, count: int) -> list[int]:
    """Which excerpts the answer actually cites, in order of first appearance."""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(answer or ""):
        n = int(match.group(1))
        if 1 <= n <= count and n not in seen:
            seen.append(n)
    return seen


async def answer(
    llm: LLMClient,
    question: str,
    context: AnswerContext,
    *,
    max_tokens: int | None = None,
) -> str:
    if not context:
        return NO_CONTEXT_ANSWER
    return await llm.chat(
        build_messages(question, context),
        max_tokens=max_tokens or settings.ASK_MAX_TOKENS,
        temperature=settings.ASK_TEMPERATURE,
    )


async def stream_answer(
    llm: LLMClient,
    question: str,
    context: AnswerContext,
    *,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    if not context:
        yield NO_CONTEXT_ANSWER
        return
    async for piece in llm.stream_chat(
        build_messages(question, context),
        max_tokens=max_tokens or settings.ASK_MAX_TOKENS,
        temperature=settings.ASK_TEMPERATURE,
    ):
        yield piece
