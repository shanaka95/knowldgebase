#! /usr/bin/env bash
# Full backend test run inside Docker Compose (fresh database).

set -e
set -x

docker compose build backend
docker compose down -v --remove-orphans
docker compose up -d db qdrant minio
docker compose run --rm prestart
docker compose run --rm -e FASTAPI_ENV=development backend bash scripts/test.sh "$@"
docker compose down -v --remove-orphans
