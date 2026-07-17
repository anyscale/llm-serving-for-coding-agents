#!/usr/bin/env bash
set -euo pipefail

# Launch Codex against a PUBLIC Anyscale Service's /v1/responses (the production path).
# The production pattern (public URL + token).
#
# Set ANYSCALE_BASE_URL + ANYSCALE_API_KEY + ANYSCALE_MODEL, or the script prompts for all three:
#   ANYSCALE_BASE_URL (ends in /v1)   ANYSCALE_API_KEY (bearer token)   ANYSCALE_MODEL (default qwen3.6-27b)
# Get the URL + token from the Anyscale console -> Services -> your service -> Query.
#
# Requires: npm i -g @openai/codex   ·   Prereq: export BRAVE_API_KEY=…
# Usage:
#   ./codex-service.sh                      # interactive
#   ./codex-service.sh "explain this repo"  # a prompt passes straight through

# Endpoint, token, and model id all come from the environment, or the script asks for all three
# together. Asking only the missing ones would risk pairing a stale export (e.g. an old endpoint)
# with fresh input, so it is all-or-nothing.
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" || -z "${ANYSCALE_MODEL:-}" ]]; then
  echo "codex-service: enter your Anyscale Service details (console -> Services -> your service -> Query)." >&2
  default_model="${ANYSCALE_MODEL:-qwen3.6-27b}"
  read -rp  "  service base URL (ends in /v1): " ANYSCALE_BASE_URL || true
  read -rsp "  service bearer token: " ANYSCALE_API_KEY || true; echo >&2
  read -rp  "  model id [${default_model}]: " ANYSCALE_MODEL || true
  ANYSCALE_MODEL="${ANYSCALE_MODEL:-$default_model}"
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "codex-service: base URL and token are both required." >&2
  exit 1
fi
BASE="${ANYSCALE_BASE_URL%/}"
export ANYSCALE_API_KEY   # exported so the codex provider (env_key=ANYSCALE_API_KEY) can read it
MODEL="$ANYSCALE_MODEL"
PROVIDER="anyscale-direct"
CTX="${CODEX_MODEL_CONTEXT_WINDOW:-32768}"
MAXOUT="${CODEX_MODEL_MAX_OUTPUT_TOKENS:-8192}"

command -v codex >/dev/null 2>&1 || { echo "codex-service: codex CLI not on PATH (npm i -g @openai/codex)." >&2; exit 1; }

echo "codex-service: Codex -> ${MODEL} @ ${BASE}/responses (public service)" >&2

# Hosted tools (web_search / image gen / plugins) hit routes the custom provider doesn't serve — off;
# web search comes from the local Brave MCP in .codex/config.toml. requires_openai_auth=false so the
# bearer token is used directly. Your ~/.codex auth/trust are untouched.
exec codex \
  -c model="${MODEL}" \
  -c model_provider="${PROVIDER}" \
  -c "model_providers.${PROVIDER}.name=Anyscale-direct" \
  -c "model_providers.${PROVIDER}.base_url=${BASE}" \
  -c "model_providers.${PROVIDER}.env_key=ANYSCALE_API_KEY" \
  -c "model_providers.${PROVIDER}.wire_api=responses" \
  -c "model_providers.${PROVIDER}.requires_openai_auth=false" \
  -c model_context_window="${CTX}" \
  -c model_max_output_tokens="${MAXOUT}" \
  -c tools.web_search=false \
  -c features.image_generation=false \
  -c features.plugins=false \
  -c features.apps=false \
  -c features.browser_use=false \
  -c features.computer_use=false \
  -c features.multi_agent=false \
  "$@"
