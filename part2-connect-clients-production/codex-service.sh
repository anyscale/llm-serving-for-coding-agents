#!/usr/bin/env bash
set -euo pipefail

# DEMO-ONLY: launch Codex against the PUBLIC Anyscale Service's /v1/responses (direct streaming).
# The production pattern — shown, not run live at the event.
#
# Set ANYSCALE_BASE_URL + ANYSCALE_API_KEY, or the script prompts you for them:
#   ANYSCALE_BASE_URL (must end in /v1)   ANYSCALE_API_KEY (bearer token)
# Get both from the Anyscale console -> Services -> your service -> Query.
#
# Requires: npm i -g @openai/codex   ·   Prereq: export BRAVE_API_KEY=…
# Usage:
#   ./codex-service.sh                      # interactive
#   ./codex-service.sh "explain this repo"  # a prompt passes straight through

# Prompt for anything not already in the environment (values from the console Query panel).
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "codex-service: enter your Anyscale Service details (console -> Services -> your service -> Query)." >&2
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" ]]; then
  read -rp "  service base URL (ends in /v1): " ANYSCALE_BASE_URL || true
fi
if [[ -z "${ANYSCALE_API_KEY:-}" ]]; then
  read -rsp "  service bearer token: " ANYSCALE_API_KEY || true; echo >&2
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "codex-service: base URL and token are both required." >&2
  exit 1
fi
BASE="${ANYSCALE_BASE_URL%/}"
export ANYSCALE_API_KEY   # exported so the codex provider (env_key=ANYSCALE_API_KEY) can read it
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"
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
