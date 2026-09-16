# Deploying to a server

The whole application ships as **one image** (`shanaka95/knowledge-base`) that
runs the API, the built web app and the background worker. Only Postgres, Qdrant
and MinIO run beside it. No models run on the server: they come from any
OpenAI-compatible provider over HTTPS.

Nothing credential-shaped is in the image. `.env` and `models.toml` are in
`.dockerignore`, and every secret is read from the environment at runtime.

## 1. A host with Docker

```bash
apt-get update && apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

## 2. Configuration

Put `compose.deploy.yml` (as `compose.yml`) and a `.env` in `/opt/knowledge-base`:

```env
SECRET_KEY=<openssl rand -base64 36>
FIRST_SUPERUSER=you@example.com
FIRST_SUPERUSER_PASSWORD=<a real password>
PUBLIC_PORT=80
FRONTEND_HOST=http://your-host

POSTGRES_PASSWORD=<random>
MINIO_ACCESS_KEY=kbminio
MINIO_SECRET_KEY=<random>

# One provider, one key. Any OpenAI-compatible endpoint works.
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen3.8-flash
LLM_API_KEY=<key>
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_API_KEY=<key>
EMBEDDING_DIM=4096          # must match the model, or nothing will index
IMPORT_PARSER=llm           # no MinerU here: the chat model reads page images
```

`chmod 600 .env`. Then:

```bash
docker compose up -d
docker compose logs -f backend
```

`prestart` runs the migrations and seeds the admin user before the API starts.

## A domain with HTTPS

`compose.deploy.yml` includes **Caddy**, which obtains and renews Let's Encrypt
certificates on its own. Point the DNS at the host, then add to `.env`:

```env
SITE_DOMAINS=example.com, www.example.com
SITE_DOMAINS_HTTP=http://example.com, http://www.example.com
ACME_EMAIL=you@example.com
SERVER_IP=203.0.113.10          # so the box stays reachable by IP too
FRONTEND_HOST=https://example.com
```

`docker compose up -d` and the certificate is issued within seconds. Caddy keeps
it in the `caddy-data` volume, so restarts do not re-issue.

Port **80 must stay open**: that is how the HTTP-01 challenge is answered, and
how renewal works ninety days later.

### Behind Cloudflare

If the DNS record is proxied (orange cloud), two things differ:

* **Both schemes must serve the app.** Cloudflare's default "Flexible" SSL mode
  connects to the origin over plain HTTP, so the Caddyfile disables the usual
  HTTP→HTTPS redirect and serves both. Redirecting instead would bounce the
  request back to Cloudflare and loop.
* Once the origin has a certificate, switch Cloudflare SSL/TLS to **Full
  (strict)** so the CDN-to-origin leg is encrypted too. Then the
  `auto_https disable_redirects` line in the Caddyfile can go.

Cloudflare passes `/.well-known/acme-challenge/` through to the origin, so
issuance works while proxied. It does block unusual user agents, which is worth
remembering when a script that works against the IP fails against the domain.

#### Purging an asset

A browser asks for `/assets/*` in CORS mode, because Vite marks the entry
`crossorigin`, so those requests carry an `Origin` header and curl does not.
While the origin answered `Vary: Origin` that was a **second cached copy**, and
the two can disagree: one 502 cached into the `Origin` copy left `/search` dead
in every browser while curl, the uptime check and the Cloudflare dashboard all
saw 200, because they were all looking at the other copy.

The origin no longer sends `Vary: Origin` on assets, so new entries have one
copy. Anything cached before that still has two, and **Purge by URL clears only
the copy with no `Origin`** - which is the one that was already fine. Name the
variant, or purge everything:

```sh
curl -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"files":[{"url":"https://plusgpt.io/assets/NAME.js",
                 "headers":{"Origin":"https://plusgpt.io"}}]}'
```

To check a purge rather than trust it, ask the way a browser asks - the header
is the whole difference:

```sh
curl -sI https://plusgpt.io/assets/NAME.js -H 'Origin: https://plusgpt.io'
```

## Things that will bite you

* **`EMBEDDING_DIM` must match the model.** Qwen3-Embedding-8B is 4096, Jina v5
  small is 1024. A mismatch fails every indexing job with a dimension error.
  Changing it later means re-indexing: `POST /api/v1/documents/embeddings/reindex-all`.
* **Reasoning models need `LLM_DISABLE_THINKING=true`** (the default). Without it
  the model spends its output budget thinking and returns empty content.
* **`IMPORT_PARSER=llm`** is required unless you run a MinerU server. With `auto`
  the app probes for one on every import and waits before falling back.
* **1 vCPU hosts**: keep `WORKER_CONCURRENCY=1`. Indexing is network-bound on a
  hosted provider, but Postgres, Qdrant and MinIO all want a slice of the CPU.
* **Port 80 is the only thing published.** Postgres, Qdrant and MinIO are
  reachable only on the Docker network. Put a TLS terminator in front before
  using this with real content.

## Updating

```bash
docker compose pull && docker compose up -d
```

Migrations run automatically through `prestart`. To build and publish a new
image from a checkout:

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile \
  -t shanaka95/knowledge-base:latest --push .
```

Build for `linux/amd64` explicitly: an image built on an Apple Silicon machine is
arm64 and will not start on a typical server.
