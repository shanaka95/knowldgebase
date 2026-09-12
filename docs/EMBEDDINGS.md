# Embeddings pipeline

Every document is indexed by a background worker into **Qdrant**. This page documents what is
stored, how the pipeline runs, and how it reacts to edits, failures and restarts.

This is the write side. How those vectors are searched is in [RETRIEVAL.md](RETRIEVAL.md).

## What gets embedded

Each document version produces three *kinds* of vectors (all 1024-dim, cosine distance, model
`jinaai/jina-embeddings-v5-text-small-retrieval-mlx` served by vMLX):

| kind | count per document | text that is embedded | why |
|---|---|---|---|
| `document` | 1 | `"{title}\n\n{plain text}"` (truncated to `EMBEDDING_MAX_CHARS`, default 24 000) | coarse "is this document relevant" match |
| `summary` | 1 | LLM-generated summary (3–6 sentences, ≤ 150 words) | dense, noise-free representation of the whole document; also stored on `document.summary` |
| `chunk` | 0…n | `"{chunk title}\n\n{chunk text}"` for every semantic chunk | fine-grained passages for retrieval |

The plain text is derived server-side from the sanitised HTML (`app/core/content.py`), so the
API, the search index and the embedding worker always see the same text.

### Semantic chunking (no fixed size)

Chunks are decided by the LLM (`lmstudio-community/Qwen3.5-9B-MLX-4bit`), not by a token
window:

1. The document is split into numbered *blocks* (`[1]…[n]`: headings, paragraphs, list items,
   code blocks, table rows).
2. The LLM is asked to group **consecutive** blocks into the fewest sections such that every
   section covers a single topic, and to return **only boundaries**:
   `{"chunks":[{"title":"…","start":1,"end":4}, …]}`.
   Because the model returns block ranges rather than text, chunk text is copied verbatim from
   the document and can never be hallucinated.
3. The answer is validated (ranges in order, contiguous, in range, full coverage, no overlap);
   small gaps are repaired, tiny ranges (< 120 chars) merged into a neighbour. An invalid answer
   triggers one corrective re-ask; if that fails too, a deterministic fallback is used.
4. Interpretation of the result:
   * **one** range → the document is a single topic → **no chunks** (`llm_single_topic`),
   * two or more ranges → one `chunk` per range (`llm`).
5. Documents longer than `LLM_WINDOW_CHARS` (default 20 000 chars) are windowed on block
   boundaries (preferring cuts before headings) and each window is chunked separately
   (`llm_windowed`).
6. Documents shorter than `LLM_MIN_CHARS_FOR_CHUNKING` (600 chars) are never chunked
   (`none_short`).

Fallback chunkers: split at the top-level headings (`fallback_headings`), otherwise group
paragraphs into ~1 500–2 500 char sections (`fallback_paragraphs`).

The method that produced the chunks is recorded on the document (`chunking_method`) and on the
job, so chunk quality can be audited.

Chunks are also stored in Postgres (`documentchunk`: `document_id`, `doc_version`,
`chunk_index`, `title`, `text`, `char_count`) so the UI can display them.

## Qdrant layout

Every point carries **two** vectors, so one collection answers both halves of
hybrid search (see [RETRIEVAL.md](RETRIEVAL.md)):

* `dense` - the 1024-dim embedding, cosine distance.
* `bm25` - a sparse BM25 vector, declared with `Modifier.IDF` so Qdrant applies
  inverse document frequency from the real corpus statistics.

Details:

* Collection: `QDRANT_COLLECTION` (default `kb_documents`), dense `size=1024`,
  `distance=Cosine`.
* Payload indexes: `document_id` (keyword), `namespace_id` (keyword), `kind` (keyword),
  `doc_version` (integer).
* A collection created before hybrid search has a single unnamed vector and no sparse field.
  There is no in-place migration: the app detects the old schema at startup, recreates the
  collection and the pages must be re-indexed (`POST /documents/embeddings/reindex-all`).
* **Point id** = `uuid5(KB_NAMESPACE, "{document_id}:{doc_version}:{kind}:{index}")`
  (`index = 0` for `document` and `summary`, the chunk index for chunks). Ids are deterministic
  so re-running a job is idempotent.
