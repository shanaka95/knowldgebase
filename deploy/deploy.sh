#!/usr/bin/env bash
# Push the current working tree to the live server, and prove it arrived.
#
# Written because "docker compose pull && up -d" is not, on its own, a
# deployment: compose reports "Pulled" whether or not the tag moved, a service
# whose image is unchanged is left running, and an image nobody rebuilt keeps
# serving old code indefinitely. The MCP container ran a day-old build for
# several rounds of fixes precisely that way.
#
# So every service is built, pushed, recreated, and then the digest running on
# the server is compared against the digest that was just pushed. A mismatch
# fails the script rather than being reported as success.
#
#   ./deploy/deploy.sh                 # everything
#   ./deploy/deploy.sh backend mcp     # only these
#
# Requires: docker buildx logged in to the registry, ssh access to the host.
set -euo pipefail

HOST="${PLUSGPT_HOST:-root@148.135.25.130}"
REMOTE_DIR="${PLUSGPT_REMOTE_DIR:-/opt/knowledge-base}"
HERMES_DIR="${PLUSGPT_HERMES_DIR:-../hermes-agent}"
MCP_DIR="${PLUSGPT_MCP_DIR:-../knowledgebase-mcp}"
PLATFORM="linux/amd64"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# service:image:build-context:dockerfile — one line per thing that ships.
COMPONENTS=(
  "backend:shanaka95/knowledge-base:.:backend/Dockerfile"
  "worker:shanaka95/knowledge-base:.:backend/Dockerfile"
  "mcp:shanaka95/knowledgebase-mcp:${MCP_DIR}:Dockerfile"
  "hermes-gw-0:shanaka95/hermes-gateway:${HERMES_DIR}:docker/plusgpt-gateway.Dockerfile"
)

WANTED=("$@")
selected() {
  [[ ${#WANTED[@]} -eq 0 ]] && return 0
  local want
  for want in "${WANTED[@]}"; do [[ "$want" == "$1" ]] && return 0; done
  return 1
}

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# --- build and push, once per image ----------------------------------------
# Parallel arrays rather than associative ones: macOS still ships bash 3.2.
BUILT_IMAGES=""
DIGEST_LINES=""
SERVICES=()

digest_for() {
  printf '%s\n' "$DIGEST_LINES" | awk -v img="$1" '$1 == img {print $2}'
}

for entry in "${COMPONENTS[@]}"; do
  IFS=: read -r service image context dockerfile <<<"$entry"
  selected "$service" || continue
  SERVICES+=("$service")

  case " $BUILT_IMAGES " in
    *" $image "*) continue ;;
  esac

  say "building $image"
  # Output to a file: piping the build hides its exit status behind the pipe,
  # which is how two failed builds were once reported as successes.
  log="$(mktemp)"
  if ! docker buildx build --platform "$PLATFORM" \
      -f "$context/$dockerfile" -t "$image:latest" --push "$context" >"$log" 2>&1; then
    echo "build failed for $image:" >&2
    tail -25 "$log" >&2
    exit 1
  fi
  BUILT_IMAGES="$BUILT_IMAGES $image"
  d="$(docker buildx imagetools inspect "$image:latest" --format '{{.Manifest.Digest}}')"
  DIGEST_LINES="$DIGEST_LINES
$image $d"
  echo "pushed $d"
done

[[ ${#SERVICES[@]} -eq 0 ]] && { echo "nothing selected"; exit 1; }

# --- pull and recreate ------------------------------------------------------
# --- host-side state the images do not carry -------------------------------
# The agents' skill is a read-only bind mount, not baked into the gateway
# image, so pushing a new image leaves it exactly as it was. That drifted
# once already: the ask tool started returning documents while the mounted
# skill still told every agent to expect a written answer.
if printf '%s\n' "${SERVICES[@]}" | grep -qx hermes-gw-0; then
  say "syncing the agent skill"
  ssh "$HOST" "mkdir -p $REMOTE_DIR/hermes-skills"
  scp -qr hermes-skills/. "$HOST:$REMOTE_DIR/hermes-skills/"
fi

say "deploying: ${SERVICES[*]}"
# --force-recreate because an unchanged tag leaves the old container running,
# and --pull always because a moved :latest is otherwise invisible to compose.
ssh "$HOST" "cd $REMOTE_DIR && docker compose pull ${SERVICES[*]} && \
  docker compose up -d --force-recreate --pull always ${SERVICES[*]}" >/dev/null

# --- wait for health --------------------------------------------------------
say "waiting for the API"
ssh "$HOST" 'until curl -sf -o /dev/null https://plusgpt.io/api/v1/utils/health-check/; do sleep 3; done'

if printf '%s\n' "${SERVICES[@]}" | grep -qx hermes-gw-0; then
  say "waiting for the gateway"
  ssh "$HOST" "cd $REMOTE_DIR && until docker compose logs --since 5m hermes-gw-0 2>&1 | \
    grep -qE 'Bridge ready|Connected to Telegram'; do sleep 5; done"
fi

# --- prove what is running --------------------------------------------------
say "verifying"
failed=0
for entry in "${COMPONENTS[@]}"; do
  IFS=: read -r service image _ _ <<<"$entry"
  selected "$service" || continue
  running="$(ssh "$HOST" "cd $REMOTE_DIR && docker inspect -f '{{index .RepoDigests 0}}' \
    \$(docker inspect -f '{{.Image}}' \$(docker compose ps -q $service))" 2>/dev/null || true)"
  want="$(digest_for "$image")"
  if [[ "$running" == *"$want"* ]]; then
    printf '  %-12s ok   %s\n' "$service" "${want:0:19}…"
  else
    printf '  %-12s MISMATCH\n     running: %s\n     pushed:  %s\n' "$service" "$running" "$want"
    failed=1
  fi
done

ssh "$HOST" "cd $REMOTE_DIR && docker compose ps --format '  {{.Service}}: {{.State}}'"

if [[ $failed -ne 0 ]]; then
  echo
  echo "A service is not running the image that was just pushed." >&2
  exit 1
fi
say "deployed"
