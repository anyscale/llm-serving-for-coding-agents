#!/usr/bin/env bash
set -euo pipefail

# Launch the OpenAI Codex CLI DIRECTLY against the Anyscale service's native /v1/responses
# endpoint. No proxy, no LiteLLM — the service serves /v1/responses because Part 1 turns on
# direct streaming (vLLM's native Responses route).
#
#   Codex ──OpenAI /v1/responses──►  Anyscale service (qwen3.6-27b, direct streaming)
#
# Requires: npm i -g @openai/codex
#
# Usage:
#   ./run-codex-direct.sh                      # interactive Codex on the Anyscale model
#   ./run-codex-direct.sh "explain this repo"  # a prompt passes straight through
#   ./run-codex-direct.sh exec "summarize x"   # subcommands work too

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# ---- load .env -------------------------------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  set -a; # shellcheck disable=SC1090
  source "${ENV_FILE}"; set +a
fi

BASE="${ANYSCALE_BASE_URL:?set ANYSCALE_BASE_URL in .env}"   # ends in /v1
BASE="${BASE%/}"
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"
PROVIDER="${CODEX_PROVIDER_ID:-anyscale-direct}"
CTX="${CODEX_MODEL_CONTEXT_WINDOW:-32768}"
MAXOUT="${CODEX_MODEL_MAX_OUTPUT_TOKENS:-8192}"

# ---- preflight -------------------------------------------------------------
command -v codex >/dev/null 2>&1 || { echo "run-codex-direct: codex CLI not on PATH (npm i -g @openai/codex)." >&2; exit 1; }
if [[ -z "${ANYSCALE_API_KEY:-}" ]]; then
  printf "Anyscale API key (token): " >&2
  stty -echo; read -r ANYSCALE_API_KEY; stty echo; printf "\n" >&2
fi
export ANYSCALE_API_KEY

echo "run-codex-direct: Codex -> ${MODEL} @ ${BASE}/responses (direct, no proxy)" >&2

# Codex presents ANYSCALE_API_KEY (env_key) straight to the service; wire_api=responses POSTs to
# ${BASE}/responses. The tool/feature disables keep Codex to plain function tools (shell, apply_patch,
# update_plan) — it otherwise offers web_search / image_generation / plugin tools the backend may
# reject. These are defensive on the native route; drop them if your Codex build is fine without.
# Your ~/.codex auth/trust are untouched.
exec codex \
  -c model="${MODEL}" \
  -c model_provider="${PROVIDER}" \
  -c "model_providers.${PROVIDER}.name=Anyscale-direct" \
  -c "model_providers.${PROVIDER}.base_url=${BASE}" \
  -c "model_providers.${PROVIDER}.env_key=ANYSCALE_API_KEY" \
  -c "model_providers.${PROVIDER}.wire_api=responses" \
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