* **Payload**

  ```json
  {
    "document_id": "8c4b…",
    "namespace_id": "1f2e…",
    "kind": "document | summary | chunk",
    "doc_version": 7,
    "title": "document title, or chunk title for chunks",
    "chunk_index": 2,
    "char_count": 1834
  }
  ```

Write order: the new version's points are upserted first, then every point of that document
with `doc_version < new version` is deleted, then the Postgres transaction that marks the
document `ready` is committed. A crash between those steps leaves at most some extra points of an
older version, which the next successful run removes.

## Lifecycle

### Document-level state (`document.embedding_status`)

| status | meaning |
|---|---|
| `pending` | a job is queued (or retrying); nothing is running yet |
| `chunking` | the worker is asking the LLM for topic boundaries |
| `summarizing` | the worker is generating the summary |
| `embedding` | vectors are being computed and written |
| `ready` | vectors for `embedding_version` are in Qdrant |
| `failed` | all attempts failed; `embedding_error` holds the last error |

Additional fields: `embedding_version` (the document `version` the vectors belong to),
`embedding_error`, `embedding_attempts`, `chunk_count`, `chunking_method`,
`embedding_updated_at`. A document is **stale** when `embedding_version != version` — the UI
shows this as "Stale" even while the status is `ready`.

### Job-level state (`embeddingjob.status`)

| status | meaning |
|---|---|
| `queued` | waiting for `run_after` (debounce or retry backoff) |
| `running` | claimed by a worker (`locked_by`, `heartbeat_at`) |
| `succeeded` | vectors written, document marked `ready` |
| `failed` | gave up after `max_attempts` |
| `cancelled` | stopped mid-flight because the document changed (or was deleted) |
| `superseded` | never ran; replaced by a newer job before being claimed |

Stages while running: `claimed → loading → chunking → summarizing → embedding → writing → done`.

### Triggering

* **Create** → `version = 1`, job queued.
* **Update** → the version is bumped and a job queued **only if the title or the plain text
  changed**; formatting-only edits are saved without re-indexing.
* **Debounce / coalescing** — a new job starts `EMBEDDING_DEBOUNCE_SECONDS` (10 s) after the last
  change. If a job is still `queued` when another edit arrives, it is retargeted at the newest
  version and its start pushed out again, so an autosave storm yields a single job.
* **Cancellation** — if a job is already `running` when the document changes, it is flagged
  `cancel_requested`. The worker checks that flag every second and cancels the asyncio task,
  which aborts the in-flight HTTP call to the LLM or embedding server. The job ends `cancelled`
  and the new job runs from scratch. The document's status is not touched by the cancelled job.
* **Version gate** — right before writing results, the worker re-reads the document row with
  `SELECT … FOR UPDATE`; if `version` moved, the job ends `superseded` and nothing is written.
* **Regenerate** (`POST /api/v1/documents/{id}/embeddings/regenerate`) — cancels any active job
  and queues a new one immediately (no debounce), resetting the attempt counter. Used by the
  "Generate", "Retry" and "Regenerate" buttons.
* **Delete** (document, folder or namespace) — a `cleanuptask` is recorded and the worker removes
  every Qdrant point of the document.

### Failures and retries

* Transient errors (model server unreachable, HTTP 5xx, timeouts) → the job returns to `queued`
  with backoff `EMBEDDING_RETRY_BACKOFF_SECONDS × 2^(attempt-1)` (30 s, 60 s), up to
  `EMBEDDING_MAX_ATTEMPTS` (3). The document stays `pending` and `embedding_error` shows
  `attempt n/m: …`.
* Permanent errors (embedding dimension mismatch = misconfigured model) fail immediately.
* **Reasoning models that will not stop thinking.** Hidden reasoning is charged to the
  same token budget as the answer, so a model that reasons when asked not to can spend
  the entire budget and return a completion with *no content at all*
  (`finish_reason=length`). This is not a transient error and retrying unchanged cannot
  fix it, which is how a 38,000-character document once failed three times over.

  Two defences. First, thinking is switched off in both dialects at once, because no
  provider understands both: local servers (vMLX, vLLM, LM Studio) read
  `chat_template_kwargs.enable_thinking`, while OpenRouter silently drops unknown fields
  and reads `reasoning.enabled`. Whichever is ignored costs nothing. Second, a completion
  that comes back empty *because it ran out of length* is retried once with a much larger
  budget (up to `LLM_MAX_OUTPUT_TOKENS`), so a provider that ignores both switches costs a
  few cents rather than a document. An empty completion for any other reason is reported,
  not retried.
