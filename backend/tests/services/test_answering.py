"""Context building and citation parsing for grounded answers."""

from __future__ import annotations

import uuid

from app.services.answering import (
    NO_CONTEXT_ANSWER,
    Passage,
    build_context,
    build_messages,
    cited_indexes,
    render_prompt,
)


def _passage(text: str, *, title: str = "A page", index: int = 1) -> Passage:
    return Passage(
        index=index,
        document_id=uuid.uuid4(),
        title=title,
        namespace_name="Office",
        text=text,
    )


# ------------------------------------------------------------------ budgeting


def test_passages_are_numbered_from_one_in_relevance_order() -> None:
    context = build_context(
        [_passage("first", title="Most relevant"), _passage("second", title="Next")]
    )
    assert [p.index for p in context.passages] == [1, 2]
    assert context.passages[0].title == "Most relevant"
    assert not context.truncated


def test_a_long_passage_is_capped_so_it_cannot_crowd_out_the_others() -> None:
    context = build_context(
        [_passage("word " * 4000), _passage("the second page still fits")],
        per_passage_budget=300,
        total_budget=5000,
    )
    assert context.truncated
    assert len(context.passages) == 2, "the shorter page must survive"
    assert len(context.passages[0].text) <= 320
    assert context.passages[0].text.endswith("…")


def test_the_budget_is_spent_from_the_top_down() -> None:
    """A highly-ranked page is never dropped to make room for a weaker one."""
    context = build_context(
        [_passage("a" * 900, title="Top"), _passage("b" * 900, title="Weaker")],
        per_passage_budget=1000,
        total_budget=1000,
    )
    assert [p.title for p in context.passages] == ["Top"]
    assert context.truncated


def test_empty_passages_are_skipped() -> None:
    context = build_context([_passage("   "), _passage("real content")])
    assert len(context.passages) == 1
    assert context.passages[0].text == "real content"


def test_no_passages_is_falsy() -> None:
    context = build_context([])
    assert not context
    assert context.passages == []


# --------------------------------------------------------------------- prompt


def test_prompt_labels_each_excerpt_with_its_number_and_origin() -> None:
    context = build_context(
        [
            Passage(
                index=1,
                document_id=uuid.uuid4(),
                title="Connecting to the VPN",
                namespace_name="Office",
                text="Error 407 means your token expired.",
                chunk_title="Troubleshooting",
            )
        ]
    )
    prompt = render_prompt(context.passages)
    assert prompt.startswith("[1] Connecting to the VPN — Office")
    assert "Troubleshooting" in prompt
    assert "Error 407" in prompt


def test_messages_carry_the_rules_and_the_question() -> None:
    context = build_context([_passage("some content")])
    messages = build_messages("  Why is the sky blue?  ", context)
    assert messages[0]["role"] == "system"
    assert "only the knowledge-base excerpts" in messages[0]["content"]
    assert messages[1]["content"].startswith("Question: Why is the sky blue?")
    assert "some content" in messages[1]["content"]


# ------------------------------------------------------------------ citations


def test_citations_are_found_in_order_of_first_use() -> None:
    assert cited_indexes("First [3] then [1] and [3] again.", 5) == [3, 1]


def test_citations_outside_the_excerpt_range_are_ignored() -> None:
    """A model that invents [9] must not produce a dangling citation."""
    assert cited_indexes("Claim [9] and claim [2].", 3) == [2]
    assert cited_indexes("Claim [0].", 3) == []


def test_no_citations_in_plain_text() -> None:
    assert cited_indexes("No sources here at all.", 4) == []
    assert cited_indexes("", 4) == []


def test_the_no_context_answer_refuses_rather_than_guessing() -> None:
    assert "could not find" in NO_CONTEXT_ANSWER.lower()
