# PlusGPT

**A personal knowledge management system.** Organise pages in **spaces** (such as *Personal* or
*Office*) and nested **folders**, write them in a rich editor, file each page under a **type**
(Letter, Invoice, Runbook - your own vocabulary), share spaces or single pages with other people,
and attach images. A background worker indexes every page with **LLM-driven semantic chunking** and
embeddings, so you can search it **lexically (BM25) and semantically at the same time**, fused with
Reciprocal Rank Fusion and then **reranked** by a cross-encoder that reads your query against each
candidate. **Ask** turns that into a written answer with citations. You can also **import PDFs and
images** - singly or many at once, as a page each or combined into one - and a document-parsing
vision model turns them into editable pages while keeping the originals attached.

Accounts are production-grade: email confirmation on sign-up, **a code emailed on every sign-in**,
password reset, session revocation and per-user API keys. Those keys are what an AI assistant uses
to reach the knowledge base over **MCP**, scoped to exactly one person's spaces. See
[docs/AUTH.md](docs/AUTH.md).

Everything except the AI models runs in Docker, and the models are configured in a single file
(`models.toml`) that points at any OpenAI-compatible endpoint.

Built on the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template):
FastAPI + SQLModel + Alembic on Python 3.14; React 19 + Vite + TanStack Router/Query + Tailwind v4 +
shadcn/ui + Tiptap on the frontend; Postgres, Qdrant and MinIO as services.

## Architecture

```
              ┌──────────────── Docker ────────────────────────────────┐
              │                                                        │
  Browser ───►│  Vite :5173          FastAPI :8800 ◄─── API key apps   │
              │                          │                             │
              │   ┌──────────────────────┼──────────────────┐          │
              │   ▼                      ▼                  ▼          │
              │ Postgres :5432      MinIO :9000       Qdrant :6333     │
              │ pages, folders,     attachments,      dense + BM25     │
              │ shares, jobs        imported files    sparse vectors   │
              │   ▲                      ▲                  ▲          │
              │   └────────── Worker (python -m app.worker) ─┘          │
              └──────────────────────────┬─────────────────────────────┘
                                         │ OpenAI-compatible HTTP
                                         ▼           (models.toml)
                            Model servers on the host
                            • Qwen3.5-9B   chunking, summaries   :8080
                            • Jina v5      embeddings, 1024-dim  :8080
                            • MinerU2.5    PDF / image parsing   :8010
```

* **Documents** are stored as sanitised HTML plus a server-derived plain-text copy (no
  encryption). The plain text feeds the Postgres full-text index and the embedding pipeline.
* **Embedding pipeline** (see [docs/EMBEDDINGS.md](docs/EMBEDDINGS.md)): on every create or
  content change the worker asks the LLM to split the page into *semantic* chunks (single-topic
  pages stay whole), writes a summary, embeds page + summary + chunks and stores them in Qdrant.
  Edits during a run cancel it and start over; failures retry with backoff and can be retried
  from the UI.
* **Hybrid search** (see [docs/RETRIEVAL.md](docs/RETRIEVAL.md)): BM25 and vector search run
  against the page, its summary and its chunks, plus a Postgres full-text source so pages are
  findable the moment they are saved. The rankings are fused with RRF, and each method can be
  toggled per query from the search page.
* **Ask** (see [docs/ASK.md](docs/ASK.md)): ask a question, get an answer written from your own
  pages with citations you can click through. Runs the full hybrid retrieval, streams the
  answer, and refuses rather than guessing when the knowledge base has no answer. Follow-ups stay
  in a thread, kept in a rail beside the page; pin a page - from the **Ask** button on it - and the
  answer is written from that page alone, with no search at all.
* **Imports** (see [docs/IMPORTS.md](docs/IMPORTS.md)): upload a PDF or image, MinerU2.5 parses it
  into headings, text and tables, and the original file stays attached to the page.
