#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code through the Part 4 LiteLLM router gateway.
# Unlike Part 2's run-claude-direct.sh (all traffic -> Qwen), this launcher keeps
# your Claude subscription login active so the gateway can route or fall back to
# Claude Opus, billed to YOUR Claude Max/Pro plan.
#
# Usage:
#   ./run-claude-router.sh            # interactive, default model = smart-router
#   ./run-claude-router.sh -p "hi"    # extra args pass straight to claude

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# ---- load .env -------------------------------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  set -a; # shellcheck disable=SC1090
  source "${ENV_FILE}"; set +a
fi

: "${GATEWAY_BASE_URL:?set GATEWAY_BASE_URL in .env (e.g. https://GATEWAY-HOST.s.anyscaleuserdata.com, no /v1)}"
# Claude Code appends /v1/messages itself, so ANTHROPIC_BASE_URL must be the gateway ROOT.
GATEWAY_BASE_URL="${GATEWAY_BASE_URL%/v1}"; GATEWAY_BASE_URL="${GATEWAY_BASE_URL%/}"
MODEL="${ROUTER_MODEL:-smart-router}"

# ---- preflight -------------------------------------------------------------
command -v claude >/dev/null 2>&1 || { echo "run-claude-router: claude CLI not on PATH." >&2; exit 1; }
if [[ -z "${LITELLM_MASTER_KEY:-}" ]]; then
  printf "LiteLLM gateway key (from gateway/service.yaml): " >&2
  stty -echo; read -r LITELLM_MASTER_KEY; stty echo; printf "\n" >&2
fi

# ---- point Claude Code at the gateway ---------------------------------------
export ANTHROPIC_BASE_URL="${GATEWAY_BASE_URL}"

# Gateway auth rides in a CUSTOM header, NOT in ANTHROPIC_AUTH_TOKEN/API_KEY.
# Leaving those UNSET preserves your Claude subscription login, whose OAuth
# token Claude Code sends in Authorization and the gateway forwards to
# Anthropic whenever a request routes or falls back to Claude Opus.
export ANTHROPIC_CUSTOM_HEADERS="x-litellm-api-key: Bearer ${LITELLM_MASTER_KEY}"
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY

# Route every Claude Code tier (main/opus/sonnet/haiku/small-fast) through the
# gateway model, so /model switches, subagents, and background tasks all go via
# the router. Default smart-router auto-picks local vs Opus per request.
export ANTHROPIC_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_OPUS_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${MODEL}"
export ANTHROPIC_SMALL_FAST_MODEL="${MODEL}"

# Long timeout so slow first tokens / long agent turns / Claude fallback aren't
# cut off client-side (the gateway caps a single upstream call at 600s).
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1200000}"

cat >&2 <<EOF
run-claude-router: Claude Code -> ${MODEL} @ ${GATEWAY_BASE_URL}/v1/messages (LiteLLM gateway)
  - If prompted, log in with "Claude account with subscription" (enables the Opus path).
  - Verify with /status: login method should be your Claude account, not an API key.
  - Switch on the fly: /model anyscale-qwen3.6-27b | claude-opus-4-8 | smart-router
EOF
exec claude "$@"