* vMLX starts models on demand: clients retry "connection refused" / 502 / 503 for up to
  `MODEL_SERVER_COLD_START_SECONDS` (150 s) before treating it as a failure. Read timeouts are
  never retried so a multi-minute LLM call is not doubled.
* Worker crash: every running job carries a lease (`heartbeat_at`, `WORKER_LEASE_SECONDS`
  = 60). Another worker reclaims expired leases (attempt counter +1). On graceful shutdown
  (SIGTERM) in-flight jobs are released back to `queued` without counting an attempt.

## Observability

* `GET /api/v1/documents/{id}/embeddings` — status, staleness, summary, current job with stage
  and progress, the last 10 jobs (with errors and per-stage timings in `stats`), and the chunks
  of the indexed version.
* `GET /api/v1/documents/embeddings/summary` — counts by state for the dashboard.
* `GET /api/v1/workers` — worker heartbeats and queue depth.
* `GET /api/v1/health` — reachability of Postgres, Qdrant, MinIO, the embedding server, the LLM
  and whether a worker is online.
* Qdrant UI: <http://localhost:6333/dashboard>.

## Sizing the budgets to your models

`EMBEDDING_MAX_CHARS` and `LLM_WINDOW_CHARS` are properties of the models you deployed,
not of this app, and both are in **characters** because that is what providers actually
enforce. Real documents here measure 3.75 (dense German) to 4.1 (English prose)
characters per token, so divide a model's token window by ~3.75 for a safe character cap.

* A document longer than `EMBEDDING_MAX_CHARS` is truncated before embedding, so anything
  past the cut is invisible to whole-document search. Set it as high as the model allows.
* A document longer than `LLM_WINDOW_CHARS` is summarised window by window and the
  summaries are then summarised. That works, but a single pass is better, so with a
  large-context model set this above the size of your longest page.

The deployed instance uses `qwen3-embedding-8b` (32k tokens → 120,000 characters, under
the provider's own 131,072-character hard limit) and `qwen3.8-flash` (1M tokens, capped at
200,000 characters here — enough for every page in one pass without paying to push a whole
book through).

## Configuration

All settings live in `.env` (host defaults) and are overridden per container in `compose.yml`:

Model endpoints live in `models.toml`; the rest are environment variables.

| variable | default | purpose |
|---|---|---|
| `[embeddings]` in models.toml | vMLX gateway / Jina v5 small / 1024 | embedding server, model, dimensions |
| `EMBEDDING_BATCH_SIZE` / `EMBEDDING_MAX_CHARS` | 16 / 24000 | batching and truncation |
| `[embeddings].max_chars` | 24000 | set it to the deployed model's own context window |
| `[llm]` in models.toml | vMLX gateway / Qwen3.5-9B | chunking + summary model |
| `[llm].disable_thinking` | true | sends both `chat_template_kwargs.enable_thinking=false` and `reasoning.enabled=false` |
| `LLM_WINDOW_CHARS` / `LLM_MIN_CHARS_FOR_CHUNKING` | 20000 / 600 | windowing thresholds |
| `LLM_MAX_OUTPUT_TOKENS` | 8192 | ceiling for the retry after an empty completion |
| `LLM_TIMEOUT_SECONDS` | 300 | read timeout per LLM call |
| `EMBEDDING_DEBOUNCE_SECONDS` | 10 | autosave coalescing |
| `EMBEDDING_MAX_ATTEMPTS` / `EMBEDDING_RETRY_BACKOFF_SECONDS` | 3 / 30 | retries |
| `WORKER_CONCURRENCY` / `WORKER_POLL_INTERVAL_SECONDS` | 2 / 1 | worker parallelism |
| `WORKER_LEASE_SECONDS` / `WORKER_HEARTBEAT_SECONDS` / `WORKER_OFFLINE_AFTER_SECONDS` | 60 / 5 / 30 | liveness |
