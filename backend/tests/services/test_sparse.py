"""BM25 sparse encoding: tokenisation rules and the term-frequency component."""

import pytest

from app.services.sparse import encode_document, encode_query, token_id, tokenize


def test_stopwords_and_short_tokens_are_dropped() -> None:
    tokens = tokenize("The quarterly budget is a review of the plan")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "a" not in tokens
    assert "quarterly" in tokens
    assert "budget" in tokens


def test_accents_are_folded() -> None:
    assert tokenize("Präsentation Überblick") == ["prasentation", "uberblick"]


def test_compound_tokens_also_yield_their_parts() -> None:
    tokens = tokenize("cloud-spend report")
    assert "cloud-spend" in tokens
    assert "cloud" in tokens
    assert "spend" in tokens


@pytest.mark.parametrize(
    ("singular", "plural"),
    [
        ("cache", "caches"),
        ("document", "documents"),
        ("policy", "policies"),
        ("box", "boxes"),
        ("watch", "watches"),
        ("class", "classes"),
        ("table", "tables"),
        ("note", "notes"),
    ],
)
def test_singular_and_plural_share_a_stem(singular: str, plural: str) -> None:
    """Query and stored text run through the same stemmer, so they must agree."""
    assert tokenize(singular) == tokenize(plural)


def test_non_plural_s_words_survive() -> None:
    assert tokenize("status analysis business") == ["status", "analysis", "business"]


def test_document_term_frequency_saturates() -> None:
    values = [
        encode_document(" ".join(["alpha"] * n)).values[0] for n in (1, 3, 10, 50)
    ]
    assert values == sorted(values), "more occurrences must never score lower"
    assert values[-1] < 2.5, "BM25 saturation must bound the term frequency component"
    assert values[3] - values[2] < values[1] - values[0], "growth must flatten"


def test_document_vector_is_sorted_and_aligned() -> None:
    vector = encode_document("budget review cloud spend budget")
    assert vector.indices == sorted(vector.indices)
    assert len(vector.indices) == len(vector.values)
    assert len(set(vector.indices)) == len(vector.indices)


def test_query_vector_is_all_ones() -> None:
    """IDF is applied by Qdrant, so the query only carries term presence."""
    vector = encode_query("budget budget review")
    assert set(vector.values) == {1.0}
    assert len(vector.indices) == 2, "repeated query terms collapse"


def test_empty_text_gives_an_empty_vector() -> None:
    assert not encode_document("")
    assert not encode_query("   ")
    assert not encode_query("the and of")


def test_token_id_is_stable_and_positive() -> None:
    first = token_id("budget")
    assert first == token_id("budget")
    assert 0 <= first <= 0x7FFFFFFF
    assert token_id("budget") != token_id("review")


def test_query_and_document_share_indices_for_the_same_word() -> None:
    doc = encode_document("quarterly budget review notes")
    query = encode_query("budgets")
    assert set(query.indices) & set(doc.indices), "plural query must hit singular text"
