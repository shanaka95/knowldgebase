# REST API

Base URL (local): `http://localhost:8800/api/v1`. Interactive docs: `http://localhost:8800/docs`
(Swagger UI) and `http://localhost:8800/redoc`. The full OpenAPI schema is at
`/api/v1/openapi.json`; the frontend's typed client is generated from it.

## Authentication

Every request carries `Authorization: Bearer <token>`. Two kinds of token are accepted on the
same endpoints:

| token | how to get one | scope | intended for |
|---|---|---|---|
| **JWT** | `POST /login/access-token` (form fields `username`, `password`) | full | the web UI, scripts run by a person |
| **Personal API key** (`kb_…`) | Settings → API keys, or `POST /api-keys` with a JWT | `read` or `write` | third-party apps and integrations |

* API keys are shown **once** at creation and stored hashed. They can have an expiry and can be
  revoked at any time.
* A `read` key can call every `GET`; any `POST/PUT/PATCH/DELETE` returns `403 API key lacks write
  scope`.
* Account management (`/users/me*`, `/api-keys*`) only works with a JWT.
* `401` = no/invalid bearer header, `403` = authenticated but not allowed, `404` = not found *or*
  not visible to you (namespaces and documents you cannot see are reported as 404).

## Permission model

* **Namespace** roles: `viewer` < `editor` < `admin`. The owner (and superusers) are admins.
  Members are added by email.
* **Document** access comes from the namespace role, or from an explicit share (`viewer` /
  `editor`) on that single document.
* Editors may create/edit folders and documents. Admins manage members and the namespace itself.
  Only namespace editors/admins may share documents; someone who only has a document share cannot
  re-share it.
* A user who only holds document shares in a namespace can still read that namespace's metadata
  (`GET /namespaces/{id}`, `/by-slug/{slug}`, with `my_role: null`) and gets a tree containing just
  the shared documents, so the web app can render the space shell around a shared page.

## Content formats

Documents are stored as sanitised HTML (`content_html`) plus server-derived plain text
(`content_text`). When creating or updating you may send any of:

```json
{ "content": "<h1>Hello</h1><p>…</p>", "content_format": "html" }
{ "content": "# Hello\n\nSome *markdown*", "content_format": "markdown" }
{ "content": "Plain text.\n\nSecond paragraph.", "content_format": "text" }
```

HTML is sanitised (scripts, event handlers and `javascript:` URLs are removed; editor markup such
as tables, task lists, code blocks and callout panels is preserved).

## Walkthrough with curl

```bash
BASE=http://localhost:8800/api/v1

# 1) Log in (JWT) – only needed to create an API key
JWT=$(curl -s -X POST $BASE/login/access-token \
  -d 'username=shanaka95@gmail.com' -d 'password=shanaka95' | jq -r .access_token)

# 2) Create a write-scoped API key (the "key" field is only returned once)
KEY=$(curl -s -X POST $BASE/api-keys/ -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"name":"my-integration","scope":"write","expires_in_days":365}' | jq -r .key)
AUTH="Authorization: Bearer $KEY"

# 3) Create a namespace (space) and a folder
NS=$(curl -s -X POST $BASE/namespaces/ -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Office","description":"Work docs","icon":"briefcase","color":"blue"}' | jq -r .id)
FOLDER=$(curl -s -X POST $BASE/folders/ -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"namespace_id\":\"$NS\",\"name\":\"Engineering\"}" | jq -r .id)

# 4) Create a document from Markdown
DOC=$(curl -s -X POST $BASE/documents/ -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"namespace_id\":\"$NS\",\"folder_id\":\"$FOLDER\",\"title\":\"Release notes\",
       \"content\":\"# Release notes\\n\\n## 1.2.0\\n- New editor\\n\",\"content_format\":\"markdown\"}" | jq -r .id)

# 5) Update it (optimistic locking: 409 if someone else changed it)
curl -s -X PUT $BASE/documents/$DOC -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"content":"# Release notes\n\n## 1.3.0\n- Faster search\n","content_format":"markdown","expected_version":1}'

# 6) Upload an image and reference it from the document
ATT=$(curl -s -X POST $BASE/attachments/ -H "$AUTH" \
  -F "namespace_id=$NS" -F "document_id=$DOC" -F "file=@diagram.png" )
echo "$ATT" | jq .download_url          # e.g. /api/v1/attachments/<id>/download
# <img src="/api/v1/attachments/<id>/download" data-attachment-id="<id>">

curl -s -H "$AUTH" -o diagram.png $BASE/attachments/<id>/download

# 7) Watch the embedding pipeline
curl -s -H "$AUTH" $BASE/documents/$DOC/embeddings | jq '{embedding_status, is_stale, chunk_count, chunking_method, current_job: .current_job.stage}'

# 8) Force re-indexing (also used for "retry" after a failure)
curl -s -X POST -H "$AUTH" $BASE/documents/$DOC/embeddings/regenerate

# 9) Search. Plain full-text:
curl -s -H "$AUTH" "$BASE/search/?q=faster+search&limit=10" | jq '.data[] | {title, snippet}'

#    …or hybrid: BM25 + vectors over page, summary and chunks, fused with RRF
curl -s -H "$AUTH" "$BASE/search/retrieve?q=faster+search&bm25=true&vector=true" \
  | jq '.data[] | {title, score, sources: [.sources[] | "\(.method):\(.target)#\(.rank)"]}'

# 9a) Ask a question; the answer is written only from your own pages
curl -s -X POST "$BASE/ask/" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"q":"What should I do if the VPN shows error 407?"}' \
  | jq '{answer, used, cited: [.citations[] | select(.cited) | .title]}'

# 9b) Import a PDF or image; it becomes a page and the file stays attached to it
curl -s -X POST "$BASE/imports/" -H "$AUTH" \
  -F "file=@report.pdf" -F "namespace_id=$NS" -F "title=Quarterly report"
curl -s -H "$AUTH" "$BASE/imports/$IMPORT_ID" | jq '{status, pages_done, pages_total, document_id}'

# 10) Share a document / a namespace with another user
curl -s -X POST $BASE/documents/$DOC/shares -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"email":"colleague@example.com","role":"editor"}'
curl -s -X POST $BASE/namespaces/$NS/members -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"email":"colleague@example.com","role":"viewer"}'
```

