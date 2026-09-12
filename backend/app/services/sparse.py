"""BM25 sparse-vector encoding for lexical search in Qdrant.

Qdrant scores sparse vectors as a plain dot product, so BM25 is split in two:

* the **document** vector carries the term-frequency component
  ``tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg_len))`` per token,
* the **query** vector carries ``1.0`` per token,
* the **IDF** factor is applied by Qdrant itself when the sparse vector field is
  declared with ``modifier=Modifier.IDF`` - it knows the true corpus statistics,
  which a single worker process does not.

Multiplying the three gives the standard Okapi BM25 score.

Tokens are mapped to sparse indices with a stable 32-bit hash, so no vocabulary
has to be persisted and re-indexing is deterministic.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.core.config import settings

# Deliberately small: removing very common words helps BM25 precision, while an
# aggressive list would hurt phrase-like queries ("how to" pages).
STOPWORDS: frozenset[str] = frozenset(
    """
    a an and are as at be but by for from has have he her his how i in is it its
    of on or our that the their them there these they this to was were what
    when where which who will with you your
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", re.ASCII)
_MIN_TOKEN_LEN = 2
_MAX_TOKEN_LEN = 40


@dataclass(slots=True, frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]

    def __bool__(self) -> bool:
        return bool(self.indices)


def _fold(text: str) -> str:
    """Lowercase and strip accents so 'Präsentation' matches 'prasentation'."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _stem(token: str) -> str:
    """A deliberately conservative suffix stripper.

    Full Porter stemming would need another dependency for marginal gain. What
    matters here is that a singular and its plural collapse to the *same* term,
    since query and stored text run through this identically - the trailing-``e``
    rule is what makes pairs like cache/caches agree.
    """
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith(("sses", "ches", "shes", "xes", "zes")):
        token = token[:-2]
    elif (
        len(token) > 3
        and token.endswith("s")
        and not token.endswith(("ss", "us", "is"))
    ):
        token = token[:-1]
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


_SEPARATORS = re.compile(r"[._-]")


def tokenize(text: str) -> list[str]:
    """Split text into BM25 terms.

    A compound like ``cloud-spend`` yields the whole token *and* its parts, so
    both "cloud-spend" and "spend" retrieve the document.
    """
    tokens: list[str] = []

    def add(token: str) -> None:
        if _MIN_TOKEN_LEN <= len(token) <= _MAX_TOKEN_LEN and token not in STOPWORDS:
            tokens.append(_stem(token))

    for raw in _TOKEN_RE.findall(_fold(text or "")):
        add(raw)
        if _SEPARATORS.search(raw):
            for part in _SEPARATORS.split(raw):
                add(part)
    return tokens


def token_id(token: str) -> int:
    """Stable, process-independent 31-bit id for a token.

    ``hash()`` is salted per process, so it cannot be used for stored vectors.
    """
    h = 2166136261
    for ch in token.encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h & 0x7FFFFFFF


def encode_document(
    text: str,
    *,
    k1: float | None = None,
    b: float | None = None,
    avg_len: float | None = None,
) -> SparseVector:
    """Sparse vector for stored text: BM25 term-frequency saturation per token."""
    k1 = settings.BM25_K1 if k1 is None else k1
    b = settings.BM25_B if b is None else b
    avg_len = settings.BM25_AVG_DOC_LEN if avg_len is None else avg_len

    tokens = tokenize(text)
    if not tokens:
        return SparseVector([], [])
    counts = Counter(tokens)
    length_norm = 1.0 - b + b * (len(tokens) / avg_len if avg_len > 0 else 1.0)

    by_index: dict[int, float] = {}
    for token, tf in counts.items():
        value = (tf * (k1 + 1.0)) / (tf + k1 * length_norm)
        index = token_id(token)
        # Hash collisions are rare; keeping the larger value is the safe merge.
        by_index[index] = max(by_index.get(index, 0.0), value)

    indices = sorted(by_index)
    return SparseVector(indices, [by_index[i] for i in indices])


def encode_query(text: str) -> SparseVector:
    """Sparse vector for a query: 1.0 per distinct token (IDF comes from Qdrant)."""
    tokens = tokenize(text)
    if not tokens:
        return SparseVector([], [])
    indices = sorted({token_id(t) for t in tokens})
    return SparseVector(indices, [1.0] * len(indices))
