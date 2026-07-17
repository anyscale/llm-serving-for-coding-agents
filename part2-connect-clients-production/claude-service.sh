#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code against a PUBLIC Anyscale Service (the production path, vs the workspace tunnel).
# The service serves /v1/messages via direct streaming; Claude Code POSTs to
# ${ANTHROPIC_BASE_URL}/v1/messages. This is the production pattern (public URL + token).
#
# Set ANYSCALE_BASE_URL + ANYSCALE_API_KEY + ANYSCALE_MODEL, or the script prompts for all three:
#   ANYSCALE_BASE_URL (ends in /v1)   ANYSCALE_API_KEY (bearer token)   ANYSCALE_MODEL (default qwen3.6-27b)
# Get the URL + token from the Anyscale console -> Services -> your service -> Query.
#
# Usage:
#   ./claude-service.sh            # interactive
#   ./claude-service.sh -p "hi"    # extra args pass to claude
#
# Prereq: export BRAVE_API_KEY=…  (for the Brave web-search MCP in .mcp.json)

# Endpoint, token, and model id all come from the environment, or the script asks for all three
# together. Asking only the missing ones would risk pairing a stale export (e.g. an old endpoint)
# with fresh input, so it is all-or-nothing.
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" || -z "${ANYSCALE_MODEL:-}" ]]; then
  echo "claude-service: enter your Anyscale Service details (console -> Services -> your service -> Query)." >&2
  default_model="${ANYSCALE_MODEL:-qwen3.6-27b}"
  read -rp  "  service base URL (ends in /v1): " ANYSCALE_BASE_URL || true
  read -rsp "  service bearer token: " ANYSCALE_API_KEY || true; echo >&2
  read -rp  "  model id [${default_model}]: " ANYSCALE_MODEL || true
  ANYSCALE_MODEL="${ANYSCALE_MODEL:-$default_model}"
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "claude-service: base URL and token are both required." >&2
  exit 1
fi
MODEL="$ANYSCALE_MODEL"

command -v claude >/dev/null 2>&1 || { echo "claude-service: claude CLI not on PATH." >&2; exit 1; }

# Claude Code appends /v1/messages itself, so ANTHROPIC_BASE_URL must be the service ROOT (strip /v1).
BASE="${ANYSCALE_BASE_URL%/v1}"; BASE="${BASE%/}"
export ANTHROPIC_BASE_URL="$BASE"
export ANTHROPIC_AUTH_TOKEN="$ANYSCALE_API_KEY"
unset ANTHROPIC_API_KEY   # use only the bearer token; avoid the "both set" warning
export ANTHROPIC_MODEL="$MODEL"
# Remap every named tier so /model, subagents, and background tasks all land on qwen.
export ANTHROPIC_DEFAULT_OPUS_MODEL="$MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1200000}"   # ride out the cold start

echo "claude-service: Claude Code -> ${MODEL} @ ${ANTHROPIC_BASE_URL}/v1/messages (public service)" >&2
exec claude "$@"