## Endpoint reference

| Area | Endpoints |
|---|---|
| Auth | `POST /login/access-token`, `POST /login/test-token`, `POST /users/signup`, `GET/PATCH /users/me`, `PATCH /users/me/password` |
| API keys (JWT only) | `GET /api-keys/`, `POST /api-keys/`, `PATCH /api-keys/{id}`, `DELETE /api-keys/{id}` (revoke) |
| Namespaces | `GET/POST /namespaces/`, `GET /namespaces/by-slug/{slug}`, `GET/PATCH/DELETE /namespaces/{id}`, `GET /namespaces/{id}/tree`, `GET/POST /namespaces/{id}/members`, `PATCH/DELETE /namespaces/{id}/members/{user_id}` |
| Folders | `POST /folders/`, `GET /folders/{id}` (children + breadcrumb path), `PATCH /folders/{id}` (rename / move: `parent_id` or `move_to_root`), `DELETE /folders/{id}` |
| Documents | `GET /documents/` (`namespace_id`, `folder_id`, `root_only`, `skip`, `limit`), `GET /documents/recent`, `GET /documents/shared-with-me`, `GET /documents/embeddings/summary`, `POST /documents/`, `GET/PUT/DELETE /documents/{id}`, `POST /documents/{id}/move` |
| Shares | `GET/POST /documents/{id}/shares`, `PATCH/DELETE /documents/{id}/shares/{user_id}` |
| Embeddings | `GET /documents/{id}/embeddings`, `POST /documents/{id}/embeddings/regenerate` |
| Attachments | `POST /attachments/` (multipart: `file`, `namespace_id`, `document_id?`), `GET /attachments/` , `GET /attachments/{id}`, `GET /attachments/{id}/download`, `DELETE /attachments/{id}` |
| Search | `GET /search/?q=&namespace_id=&skip=&limit=` (Postgres full-text), `GET /search/retrieve?q=&bm25=&vector=&targets=` (hybrid BM25 + vector, RRF-fused — see [RETRIEVAL.md](RETRIEVAL.md)) |
| Ask | `POST /ask/` (grounded answer with citations), `POST /ask/stream` (same, server-sent events) — see [ASK.md](ASK.md) |
| Imports | `POST /imports/` (multipart PDF/image), `GET /imports/`, `GET /imports/{id}`, `POST /imports/{id}/retry`, `POST /imports/{id}/cancel`, `DELETE /imports/{id}` — see [IMPORTS.md](IMPORTS.md) |
| Ops | `GET /health/` (no auth), `GET /workers/`, `GET /utils/health-check/` |

### Document object

```json
{
  "id": "…", "namespace_id": "…", "namespace_slug": "office", "folder_id": "…",
  "title": "Release notes",
  "content_html": "<h1>…</h1>", "content_text": "Release notes\n\n…", "summary": "…",
  "version": 3,
  "created_by": "…", "updated_by": "…", "created_at": "…", "updated_at": "…",
  "embedding_status": "ready", "embedding_version": 3, "is_stale": false,
  "source_attachment": {"id": "…", "filename": "report.pdf", "download_url": "…"},
  "embedding_error": null, "embedding_attempts": 0,
  "chunk_count": 3, "chunking_method": "llm", "embedding_updated_at": "…",
  "my_role": "editor"
}
```

`version` increases only when the title or the plain text changes; formatting-only edits keep
the version and do not trigger re-indexing. See [EMBEDDINGS.md](EMBEDDINGS.md) for the pipeline.

### Error codes

| code | meaning |
|---|---|
| 400 | validation problem (e.g. inactive user, removing the owner from a namespace) |
| 401 | missing or malformed `Authorization` header |
| 403 | not allowed (insufficient role, read-only key on a write, API key on a JWT-only endpoint, invalid/expired key) |
| 404 | not found or not visible |
| 409 | conflict: `expected_version` mismatch, duplicate member/share, sharing with someone who already has access |
| 413 | attachment larger than `MAX_UPLOAD_SIZE_MB` |
| 422 | request body/query validation error (e.g. empty search query) |
