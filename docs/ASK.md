# Ask: answers written from your pages

Ask is Search with a model on the end. It runs the **full hybrid retrieval** -
every method against every target, fused with RRF - takes the best pages, and
asks the LLM to write an answer from those excerpts and nothing else.

There are no search toggles on the Ask tab on purpose: a question is not the
place to make someone choose between BM25 and vectors.

Two things change that shape:

* **A pinned page.** When the reader says which page the question is about -
  from the **Ask** button on the page itself, or the page picker in the
  composer - nothing is searched for. See [One page](#one-page).
* **A thread.** Questions and answers are kept, and a follow-up carries the
  last few exchanges. See [Threads](#threads).

## How an answer is produced

```
question ─► hybrid search (BM25 + vectors, RRF) ─► top 10 pages
                                                      │
                                 rerank ─► the 3 (up to 5) that answer it
                                                      │
                            section-level pass: best sections of those pages
                                                      │
                                          budgeted excerpts [1]…[n]
                                                      ▼
                                             LLM ─► answer + citations
```

1. **Retrieve.** The same `retrieve()` the search page uses, with both methods
   and all three targets plus the full-text source, so pages written moments ago
   are eligible too. See [RETRIEVAL.md](RETRIEVAL.md).
2. **Narrow to what answers it.** Ten pages is the right net to cast, and the
   wrong number to read. A cross-encoder scores each of them against the
   question and the best three go forward. See
   [RETRIEVAL.md](RETRIEVAL.md#reranking).

   Three, not ten, because the pages ranked fourth and below are usually near
   misses, and a near miss in the prompt is worse than nothing: it gives the
   model something plausible to cite instead of admitting the answer is not
   there. Three is also not a hard cap. When several pages score nearly as
   highly as the third - a procedure written across four pages, say - up to five
   go through. The widening rule is deliberately strict, because irrelevant
   pages also score close to each other, so nearness alone proves nothing. A
   page joins only if it also clears an absolute score of `0.25`, which is where
   measured relevant and irrelevant pages separate cleanly.

   Without a reranker configured there is no confidence signal to cut on, so all
   `ASK_DOCUMENTS_WITHOUT_RERANK` (10) pages go forward and the context budget
   does the trimming. The answer reports `reranked` either way.

3. **Pick the passages.** Document ranking answers *which pages* are about the
   question; it does not say **where** in a long page the answer sits. So the
   chosen pages get a second, section-level pass: their chunks are ranked against
   the question with the same BM25 + vector fusion, and each page contributes up
   to `ASK_CHUNKS_PER_DOC` (4) of its best sections. A page with no matching
   section contributes its summary, falling back to the page text.

   This matters more than it sounds. An invoice matches on its summary, while the
   amount lives three sections further down - sending only the best-matching
   section would answer "the excerpts do not contain the amount" about a page
   that plainly does.
4. **Budget the context.** Excerpts are added in relevance order until
   `ASK_CONTEXT_CHARS` (300 000) is used, each capped at `ASK_PASSAGE_CHARS`
   (120 000) - sized for whole pages, so a contract or manual arrives intact.
   Spending top-down means a highly-ranked page is never dropped to make
   room for a weaker one, and one long page cannot crowd out the rest. When
   anything was cut, the response says `truncated: true`.
5. **Answer.** The excerpts are numbered `[1]…[n]` and the model is told to use
   only them, to cite the number its claims come from, and to say so plainly when
   the answer is not there.
6. **Report.** Every excerpt comes back with the answer, each marked `cited` or
   not, so the reader can check any claim - and see what was considered but not
   used.

**Access control**: retrieval is already scoped to what the caller may read, and
the pages are re-checked against the database before becoming context. A user
never gets an answer built from a page they cannot open.

**Nothing found**: if retrieval returns nothing the model is never called. The
reply is a plain refusal rather than a guess, which also means no tokens are
spent on questions the knowledge base cannot answer.

## One page

`document_id` on the request pins the answer to a single page. Retrieval is
skipped entirely: the page is loaded by id, permission-checked with the same
rule the page view uses, and read whole.

```
question + document_id ─► the page, whole ─► LLM ─► answer + one citation
```

This is the cheapest and fastest path in the feature, and it is not an
optimisation of the search path but the absence of it - no query embedding, no
vector search, no fusion, no reranker call. On a thread pinned to one page the
excerpts are byte-for-byte identical from turn to turn, so the prompt's whole
opening is a cache prefix the serving stack can reuse: the second question on a
page does not pay to read it again.

It is also the honest answer to "what does *this* say?". Search answers "which
pages are about this?", which is a different question, and it can rank the page
in front of you second.

## Threads

A question starts a thread, and the answer lands in it. The thread is private to
the person who asked - there is no sharing model for threads - and is listed
newest-first in the rail beside the Ask page.

**What a follow-up carries.** The last `ASK_HISTORY_TURNS` (3) exchanges, each
shortened to its gist: the question capped at 500 characters, the answer at 700.
The **excerpts of earlier turns are never resent**. They were retrieved for a
different question, they would double the prompt every turn, and the current
turn re-retrieves whatever it actually needs. What the model needs from its own
past is the thread of the conversation, and that survives the truncation. The
excerpts are renumbered every turn, and the prompt says so.

**What a follow-up searches for.** "And in euros?" retrieves nothing on its own.
The textbook fix is a first LLM call that rewrites it into a standalone
question, which costs a whole extra round trip before the search has started.
Instead, a question that looks like a follow-up - short, or opening with `and`,
`what about`, `that`, `they`… - is searched for with the previous question
prepended. BM25 picks up the terms that were dropped ("invoice", "March") and
the dense vector lands between the two questions, which is where the answer
usually is. Only the search sees this; the model is given the real history.

**What is stored.** Both sides of every turn, plus the citations of each answer
with a `ASK_STORED_CITATION_CHARS` (600) preview rather than the page itself. A
citation's full text is the live page and is not worth a copy: it would be stale
the moment somebody edits the page, and a thread of ten answers would carry
megabytes of duplicated content. The title links to the page for the rest.

**What is not.** Nothing derived by a model. A thread is named from its first
question - trimmed at a word boundary - because a generation call to write six
words is a generation call.

**Bounded.** Past `ASK_MAX_CONVERSATIONS_PER_USER` (500) threads, the oldest are
dropped. A partial answer is kept: closing the tab mid-answer stores what had
arrived, so the thread is never a question with nothing under it.

```
GET    /api/v1/ask/conversations?limit=&offset=   titles and counts, newest first
GET    /api/v1/ask/conversations/{id}             one thread with its messages
PATCH  /api/v1/ask/conversations/{id}             rename
DELETE /api/v1/ask/conversations/{id}             delete it and its messages
```

The list is titles and counts only - the messages of a thread are fetched when
one is opened, so the rail stays a few kilobytes however long the history is.

## API

### One-shot

```bash
curl -s -X POST http://localhost:8800/api/v1/ask/ \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"q": "What should I do if the VPN shows error 407?"}' | jq
```

```json
{
  "question": "What should I do if the VPN shows error 407?",
  "answer": "Request a new hardware token from the IT portal [2].",
  "citations": [
    {
      "index": 2, "document_id": "…", "title": "Connecting to the office VPN",
      "namespace_slug": "office", "chunk_title": "Troubleshooting",
      "text": "Error 407 means your token expired…", "cited": true, "score": 0.066
    }
  ],
  "searched": 4, "used": 4, "passages": 7, "truncated": false,
  "model": "lmstudio-community/Qwen3.5-9B-MLX-4bit",
  "retrieval_ms": 288.0, "took_ms": 10673.0
}
```

| field | meaning |
|---|---|
| `q` | the question (required) |
| `namespace_id` | restrict to one space |
| `document_id` | answer from this page alone; no search, no reranking |
| `conversation_id` | continue a thread. `/ask/` only continues one; `/ask/stream` starts one when this is absent |
| `top_k` | how many pages are shortlisted before reranking (default `ASK_TOP_K` = 10, max 25) |
| `searched` / `used` | pages the search found / distinct pages that contributed an excerpt |
| `reranked` | whether a cross-encoder chose the pages that were read |
| `passages` | excerpts sent to the model; one page can contribute several |
| `truncated` | an excerpt was shortened, or a page did not fit at all |
| `cited` (per citation) | the answer actually referenced this excerpt |

### Streaming

A local model takes 5-15 seconds to write an answer, so the web app uses the
streaming endpoint and shows the sources while the answer is still being written.

```bash
curl -N -X POST http://localhost:8800/api/v1/ask/stream \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"q": "Why did cloud costs go up?"}'
```

Server-sent events, in order:

| event | payload | when |
|---|---|---|
| `conversation` | `{id, title, document_id}` | first, before anything else: the thread this turn landed in |
| `sources` | `{citations, searched, used, passages, pinned, truncated, retrieval_ms, model}` | ~100 ms in, before any answer text |
| `delta` | `{text}` | many; append in order |
| `error` | `{message}` | the model failed; whatever text arrived is still valid |
| `done` | `{cited: [2], took_ms}` | always last; marks which excerpts the answer used |

Measured on this machine: sources at 0.1 s, first answer token at 0.5 s,
complete at ~5 s.

## Configuration

| setting | default | purpose |
|---|---|---|
| `ASK_TOP_K` | 10 | pages retrieved before reranking |
| `ASK_DOCUMENTS_WITHOUT_RERANK` | 10 | pages used when no reranker is configured |
| `ASK_CHUNKS_PER_DOC` | 4 | best sections taken from each page |
| `ASK_MAX_PASSAGES` | 16 | hard cap on excerpts |
| `ASK_CONTEXT_CHARS` | 300000 | total excerpt budget |
| `ASK_PASSAGE_CHARS` | 120000 | cap per excerpt |
| `ASK_MAX_TOKENS` | 900 | answer length ceiling |
| `ASK_TEMPERATURE` | 0.2 | low: this is extraction, not creative writing |
| `ASK_HISTORY_TURNS` | 3 | earlier exchanges carried into a follow-up |
| `ASK_HISTORY_ANSWER_CHARS` | 700 | how much of an earlier answer travels |
| `ASK_HISTORY_QUESTION_CHARS` | 500 | how much of an earlier question travels |
| `ASK_FOLLOWUP_CHARS` | 80 | a question shorter than this is searched for with its predecessor |
| `ASK_STORED_CITATION_CHARS` | 600 | preview kept with a stored citation |
| `ASK_MAX_CONVERSATIONS_PER_USER` | 500 | threads kept before the oldest are dropped |

The model itself comes from `[llm]` in `models.toml`, so Ask uses whatever chat
model the rest of the app uses - swap in a larger or hosted one there if you want
better answers.

## Limits worth knowing

* **Answer quality follows retrieval.** If the right page is not in the top 10,
  the model cannot use it - though within those pages the section-level pass
  gives it a second chance to find the right part. The Search tab, with its per-method toggles, is the
  tool for finding out *why* something did or did not rank.
* **A follow-up re-searches.** History steers the search and the wording; it is
  not a cache. Each turn retrieves again, which is what keeps the citations
  honest when the follow-up has moved on to another page.
* **Threads are private.** They are not shared, exported or searchable, and
  they are not fed back into retrieval.
* **The model is small.** A 9B model on a laptop is good at extracting and
  summarising what it is shown, and weaker at multi-step reasoning across many
  pages.
