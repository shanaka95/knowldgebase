#! /usr/bin/env bash
# Serves the MinerU2.5 document-parsing model on an OpenAI-compatible endpoint.
#
# Everything else in this project runs in Docker. Model inference cannot: MLX
# needs direct access to the Apple Silicon GPU, which containers do not get.
#
# The chat and embedding models are served by vMLX Studio, but MinerU is not:
# vMLX bundles mlx-vlm 0.5.0, whose qwen2_vl vision stack crashes on this model
# ("tile(): incompatible function arguments"). It therefore gets its own tiny
# server built on mlx-vlm 0.7 - the version MinerU itself targets.
#
# Usage:  bash scripts/mineru-server.sh [--port 8010]
# Then:   the port must match [parser].base_url in models.toml
set -euo pipefail

MODEL_REPO="opendatalab/MinerU2.5-Pro-2605-1.2B"
PORT="${MINERU_PORT:-8010}"
HOST="${MINERU_HOST:-127.0.0.1}"
SERVER_DIR="${MINERU_SERVER_DIR:-$HOME/.cache/mineru-server}"
PATCHED_DIR="${MINERU_MODEL_DIR:-$HOME/.cache/vmlx-models/MinerU2.5-Pro-2605-1.2B}"

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null 2>&1 || {
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
}

# 1. Download the model (cached in ~/.cache/huggingface after the first run).
if [ ! -d "$PATCHED_DIR" ]; then
  echo "==> Downloading $MODEL_REPO"
  SNAPSHOT=$(uv tool run --from "huggingface_hub[hf_xet]" \
    hf download "$MODEL_REPO" | tail -1 | sed 's/^path=//')

  # The checkpoint ties its output layer to the input embeddings, but records
  # that only in config.json's nested text_config. mlx-vlm reads the flag from
  # the top level, so without this it looks for an lm_head tensor that the file
  # does not contain and refuses to load. Patch a copy, never the HF cache.
  echo "==> Preparing $PATCHED_DIR"
  mkdir -p "$PATCHED_DIR"
  uv run --no-project python - "$SNAPSHOT" "$PATCHED_DIR" <<'PY'
import json, os, sys
src, dest = sys.argv[1], sys.argv[2]
for name in os.listdir(src):
    source = os.path.realpath(os.path.join(src, name))
    target = os.path.join(dest, name)
    if os.path.lexists(target):
        os.remove(target)
    if name == "config.json":
        config = json.load(open(source))
        config["tie_word_embeddings"] = True
        json.dump(config, open(target, "w"), indent=2)
    else:
        os.symlink(source, target)
PY
fi

# 2. Isolated environment for mlx-vlm (kept out of the project's own venv).
if [ ! -x "$SERVER_DIR/.venv/bin/python" ]; then
  echo "==> Creating $SERVER_DIR"
  mkdir -p "$SERVER_DIR"
  (cd "$SERVER_DIR" && uv venv --python 3.12 -q && uv pip install -q "mlx-vlm>=0.7.0,<0.8.0")
fi

echo "==> MinerU on http://$HOST:$PORT/v1"
echo "    models.toml [parser] should read:"
echo "      base_url = \"http://host.docker.internal:$PORT/v1\""
echo "      model    = \"$PATCHED_DIR\""
exec "$SERVER_DIR/.venv/bin/python" -m mlx_vlm.server \
  --model "$PATCHED_DIR" --host "$HOST" --port "$PORT"