* **Limits** (see [docs/LIMITS.md](docs/LIMITS.md)): an account may create 100 pages by default.
  Administrators raise or lower that per person, or for a whole class of people by putting them in
  a group — groups are an administrative device, and the people in one are never told.
* **Sharing** (see [docs/SHARING.md](docs/SHARING.md)): share a page with named people,
  invite addresses that have no account yet, publish a read-only link, or take a private copy
  of something somebody shared with you.
* **API** (see [docs/API.md](docs/API.md)): the same endpoints serve the web UI (JWT) and
  integrations (personal API keys with read/write scopes).

**Deploying to a server?** See [DEPLOY.md](DEPLOY.md) — one published image, one
`.env`, any OpenAI-compatible provider for the models, and automatic HTTPS via
Caddy and Let's Encrypt.

## Prerequisites

* Docker Desktop (Compose v2+). The whole application runs inside it.
* Somewhere to run three models, reachable over an OpenAI-compatible HTTP API. Locally that is
  **vMLX Studio** on the host, which serves the chat and embedding models on its gateway
  (`:8080`) and starts them on demand — so the first indexing job after an idle period takes about
  a minute longer.
  * For PDF/image import, start the parser too: `bash scripts/mineru-server.sh` (see
    [docs/IMPORTS.md](docs/IMPORTS.md) for why it needs its own server).
