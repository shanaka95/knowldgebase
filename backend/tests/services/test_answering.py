"""Context building and citation parsing for grounded answers."""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.services.answering import (
    NO_CONTEXT_ANSWER,
    Passage,
    Turn,
    build_context,
    build_messages,
    cited_indexes,
    conversation_title,
    render_prompt,
    retrieval_query,
    trim_history,
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
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "only the knowledge-base excerpts" in messages[0]["content"]
    assert "some content" in messages[0]["content"]
    assert messages[-1]["content"] == "Question: Why is the sky blue?"


def test_the_excerpts_lead_so_a_pinned_page_is_a_stable_prefix() -> None:
    """Two turns on the same page must share everything before the history.

    That shared opening is what a serving stack's prefix cache keys on, and it
    is the difference between re-reading a whole page and not.
    """
    context = build_context([_passage("the page, unchanged between turns")])
    first = build_messages("What is this?", context)
    second = build_messages(
        "And the second part?", context, [Turn("What is this?", "An answer.")]
    )
    assert first[0] == second[0], "the system message must not move between turns"
    assert second[0]["content"].index("Excerpts:") < len(second[0]["content"])


def test_history_becomes_alternating_turns_before_the_question() -> None:
    context = build_context([_passage("content")])
    messages = build_messages(
        "And in euros?",
        context,
        [Turn("What did March cost?", "It cost $100. [1]")],
    )
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "What did March cost?"
    assert messages[2]["content"] == "It cost $100. [1]"
    assert messages[3]["content"] == "Question: And in euros?"


# -------------------------------------------------------------------- history


def test_only_the_last_few_turns_travel() -> None:
    history = [Turn(f"q{i}", f"a{i}") for i in range(10)]
    kept = trim_history(history)
    assert len(kept) == settings.ASK_HISTORY_TURNS
    assert kept[-1].question == "q9", "the most recent turn must survive"


def test_an_earlier_answer_is_carried_as_a_gist() -> None:
    kept = trim_history([Turn("q", "word " * 5000)])
    assert len(kept[0].answer) <= settings.ASK_HISTORY_ANSWER_CHARS + 2
    assert kept[0].answer.endswith("…")


def test_empty_turns_are_dropped() -> None:
    assert trim_history([Turn("  ", "  ")]) == []


# ------------------------------------------------------------ retrieval query


def test_a_first_question_is_searched_for_as_asked() -> None:
    assert retrieval_query("What did March cost?", []) == "What did March cost?"


def test_a_follow_up_borrows_the_question_before_it() -> None:
    """ "And in euros?" finds nothing alone; with its predecessor it finds the page."""
    query = retrieval_query("And in euros?", [Turn("What did March cost?", "$100")])
    assert "What did March cost?" in query
    assert "And in euros?" in query


def test_a_self_contained_follow_up_is_searched_for_on_its_own() -> None:
    question = (
        "Which supplier issued the credit note that the finance team disputed "
        "in the second quarter, and what was the stated reason for it?"
    )
    assert retrieval_query(question, [Turn("earlier", "answer")]) == question


# ---------------------------------------------------------------------- title


def test_a_thread_is_named_after_its_first_question() -> None:
    assert conversation_title("  How do I   get set up? ") == "How do I get set up?"


def test_a_long_first_question_is_cut_at_a_word() -> None:
    title = conversation_title("word " * 40)
    assert len(title) <= 61
    assert title.endswith("…")


def test_an_empty_question_still_names_the_thread() -> None:
    assert conversation_title("   ") == "New thread"


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
