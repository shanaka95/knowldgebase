"""Reranking: what gets sent for scoring, and how many pages survive it."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.model_client import ModelServerError
from app.services.reranking import (
    RerankClient,
    RerankError,
    build_candidate_text,
    fit_to_budget,
    keep_count,
)

pytestmark = pytest.mark.anyio

RERANK_URL = "https://models.test/v1/rerank"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _client() -> RerankClient:
    return RerankClient(
        base_url="https://models.test/v1", model="cohere/rerank-4-fast", api_key="k"
    )


# --- the call itself --------------------------------------------------------


async def test_results_come_back_ordered_by_relevance() -> None:
    with respx.mock:
        respx.post(RERANK_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.11},
                        {"index": 0, "relevance_score": 0.92},
                        {"index": 1, "relevance_score": 0.44},
                    ]
                },
            )
        )
        out = await _client().rerank("q", ["a", "b", "c"])
    assert [r.index for r in out] == [0, 1, 2]
    assert [round(r.score, 2) for r in out] == [0.92, 0.44, 0.11]


async def test_the_query_and_every_candidate_are_sent() -> None:
    with respx.mock:
        route = respx.post(RERANK_URL).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        await _client().rerank("how do I fail over", ["one", "two"], top_n=1)
    body = route.calls[0].request.content.decode()
    assert '"how do I fail over"' in body
    assert '"top_n":1' in body.replace(" ", "")
    assert '"model":"cohere/rerank-4-fast"' in body.replace(" ", "")


async def test_no_candidates_means_no_request() -> None:
    """Paying for a call that can only return nothing would be silly."""
    with respx.mock:
        route = respx.post(RERANK_URL).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        assert await _client().rerank("q", []) == []
        assert route.call_count == 0


async def test_a_malformed_response_is_an_error_not_a_wrong_order() -> None:
    with respx.mock:
        respx.post(RERANK_URL).mock(
            return_value=httpx.Response(200, json={"unexpected": True})
        )
        with pytest.raises(RerankError):
            await _client().rerank("q", ["a"])


async def test_a_result_missing_its_score_is_an_error() -> None:
    with respx.mock:
        respx.post(RERANK_URL).mock(
            return_value=httpx.Response(200, json={"results": [{"index": 0}]})
        )
        with pytest.raises(RerankError):
            await _client().rerank("q", ["a"])


async def test_a_server_error_surfaces_as_a_model_server_error() -> None:
    """The caller catches this and keeps the fused order."""
    with respx.mock:
        respx.post(RERANK_URL).mock(return_value=httpx.Response(500, text="boom"))
        with pytest.raises(ModelServerError):
            await _client().rerank("q", ["a"])


# --- what a candidate looks like to the reranker ----------------------------


def test_the_matching_section_is_preferred_over_the_summary() -> None:
    text = build_candidate_text(
        "Runbook",
        passage="Promote the standby with pg_ctl promote.",
        summary="A summary of the runbook.",
        body="The whole runbook.",
    )
    assert text.startswith("Runbook")
    assert "pg_ctl promote" in text
    assert "A summary" not in text, "one representation of the page, not three"


def test_the_summary_stands_in_when_nothing_matched_a_section() -> None:
    text = build_candidate_text(
        "Runbook", summary="A summary of the runbook.", body="The whole runbook."
    )
    assert "A summary of the runbook." in text
    assert "The whole runbook." not in text


def test_the_page_itself_is_the_last_resort() -> None:
    text = build_candidate_text("Runbook", body="The whole runbook.")
    assert text == "Runbook\n\nThe whole runbook."


def test_a_page_with_no_text_at_all_is_still_its_title() -> None:
    assert build_candidate_text("Untitled draft") == "Untitled draft"


def test_long_candidates_are_trimmed_at_a_word_boundary() -> None:
    text = build_candidate_text("T", body="word " * 5000, max_chars=100)
    assert len(text) <= 100
    assert not text.endswith("wor")


def test_candidates_shrink_together_rather_than_some_being_dropped() -> None:
    """Dropping one would remove a page from the ranking without saying so."""
    docs = ["x" * 9000 for _ in range(10)]
    fitted = fit_to_budget(docs, total_chars=20000)
    assert len(fitted) == 10
    assert sum(len(d) for d in fitted) <= 20000


def test_candidates_that_already_fit_are_left_alone() -> None:
    docs = ["short", "also short"]
    assert fit_to_budget(docs, total_chars=10000) == docs


# --- how many pages reach the answering model -------------------------------


def test_three_pages_by_default() -> None:
    assert keep_count([0.9, 0.8, 0.7, 0.2, 0.1]) == 3


def test_a_fourth_page_joins_when_it_is_nearly_as_convincing() -> None:
    assert keep_count([0.9, 0.88, 0.85, 0.84, 0.05]) == 4


def test_the_cluster_stops_at_five_however_flat_the_scores() -> None:
    assert keep_count([0.9] * 10) == settings.RERANK_KEEP_MAX


def test_a_run_of_equally_irrelevant_pages_stays_out() -> None:
    """These are measured scores from a query nothing in the corpus answered.

    Every neighbour is within 85% of the one above it, so a ratio test alone
    would admit all five. They are all noise.
    """
    assert keep_count([0.198, 0.198, 0.181, 0.149, 0.149]) == 3


def test_a_clearly_weaker_fourth_page_stays_out_even_above_the_floor() -> None:
    """Measured: a relevant but distinctly weaker page, against three strong ones."""
    assert keep_count([0.656, 0.569, 0.439, 0.305, 0.258]) == 3


def test_an_answer_split_across_four_pages_keeps_all_four() -> None:
    """Measured: one procedure written across four pages, then unrelated noise."""
    assert keep_count([0.539, 0.507, 0.424, 0.354, 0.104]) == 4


def test_fewer_candidates_than_the_default_keeps_them_all() -> None:
    assert keep_count([0.9, 0.4]) == 2


def test_no_candidates_keeps_nothing() -> None:
    assert keep_count([]) == 0


def test_a_run_of_zero_scores_does_not_widen_the_cut() -> None:
    assert keep_count([0.9, 0.0, 0.0, 0.0, 0.0]) == 3
