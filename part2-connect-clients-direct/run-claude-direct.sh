#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code DIRECTLY against the Anyscale service's native Anthropic endpoint.
# The service serves /v1/messages because Part 1 turns on direct streaming. Claude Code
# POSTs to ${ANTHROPIC_BASE_URL}/v1/messages.
#
# Usage:
#   ./run-claude-direct.sh            # interactive
#   ./run-claude-direct.sh -p "hi"    # extra args pass straight to claude

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# ---- load .env -------------------------------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  set -a; # shellcheck disable=SC1090
  source "${ENV_FILE}"; set +a
fi

: "${ANYSCALE_BASE_URL:?set ANYSCALE_BASE_URL in .env (e.g. https://HOST.s.anyscaleuserdata.com/v1)}"
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"

# Claude Code appends /v1/messages itself, so ANTHROPIC_BASE_URL must be the service ROOT (strip /v1).
ANTHROPIC_BASE_URL="${ANYSCALE_BASE_URL%/v1}"; ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL%/}"

# ---- preflight -------------------------------------------------------------
command -v claude >/dev/null 2>&1 || { echo "run-claude-direct: claude CLI not on PATH." >&2; exit 1; }
if [[ -z "${ANYSCALE_API_KEY:-}" ]]; then
  printf "Anyscale API key (token): " >&2
  stty -echo; read -r ANYSCALE_API_KEY; stty echo; printf "\n" >&2
fi

# ---- point Claude Code straight at the service -----------------------------
export ANTHROPIC_BASE_URL
export ANTHROPIC_AUTH_TOKEN="${ANYSCALE_API_KEY}"
# Use ONLY the bearer token. Setting ANTHROPIC_API_KEY too makes Claude Code warn
# "Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set"; unset any inherited one.
unset ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-${MODEL}}"
export ANTHROPIC_SMALL_FAST_MODEL="${ANTHROPIC_SMALL_FAST_MODEL:-${MODEL}}"
# Remap every named tier (opus/sonnet/haiku) so /model switches, subagents, and agent-teams
# can never resolve to a real Anthropic model — all land on Qwen.
export ANTHROPIC_DEFAULT_OPUS_MODEL="${ANTHROPIC_DEFAULT_OPUS_MODEL:-${MODEL}}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-${MODEL}}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL:-${MODEL}}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-1}"
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1200000}"

echo "run-claude-direct: Claude Code -> ${MODEL} @ ${ANTHROPIC_BASE_URL}/v1/messages (direct, no proxy)" >&2
exec claude "$@"
