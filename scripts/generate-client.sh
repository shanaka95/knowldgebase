#! /usr/bin/env bash
# Regenerates the typed frontend API client from the backend's OpenAPI schema.
# bun runs inside a container so it does not need to be installed on the host.

set -e
set -x

cd backend
FASTAPI_ENV=development uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../frontend/openapi.json
cd ..

if command -v bun >/dev/null 2>&1; then
  bun run --filter frontend generate-client
  bun run lint
else
  docker run --rm -v "$PWD":/app -w /app/frontend oven/bun:1 sh -c "bun install && bun run generate-client && bun run lint"
fi
