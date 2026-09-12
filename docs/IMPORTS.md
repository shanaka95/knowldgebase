# Importing PDFs and images

Upload a PDF or a photo/scan, give it a name (and optionally a prompt), and the
system turns it into a normal page: headings, paragraphs, lists and tables, fully
searchable and indexed like anything you type yourself. The original file is kept
and can be opened from the page at any time.

## What happens

```
upload ─► object storage ─► render pages ─► parse each page ─► create page ─► embed
 queued        rendering         parsing              creating       done
```

1. The file is stored in MinIO (`imports/<job-id>.<ext>`) and an import job row is
   created. The upload endpoint returns immediately.
2. The worker claims the job and renders it to page images with
   [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) at
   `page_dpi` (200 by default). An image upload is a single page. Because the
   model only ever sees images, scans and photos work the same as digital PDFs.
3. Each page goes to **MinerU2.5**, a document-parsing vision model. It runs a
   two-step extraction - layout detection, then content recognition per region -
   and returns typed blocks (`title`, `text`, `table`, `list`, `image`,
   `equation`) with tables already as HTML.
4. Blocks become the page HTML: the first title is an `<h1>`, later titles are
   `<h2>`, bulleted lines are regrouped into `<ul>`, and tables are kept as
   tables. The result is sanitised like any other page content.
5. The page is created and queued for the usual semantic chunking, summary and
   embedding.
6. The uploaded file becomes an `Attachment` on the page, reusing the very same
   stored object, and is linked as the page's `source_attachment`. The document
   page shows it, so the original can be reopened or downloaded whenever needed.

## Models

MinerU2.5 (`opendatalab/MinerU2.5-Pro-2605-1.2B`) is a 1.2B Qwen2-VL model. It
runs **outside Docker**, like the other models, because MLX needs the Apple
Silicon GPU:

```bash
bash scripts/mineru-server.sh          # first run downloads the model
```

The script also patches one thing: the published checkpoint ties its output layer
to the input embeddings but declares that only in the nested `text_config`, while
the loader reads the flag from the top level. Without the patch it looks for an
`lm_head` tensor the file does not contain. The patched copy lives in
`~/.cache/vmlx-models/` and the HuggingFace cache is left untouched.

MinerU cannot run on vMLX Studio itself: vMLX bundles mlx-vlm 0.5.0, whose
`qwen2_vl` vision stack crashes on this model (`tile(): incompatible function
arguments`). The script therefore uses mlx-vlm 0.7, the version MinerU targets.
The chat and embedding models are unaffected and keep using the vMLX gateway.

**Fallback.** If the parser endpoint is unreachable and
`[parser].fallback_to_llm` is on, pages are transcribed by the general
multimodal model (Qwen3.5-9B) instead. It is noticeably weaker on tables and
layout, so it is a safety net rather than an equal option. The parser that was
actually used is recorded on the job and shown in the UI.

Both are configured in `models.toml`:

```toml
[parser]
base_url = "http://host.docker.internal:8010/v1"
model = "…/MinerU2.5-Pro-2605-1.2B"
fallback_to_llm = true
page_dpi = 200
max_pages = 100
```

Any OpenAI-compatible vision endpoint works here, including a hosted one - set
`api_key` in the same section.

## API

```bash
# start an import
curl -X POST http://localhost:8800/api/v1/imports/ \
  -H "Authorization: Bearer $KEY" \
  -F "file=@report.pdf" \
  -F "namespace_id=$NS" \
  -F "folder_id=$FOLDER" \
  -F "title=Quarterly report" \
  -F "prompt=Keep every table"

# watch it
curl -H "Authorization: Bearer $KEY" http://localhost:8800/api/v1/imports/$ID
```

| endpoint | purpose |
|---|---|
| `POST /imports/` | upload a PDF or image (multipart) |
| `GET /imports/` | list your imports, newest first |
| `GET /imports/{id}` | one job with progress |
| `POST /imports/{id}/retry` | re-run a failed or cancelled job |
| `POST /imports/{id}/cancel` | stop a job that is queued or running |
| `DELETE /imports/{id}` | remove the job record |

Accepted types: PDF, PNG, JPEG, WebP, GIF, BMP, TIFF. Size limit
`MAX_IMPORT_SIZE_MB` (50 MB); page limit `[parser].max_pages` (100).

### Job states

| status | meaning |
|---|---|
| `queued` | waiting for a worker (or backing off after a failure) |
| `rendering` | fetching the file and rasterising pages |
| `parsing` | per-page model calls; `pages_done`/`pages_total` advance |
| `creating` | writing the page and its attachment |
| `done` | `document_id` and `attachment_id` are set |
| `failed` | `error` explains why; retryable from the UI |
| `cancelled` | stopped on request |

A file that yields no text (an unreadable scan, a blank page) fails immediately
without burning retries. Transient failures - model server restarting, storage
hiccup - back off `30s · 2^(attempt-1)` and requeue up to three attempts. If a
worker dies mid-parse, its lease expires after `WORKER_LEASE_SECONDS` and another
worker picks the job up.

Imports run with their own small concurrency budget (`IMPORT_CONCURRENCY`,
default 1) so a large PDF cannot starve the embedding pipeline.

## Notes

* Parsing is the slow part: roughly 15-25 s per page for MinerU on an M-series
  Mac, and the first call after idle adds model load time.
* Pictures inside a page are not transcribed into the text; their captions and
  surrounding text are. The original file remains available for anything the
  parser could not represent.
* The created page is a normal page: editable, shareable, movable, and re-indexed
  on every edit.
