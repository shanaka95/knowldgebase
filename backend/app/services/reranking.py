"""Cross-encoder reranking of retrieved pages.

Fusion (see ``retrieval.py``) is good at deciding which pages are *worth a
look*: it merges several rankings that each see the query from one angle. It is
poor at deciding which of those pages actually answers the question, because no
source ever reads the query and the page together.

A reranker does exactly that. It scores every (query, page) pair with a single
model, which is why it catches "the espresso machine is descaled with citric
acid" as an answer to "what do I use to clean the coffee maker" when neither
keyword overlap nor a single whole-document embedding does.

Two facts shape the design:

* **Billing is per call, not per document.** A rerank request costs the same
  whether it carries three candidates or a hundred, so there is one call per
  query and it carries the whole candidate pool.
* **The model has its own context window** (32k tokens for Cohere rerank 4), and
  everything sent has to fit inside it. Candidates are therefore trimmed to
  ``RERANK_DOC_CHARS`` each, under a total budget, keeping the part of each page
  most likely to decide relevance.

A reranker is an improvement, not a dependency: if it is not configured, or the
call fails, retrieval keeps its fused order and the caller is told it did not
run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.services.model_client import (
    ModelServerError,
    make_http_client,
    post_json_with_cold_start_retry,
)

logger = logging.getLogger(__name__)


class RerankError(ModelServerError):
    pass


@dataclass(slots=True)
class RerankedDocument:
    """One candidate, with the score the reranker gave it."""

    index: int  # position in the list that was submitted
    score: float


class Reranker(Protocol):
    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedDocument]: ...


class RerankClient:
    """An OpenAI-style ``/rerank`` endpoint (OpenRouter, Cohere, Jina, Voyage)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or str(settings.RERANK_BASE_URL or "")).rstrip("/")
        self.model = model or settings.RERANK_MODEL
        self.api_key = settings.RERANK_API_KEY if api_key is None else api_key
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_http_client(
                settings.RERANK_TIMEOUT_SECONDS, self.api_key
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedDocument]:
        if not documents:
            return []
        body: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            body["top_n"] = top_n
        data = await post_json_with_cold_start_retry(
            self.client, f"{self.base_url}/rerank", body, what="rerank"
        )
        try:
            results = data["results"]
        except (KeyError, TypeError) as exc:
            raise RerankError(f"rerank: malformed response: {str(data)[:300]}") from exc

        out: list[RerankedDocument] = []
        for item in results:
            try:
                out.append(
                    RerankedDocument(
                        index=int(item["index"]),
                        score=float(item["relevance_score"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RerankError(
                    f"rerank: malformed result entry: {str(item)[:200]}"
                ) from exc
        # Providers are supposed to return these sorted; do not depend on it.
        out.sort(key=lambda r: r.score, reverse=True)
        return out


def build_candidate_text(
    title: str,
    *,
    passage: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    max_chars: int | None = None,
) -> str:
    """The text that stands in for a page while it is being scored.

    The title leads, because it is often the clearest statement of what a page
    is about. Then the page itself: a reranker asked "does this page answer the
    question" should see the page, not the paragraph that happened to embed
    nearest. A contract whose answer sits two sections away from the matched
    chunk scores badly on the chunk and correctly on the whole.

    The summary and a matched passage remain as fallbacks for a page with no
    stored text - a scan still being parsed, say - in that order of specificity.
    """
    limit = max_chars or settings.RERANK_DOC_CHARS
    parts = [title.strip()]
    for candidate in (body, summary, passage):
        text = (candidate or "").strip()
        if text:
            parts.append(text)
            break
    joined = "\n\n".join(p for p in parts if p)
    if len(joined) <= limit:
        return joined
    # Trim at a word boundary so the model is not handed a severed token.
    cut = joined.rfind(" ", 0, limit)
    return joined[: cut if cut > limit // 2 else limit]


def fit_to_budget(documents: list[str], *, total_chars: int | None = None) -> list[str]:
    """Shrink candidates evenly until they fit the reranker's context window.

    Dropping candidates would silently hide pages from the ranking, so every
    candidate keeps a share of the budget instead.
    """
    budget = total_chars or settings.RERANK_TOTAL_CHARS
    if not documents or sum(len(d) for d in documents) <= budget:
        return documents
    share = max(budget // len(documents), 200)
    return [d if len(d) <= share else d[:share] for d in documents]


def keep_count(
    scores: list[float],
    *,
    default: int | None = None,
    maximum: int | None = None,
    ratio: float | None = None,
    min_score: float | None = None,
) -> int:
    """How many reranked pages to put in front of the answering model.

    Three by default: past the top few, added pages dilute the prompt more than
    they inform it. The exception is a query the reranker answers with a cluster
    of near-equal scores - several pages that genuinely say the same thing, or
    one answer split across pages - where cutting at three would drop half of
    it. Such a page joins only if it scores close to the third one *and* is
    convincing on its own; a run of equally irrelevant pages stays out.
    """
    keep = default or settings.RERANK_KEEP_DEFAULT
    cap = maximum or settings.RERANK_KEEP_MAX
    close = settings.RERANK_KEEP_RATIO if ratio is None else ratio
    floor = settings.RERANK_KEEP_MIN_SCORE if min_score is None else min_score

    if len(scores) <= keep:
        return len(scores)
    anchor = scores[keep - 1]
    if anchor <= 0:
        return keep
    n = keep
    while n < min(cap, len(scores)):
        score = scores[n]
        if score >= floor and score >= anchor * close:
            n += 1
            continue
        break
    return n
