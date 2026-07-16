#!/usr/bin/env bash
set -euo pipefail

# DEMO-ONLY: launch Claude Code against the PUBLIC Anyscale Service (not the workspace tunnel).
# The service serves /v1/messages via direct streaming; Claude Code POSTs to
# ${ANTHROPIC_BASE_URL}/v1/messages. This is the production pattern — shown, not run live at the event.
#
# Set ANYSCALE_BASE_URL + ANYSCALE_API_KEY, or the script prompts you for them:
#   ANYSCALE_BASE_URL (must end in /v1)   ANYSCALE_API_KEY (bearer token)
# Get both from the Anyscale console -> Services -> your service -> Query.
#
# Usage:
#   ./claude-service.sh            # interactive
#   ./claude-service.sh -p "hi"    # extra args pass to claude
#
# Prereq: export BRAVE_API_KEY=…  (for the Brave web-search MCP in .mcp.json)

# Prompt for anything not already in the environment (values from the console Query panel).
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "claude-service: enter your Anyscale Service details (console -> Services -> your service -> Query)." >&2
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" ]]; then
  read -rp "  service base URL (ends in /v1): " ANYSCALE_BASE_URL || true
fi
if [[ -z "${ANYSCALE_API_KEY:-}" ]]; then
  read -rsp "  service bearer token: " ANYSCALE_API_KEY || true; echo >&2
fi
if [[ -z "${ANYSCALE_BASE_URL:-}" || -z "${ANYSCALE_API_KEY:-}" ]]; then
  echo "claude-service: base URL and token are both required." >&2
  exit 1
fi
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"

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
