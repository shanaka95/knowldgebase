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
from app.services.language import detect
from app.services.llm import LLMClient

SYSTEM_PROMPT = """You answer questions using only the knowledge-base excerpts you are given.

Rules:
- Use only the excerpts. Never add facts, numbers, names or dates from your own knowledge.
- If the excerpts do not answer the question, say so plainly and name what is missing. Do not guess.
- Cite the excerpt each claim comes from with a bracketed number at the end of the sentence, like [2]. Use [1][3] when several support it.
- The excerpts are renumbered every turn. Cite the numbers below, never one from an earlier answer.
- If excerpts disagree, say so and cite both.
- Lead with the answer, then the supporting detail. No preamble, no "based on the excerpts".
- Do not describe your sources in prose ("this comes from excerpt 2"). The bracketed number is the citation; nothing else is needed.
- Use short paragraphs, or a bulleted list when the answer has several parts.
- Answer in the language of the question."""

# Appended when the question's language was actually recognised. The rule above
# leaves it to the model, and a model reading twelve pages of German will drift
# into German however the question was phrased; naming the language outright is
# what stops that.
LANGUAGE_RULE = (
    "\n- IMPORTANT: you should answer in {language}, whatever language the "
    "excerpts are written in."
)

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
    # Which corpus this came from. Defaulted, so nothing that builds a Passage
    # today has to change, and the citation builder can tell the two apart.
    entity_type: str = "document"


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


@dataclass(slots=True)
class Turn:
    """One earlier exchange, carried into a follow-up."""

    question: str
    answer: str


def trim_history(history: Sequence[Turn]) -> list[Turn]:
    """Keep the last few turns, each shortened to its gist.

    The excerpts of earlier turns are deliberately not carried: they were
    retrieved for a different question, they would double the prompt, and the
    current turn re-retrieves whatever is actually needed. What the model needs
    from its own past is the thread of the conversation, which survives the
    truncation.
    """
    kept = list(history)[-settings.ASK_HISTORY_TURNS :]
    return [
        Turn(
            question=_clip(t.question, settings.ASK_HISTORY_QUESTION_CHARS),
            answer=_clip(t.answer, settings.ASK_HISTORY_ANSWER_CHARS),
        )
        for t in kept
        if t.question.strip() or t.answer.strip()
    ]


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


# Openers that only mean something next to the question before them. Bare
# question words are deliberately absent: "Which supplier issued the credit
# note?" stands on its own, and only its *short* forms ("Which one?") need the
# previous question - which the length test below already catches.
_FOLLOWUP_OPENERS = (
    "and ",
    "but ",
    "what about",
    "how about",
    "it ",
    "its ",
    "that ",
    "this ",
    "they ",
    "them ",
    "those ",
    "these ",
    "the second",
    "the first",
    "the last",
    "same ",
    "also",
    "instead",
    "again",
)


def is_followup(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    if len(q) <= settings.ASK_FOLLOWUP_CHARS:
        return True
    return q.startswith(_FOLLOWUP_OPENERS)


def retrieval_query(question: str, history: Sequence[Turn]) -> str:
    """What to search for, given that the question may lean on the last one.

    "And in euros?" retrieves nothing on its own. The textbook fix is to ask a
    model to rewrite it into a standalone question first, which costs a whole
    extra round trip on every follow-up - seconds of latency and a second
    generation - before the search has even started.

    Concatenating the previous question instead costs nothing and does the same
    work for hybrid search: BM25 picks up the terms that were dropped
    ("invoice", "March"), and the dense vector lands between the two questions,
    which is where the answer usually is. Only the search sees this; the model
    is given the real history.
    """
    q = (question or "").strip()
    if not history or not is_followup(q):
        return q
    previous = history[-1].question.strip()
    if not previous:
        return q
    return f"{previous}\n{q}"


def answer_language(question: str, history: Sequence[Turn] = ()) -> str | None:
    """The language to answer in, or None when the question does not say.

    A follow-up is usually too short to identify on its own - "and in euros?"
    is as good a match for Dutch as for English - so the thread's earlier
    questions are read with it. It is the same person writing in the same
    language, and together they are long enough to be sure.

    None means the detector was not confident, and the prompt then falls back
    to its standing "answer in the language of the question" rule rather than
    naming the wrong one.
    """
    asked = [t.question for t in list(history)[-settings.ASK_HISTORY_TURNS :]]
    asked.append(question)
    detected = detect("\n".join(q.strip() for q in asked if q and q.strip()))
    return detected.name if detected else None


def conversation_title(question: str) -> str:
    """Name a thread from its first question - no model call, no cost."""
    text = " ".join((question or "").split())
    if not text:
        return "New thread"
    if len(text) <= 60:
        return text
    return text[:60].rsplit(" ", 1)[0].rstrip(",;:.-") + "…"


def build_messages(
    question: str,
    context: AnswerContext,
    history: Sequence[Turn] = (),
    language: str | None = None,
) -> list[dict[str, str]]:
    """Rules and excerpts first, then the thread, then the question.

    The order is chosen for the prefill cache rather than for reading: every
    serving stack (vLLM, vMLX, the hosted providers) caches on a *prefix*, so
    the part that does not change between turns has to come first. On a thread
    pinned to one page the excerpts are byte-for-byte identical every turn, and
    that page can be a hundred thousand characters - putting it at the front
    turns the second question's prefill into a cache hit instead of a re-read.
    """
    system = SYSTEM_PROMPT
    if language:
        system += LANGUAGE_RULE.format(language=language)
    if context.prompt:
        system = f"{system}\n\nExcerpts:\n{context.prompt}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in trim_history(history):
        if turn.question:
            messages.append({"role": "user", "content": turn.question})
        if turn.answer:
            messages.append({"role": "assistant", "content": turn.answer})
    messages.append({"role": "user", "content": f"Question: {question.strip()}"})
    return messages


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
    history: Sequence[Turn] = (),
    language: str | None = None,
) -> str:
    if not context:
        return NO_CONTEXT_ANSWER
    return await llm.chat(
        build_messages(question, context, history, language),
        max_tokens=max_tokens or settings.ASK_MAX_TOKENS,
        temperature=settings.ASK_TEMPERATURE,
    )


async def stream_answer(
    llm: LLMClient,
    question: str,
    context: AnswerContext,
    *,
    max_tokens: int | None = None,
    history: Sequence[Turn] = (),
    language: str | None = None,
) -> AsyncIterator[str]:
    if not context:
        yield NO_CONTEXT_ANSWER
        return
    async for piece in llm.stream_chat(
        build_messages(question, context, history, language),
        max_tokens=max_tokens or settings.ASK_MAX_TOKENS,
        temperature=settings.ASK_TEMPERATURE,
    ):
        yield piece
