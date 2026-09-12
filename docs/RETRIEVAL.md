# Hybrid retrieval (BM25 + vectors + RRF)

Search runs two independent kinds of matching and fuses them. Both can be turned
on or off per query from the search page or the API.

| method | what it is good at | what it misses |
|---|---|---|
| **BM25** (lexical) | exact words, names, error codes, acronyms, IDs | synonyms, paraphrases |
| **Vector** (semantic) | meaning: "cut cloud costs" finds "reduce AWS spend" | rare literal tokens, exact identifiers |

Running both and fusing the rankings is what makes a query like
*"error 407 vpn token"* work: BM25 nails `407`, the vector side understands
*vpn token*.

## Sources

Each enabled method is applied to each of the three embedding kinds, and keyword
search adds one more source that does not use the vector store at all - giving up
to **seven independent sources**:

```
bm25:document    bm25:summary    bm25:chunk      fulltext:page
vector:document  vector:summary  vector:chunk
```

* `document` - the whole page (title + full text). Broad topical match.
* `summary` - the LLM-written summary. Dense and noise-free, so it matches the
  *gist* of a page even when the wording differs.
* `chunk` - individual semantic sections. Finds the one paragraph that answers
  the question inside a long page, and gives the snippet shown in the results.

* `fulltext:page` - Postgres full-text ranking over the live page row. Qdrant
  only knows pages the worker has already indexed, so without this a page
  written a minute ago would be unfindable; this source sees it the instant it
  is saved. It runs whenever **BM25** is enabled, and is reported separately so
  you can see when a hit came only from it.

A query can restrict the targets (for example chunks only) with the `targets`
parameter. That applies to the vector-store sources; the full-text source always
searches whole pages.

## Fusion: Reciprocal Rank Fusion

Scores from different methods are not comparable - cosine similarity sits in
[-1, 1], BM25 is unbounded and depends on corpus statistics. So RRF throws the
scores away and fuses **ranks**:

```
score(document) = Σ over sources  1 / (k + rank_in_that_source)      k = 60
```

Consequences worth knowing:

* A page found by several sources beats a page that one source loves. Agreement
  is the signal.
* `k` damps the head of each list: with `k = 60`, rank 1 contributes 1/61 and
  rank 2 contributes 1/62, so a narrow win in one source cannot dominate.
  Lower `k` makes top ranks more decisive; higher `k` flattens the curve.
* When several chunks of the same page match in one source, only its **best**
  rank counts - long pages do not win by having more chunks.

Every result carries the sources that produced it, with their rank and raw
score, so the UI can explain *why* a page matched.

## How BM25 works here

There is no separate search engine: the sparse vectors live in the same Qdrant
collection as the dense ones.

* Each point stores a `bm25` sparse vector alongside its `dense` vector.
* Stored text carries the BM25 term-frequency component
  `tf·(k1+1) / (tf + k1·(1-b + b·len/avg_len))` per token (`k1=1.2`, `b=0.75`).
* A query carries `1.0` per token.
* The collection declares the sparse field with `Modifier.IDF`, so **Qdrant**
  multiplies in the inverse document frequency from the real corpus statistics.

Dot product of the three parts is exactly Okapi BM25.

Tokenisation (`app/services/sparse.py`) lowercases, strips accents, drops a small
stopword list, splits compounds (`cloud-spend` also matches `spend`), and applies
a conservative stemmer whose only hard requirement is that a singular and its
plural collapse to the same term. Token ids are a stable FNV hash, so no
vocabulary is persisted and re-indexing is deterministic.

## API

```bash
GET /api/v1/search/retrieve?q=vpn+token+error&bm25=true&vector=true&limit=20
```

| parameter | default | meaning |
|---|---|---|
| `q` | required | the query |
| `bm25` | `true` | enable lexical search |
| `vector` | `true` | enable semantic search |
| `targets` | `document,summary,chunk` | which embedding kinds to search |
| `namespace_id` | all accessible | restrict to one space |
| `limit` | 20 | number of fused results |
| `rerank` | `true` | rerank the leading results (see below) |
| `rrf_k` | 60 | fusion constant |
| `candidates_per_source` | 50 | depth fetched from each source before fusion |

The response carries `used_bm25`, `used_vector` and `used_rerank`, which report
what actually ran rather than what was asked for.

## Reranking

