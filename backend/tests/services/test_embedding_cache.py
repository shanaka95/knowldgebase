"""Embedding a search query is the slowest step in a search, so it happens once.

Measured against the hosted model, one query embedding took between 0.8 and 4.8
seconds, and everything else in a search waits on it. The same text gets
embedded again constantly - paging results, toggling a filter, and Ask, which
needs the question twice.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.embeddings import (
    QUERY_CACHE_MAX,
    EmbeddingClient,
)

pytestmark = pytest.mark.anyio

URL = f"{str(settings.EMBEDDING_BASE_URL).rstrip('/')}/embeddings"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def response(n: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [{"embedding": [0.1] * settings.EMBEDDING_DIM} for _ in range(n)]
        },
    )


async def test_the_same_query_is_embedded_once() -> None:
    with respx.mock:
        route = respx.post(URL).mock(return_value=response())
        client = EmbeddingClient()
        first = await client.embed_query("notice period")
        second = await client.embed_query("notice period")
        await client.close()
    assert first == second
    assert route.call_count == 1, "the second search reused the first answer"


async def test_a_different_query_is_embedded_again() -> None:
    with respx.mock:
        route = respx.post(URL).mock(return_value=response())
        client = EmbeddingClient()
        await client.embed_query("notice period")
        await client.embed_query("annual leave")
        await client.close()
    assert route.call_count == 2


async def test_the_cache_cannot_grow_without_limit() -> None:
    """A latency cache, not a store. Unbounded, it would be a way to use memory."""
    with respx.mock:
        respx.post(URL).mock(return_value=response())
        client = EmbeddingClient()
        for i in range(QUERY_CACHE_MAX + 40):
            await client.embed_query(f"query {i}")
        size = len(client._query_cache)
        await client.close()
    assert size <= QUERY_CACHE_MAX


async def test_a_stale_entry_is_not_served() -> None:
    import app.services.embeddings as module

    with respx.mock:
        route = respx.post(URL).mock(return_value=response())
        client = EmbeddingClient()
        await client.embed_query("notice period")

        # Age the entry past its time to live rather than waiting ten minutes.
        key = (client.model, "notice period")
        stored_at, vector = client._query_cache[key]
        client._query_cache[key] = (
            stored_at - module.QUERY_CACHE_TTL_SECONDS - 1,
            vector,
        )

        await client.embed_query("notice period")
        await client.close()
    assert route.call_count == 2


async def test_document_embedding_is_not_cached() -> None:
    """Documents are embedded once by the worker; caching them would only cost memory."""
    with respx.mock:
        route = respx.post(URL).mock(return_value=response())
        client = EmbeddingClient()
        await client.embed(["the same page text"])
        await client.embed(["the same page text"])
        await client.close()
    assert route.call_count == 2
