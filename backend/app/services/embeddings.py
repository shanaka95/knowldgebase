from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.model_client import (
    ModelServerError,
    make_http_client,
    post_json_with_cold_start_retry,
)


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

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        inputs = [(t or " ")[: self.max_chars] for t in texts]
        data = await post_json_with_cold_start_retry(
            self.client,
            f"{self.base_url}/embeddings",
            {"model": self.model, "input": inputs},
            what="embeddings",
        )
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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` in batches, preserving order."""
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            out.extend(await self.embed_batch(texts[start : start + self.batch_size]))
        return out
