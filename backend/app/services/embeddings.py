from __future__ import annotations

import time
from collections import OrderedDict

import httpx

from app.core.config import settings
from app.models import UsageKind
from app.services.model_client import (
    ModelServerError,
    make_http_client,
    post_json_with_cold_start_retry,
)
from app.services.usage import UsageMeter

# A search query is embedded and re-embedded far more often than it changes.
# Small and short-lived on purpose: this is a latency cache, not a store.
QUERY_CACHE_MAX = 512
QUERY_CACHE_TTL_SECONDS = 600.0


class EmbeddingDimensionError(ModelServerError):
    """The server returned vectors of an unexpected size (misconfiguration, not transient)."""


class EmbeddingClient:
    def __init__(
        self,
        base_url: str = str(settings.EMBEDDING_BASE_URL),
        model: str = settings.EMBEDDING_MODEL,
        dim: int = settings.EMBEDDING_DIM,
        batch_size: int = settings.EMBEDDING_BATCH_SIZE,
        max_chars: int = settings.EMBEDDING_MAX_CHARS,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Query text -> (when it was embedded, the vector). An ordered dict so
        # the oldest entry is the one evicted.
        self._query_cache: OrderedDict[tuple[str, str], tuple[float, list[float]]] = (
            OrderedDict()
        )
        self.dim = dim
        self.batch_size = max(1, batch_size)
        self.max_chars = max_chars
        self.api_key = settings.EMBEDDING_API_KEY if api_key is None else api_key
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_http_client(
                settings.EMBEDDING_TIMEOUT_SECONDS, self.api_key
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed_batch(
        self, texts: list[str], *, meter: UsageMeter | None = None
    ) -> list[list[float]]:
        inputs = [(t or " ")[: self.max_chars] for t in texts]
        try:
            data = await post_json_with_cold_start_retry(
                self.client,
                f"{self.base_url}/embeddings",
                {"model": self.model, "input": inputs},
                what="embeddings",
            )
        except Exception:
            if meter is not None:
                meter.failure(UsageKind.embedding, self.model)
            raise
        if meter is not None:
            meter.record(UsageKind.embedding, data, model=self.model)
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        if len(items) != len(inputs):
            raise ModelServerError(
                f"embeddings: expected {len(inputs)} vectors, got {len(items)}"
            )
        vectors: list[list[float]] = []
        for item in items:
            vec = item.get("embedding")
            if not isinstance(vec, list) or len(vec) != self.dim:
                raise EmbeddingDimensionError(
                    f"embeddings: expected {self.dim}-dim vectors, got "
                    f"{len(vec) if isinstance(vec, list) else type(vec).__name__}"
                )
            vectors.append([float(x) for x in vec])
        return vectors

    async def embed(
        self, texts: list[str], *, meter: UsageMeter | None = None
    ) -> list[list[float]]:
        """Embed ``texts`` in batches, preserving order."""
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            out.extend(
                await self.embed_batch(
                    texts[start : start + self.batch_size], meter=meter
                )
            )
        return out

    async def embed_query(
        self, text: str, *, meter: UsageMeter | None = None
    ) -> list[float]:
        """Embed one search query, reusing a recent answer for the same text.

        This is the slowest single step in a search: measured against the hosted
        model it ranged from 0.8 to 4.8 seconds, and it happens before anything
        else can run. The same query text is embedded again constantly - a
        person paging results or toggling a filter, and Ask, which embeds the
        question once to find pages and again to find the sections inside them.

        Safe to cache because it is a pure function of (model, text), and the
        model is pinned per deployment. Bounded and short-lived, so it never
        becomes a place where memory or stale vectors accumulate.
        """
        key = (self.model, text)
        now = time.monotonic()
        hit = self._query_cache.get(key)
        if hit is not None:
            stored_at, vector = hit
            if now - stored_at < QUERY_CACHE_TTL_SECONDS:
                # Refresh its position so the useful entries survive eviction.
                self._query_cache.move_to_end(key)
                return vector
            del self._query_cache[key]

        vector = (await self.embed([text], meter=meter))[0]
        self._query_cache[key] = (now, vector)
        while len(self._query_cache) > QUERY_CACHE_MAX:
            self._query_cache.popitem(last=False)
        return vector