* Optional for host-side development: [uv](https://docs.astral.sh/uv/) (Python) — bun is run
  inside a container so it does not have to be installed.

### Pointing at different models

All model configuration lives in **[`models.toml`](models.toml)** — one place, mounted read-only
into the containers:

```toml
[defaults]
base_url = "http://host.docker.internal:8080/v1"   # any OpenAI-compatible endpoint
api_key = ""                                        # set for hosted providers

[llm]         model = "lmstudio-community/Qwen3.5-9B-MLX-4bit"
[embeddings]  model = "jinaai/jina-embeddings-v5-text-small-retrieval-mlx", dimensions = 1024
[parser]      base_url = "http://host.docker.internal:8010/v1"   # MinerU2.5
```

Point it at OpenAI, vLLM, Ollama, LM Studio or an internal gateway by changing `base_url`,
`api_key` and `model`. Any value can still be overridden by an environment variable
(`LLM_BASE_URL`, `EMBEDDING_API_KEY`, …). Changing the embedding model or its `dimensions`
requires re-indexing (see [docs/RETRIEVAL.md](docs/RETRIEVAL.md)).

## Run everything with Docker Compose

```bash
cp .env.example .env              # then set SECRET_KEY and the passwords
cp models.example.toml models.toml
docker compose up --build
```

Neither file is in version control: `.env` holds the secrets and `models.toml`
points at your model endpoints.

This starts Postgres, Qdrant, MinIO, Adminer, a one-shot `prestart` job (migrations + admin
user), the API, the background worker and the Vite dev server.

| URL | what |
|---|---|
| <http://localhost:5173> | web app (dev server with hot reload) |
| <http://localhost:8800/docs> | API docs (Swagger UI); API at `/api/v1` |
| <http://localhost:8800/api/v1/health/> | health of db / qdrant / minio / embedding / llm / worker |
| <http://localhost:6333/dashboard> | Qdrant dashboard |
| <http://localhost:9001> | MinIO console (credentials in `.env`) |
| <http://localhost:8801> | Adminer (server `db`, user `postgres`, password from `.env`) |

Host ports 8000, 8002 and 8080 are left free for the MLX servers.

**Admin login:** `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` from `.env`
(`shanaka95@gmail.com` / `shanaka95` by default — change them in `.env` before sharing the
instance). New users can self-register on the sign-up page; no e-mail verification.

Useful commands:

```bash
docker compose watch                 # live-sync backend code into the containers
docker compose logs -f worker        # follow the embedding worker
docker compose run --rm prestart     # re-run migrations / re-seed the admin user
docker compose down -v               # stop and delete all data (Postgres, Qdrant, MinIO)
```

The production-style image (`backend/Dockerfile`) builds the frontend into the backend image, so
`docker compose -f compose.yml up` (without the dev override) serves the whole app from
<http://localhost:8800>.

## Develop on the host

```bash
docker compose up -d db qdrant minio           # infrastructure only
uv sync                                        # Python deps (workspace root)
cd backend
uv run bash scripts/prestart.sh                # migrations + admin user
FASTAPI_ENV=development uv run fastapi dev --port 8800
FASTAPI_ENV=development uv run python -m app.worker   # second terminal
# frontend (third terminal, from the repo root)
docker run --rm -it -p 5173:5173 -v "$PWD":/app -w /app/frontend oven/bun:1 \
  sh -c "bun install && bun run dev --host 0.0.0.0"
```

`.env` holds host-side URLs (`localhost`); `compose.yml` overrides them with in-network
hostnames for containers.

### Regenerate the typed frontend client

After changing backend routes or schemas:

```bash
bash scripts/generate-client.sh
```

### Tests and linting

```bash
# backend – runs against a dedicated `app_test` database it creates itself
cd backend && FASTAPI_ENV=development uv run pytest tests -q
uv run bash scripts/lint.sh                       # mypy, ty, ruff

# frontend
docker run --rm -v "$PWD":/app -w /app/frontend oven/bun:1 sh -c "bun install && bun run lint && bunx tsc -p tsconfig.build.json --noEmit"
docker run --rm -v "$PWD":/app -w /app/frontend oven/bun:1 bun run test    # Playwright e2e (needs the stack running)
```

### Database migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Configuration

All settings live in `.env` (see the comments there). Highlights:

Models live in `models.toml`; everything else is in `.env`:

| variable | purpose |
|---|---|
| `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD` | auth + seeded admin |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | database |
| `QDRANT_URL`, `QDRANT_COLLECTION` | vector store |
| `MINIO_*`, `MAX_UPLOAD_SIZE_MB`, `MAX_IMPORT_SIZE_MB` | attachments and imports |
| `RRF_K`, `RETRIEVAL_CANDIDATES_PER_SOURCE`, `VECTOR_MIN_SCORE` | hybrid search fusion |
| `ASK_TOP_K`, `ASK_CONTEXT_CHARS`, `ASK_MAX_TOKENS` | how much context an answer is built from |
| `WORKER_CONCURRENCY`, `IMPORT_CONCURRENCY`, `EMBEDDING_DEBOUNCE_SECONDS`, `EMBEDDING_MAX_ATTEMPTS` | worker behaviour |
| `FRONTEND_HOST` | CORS origin of the dev frontend |
| `MODELS_CONFIG_FILE` | where `models.toml` lives (set automatically by Compose) |

## Repository layout

```
backend/app/api/routes/   REST endpoints (namespaces, folders, documents, attachments, api_keys, search, health, workers)
backend/app/core/         settings, security (JWT + API keys), permissions, content sanitising
backend/app/services/     MinIO, Qdrant, LLM, embeddings, BM25, retrieval, PDF parsing
backend/app/worker/       background job runner, chunking pipeline, import pipeline
backend/app/alembic/      migrations
backend/tests/            pytest suite (API, permissions, content, worker)
frontend/src/routes/      TanStack Router file routes
frontend/src/components/  Editor, Sidebar tree, Documents, Embeddings, Namespaces, Sharing, ApiKeys…
frontend/tests/           Playwright end-to-end tests
docs/                     EMBEDDINGS.md, RETRIEVAL.md, ASK.md, IMPORTS.md, API.md
DEPLOY.md                 running it on a server
compose.deploy.yml        production compose: prebuilt image, one published port
models.toml               model endpoints (base URL, API key, model name per role)
scripts/mineru-server.sh  starts the PDF/image parsing model on the host
compose.yml               services; compose.override.yml = local dev ports/commands
```