Fusion decides which pages belong in the running. It cannot decide which of them
actually answers the query, because no source ever reads the query and the page
together: BM25 counts word overlap, and a vector search compares two summaries of
meaning that were computed separately.

A cross-encoder does read them together. After fusion, the top
`RERANK_CANDIDATES` (10) pages are sent to the reranker in one call, and the
order it returns is the order the reader sees. Anything past the pool keeps its
fused position behind the rescored block.

Each candidate is represented by its title followed by the most specific text
available: the section that matched, else the summary, else the start of the
page. One representation, not three, because the budget is better spent on more
pages than on the same page said three ways. Candidates are trimmed to
`RERANK_DOC_CHARS` (4000) and, if the batch is still too big for the reranker's
own context window, shrunk evenly rather than dropped, so no page silently
disappears from the ranking.

Reranking is an improvement, not a dependency. If `RERANK_MODEL` is empty, or the
call fails, the fused order stands and `used_rerank` comes back `false`.

### Cost

Rerank providers bill per request, not per document. Measured against
`cohere/rerank-4-fast` through OpenRouter, a call carrying 100 documents of
12,000 characters each costs exactly what a call carrying 3 short ones costs:
one search unit, $0.002. So the design is one call per query carrying the whole
candidate pool. Trimming candidates buys latency and context headroom, not money.

| configuration | default | meaning |
|---|---|---|
| `RERANK_MODEL` | empty (off) | model id, e.g. `cohere/rerank-4-fast` |
| `RERANK_BASE_URL` | empty | an OpenAI-style `/rerank` endpoint |
| `RERANK_API_KEY` | empty | falls back to the chat model's key in the deploy compose |
| `RERANK_CANDIDATES` | 10 | pages sent for scoring |
| `RERANK_MIN_CANDIDATES` | 3 | below this there is nothing worth reordering |
| `RERANK_DOC_CHARS` | 4000 | per-candidate trim |
| `RERANK_TOTAL_CHARS` | 100000 | whole-batch ceiling |

### A note on the semantic floor

Dense retrieval always returns *something*: cosine similarity has no natural
"no match" point, so without a floor every query returns every page. Measured on
this corpus, genuinely relevant queries reach down to ~0.25 while unrelated text
sits near ~0.13 - overlapping enough that an aggressive cutoff would discard good
results. `VECTOR_MIN_SCORE` (default **0.15**) is therefore deliberately low: it
removes obvious noise and nothing else. Set it to `0` to keep every semantic
match, or raise it if your corpus tolerates it. BM25 needs no such floor - a term
either occurs or it does not.

At least one method must be enabled (`422` otherwise). Results are always
filtered to what the caller may read, both in the Qdrant filter and again when
the rows are loaded from Postgres.

Response shape:

```json
{
  "data": [{
    "document_id": "…", "title": "Connecting to the office VPN",
    "namespace_slug": "office", "score": 0.0489,
    "snippet": "…Error <mark>407</mark> means your <mark>token</mark> expired…",
    "matched_chunk_index": 2,
    "sources": [
      {"method": "bm25",   "target": "chunk",    "rank": 1, "score": 8.9,  "contribution": 0.0164},
      {"method": "vector", "target": "summary",  "rank": 2, "score": 0.81, "contribution": 0.0161}
    ]
  }],
  "sources": [{"method": "bm25", "target": "chunk", "hits": 12, "took_ms": 4.1}],
  "used_bm25": true, "used_vector": true, "rrf_k": 60, "took_ms": 91.2
}
```

A failing source (say the embedding server is down) is reported in `sources`
with an `error` and contributes nothing - the rest of the search still returns.

To have a model answer from these results instead of reading them yourself, see
[ASK.md](ASK.md) - it runs exactly this retrieval and writes an answer with
citations.

`GET /api/v1/search/` remains available on its own: a plain Postgres full-text
search that needs no vector store and no model server. It is the same ranking
that `fulltext:page` contributes to the fusion, and it is what the ⌘K palette
uses for instant results.

## Re-indexing

The sparse vectors were added after the first release, so a collection created
earlier has the wrong schema. The app detects this on startup and recreates the
collection, which empties it. To refill:

```bash
curl -X POST -H "Authorization: Bearer $JWT" \
  http://localhost:8800/api/v1/documents/embeddings/reindex-all
```

This queues every page for re-embedding (superuser only). Progress is visible per
page in the AI index panel and in aggregate on the dashboard.
