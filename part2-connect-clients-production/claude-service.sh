#!/usr/bin/env bash
set -euo pipefail

# DEMO-ONLY: launch Claude Code against the PUBLIC Anyscale Service (not the workspace tunnel).
# The service serves /v1/messages via direct streaming; Claude Code POSTs to
# ${ANTHROPIC_BASE_URL}/v1/messages. This is the production pattern — shown, not run live at the event.
#
# Defaults point at the shared demo service below. Override for your own service:
#   ANYSCALE_BASE_URL (must end in /v1)   ANYSCALE_API_KEY (bearer token)
#
# Usage:
#   ./claude-service.sh            # interactive
#   ./claude-service.sh -p "hi"    # extra args pass to claude
#
# Prereq: export BRAVE_API_KEY=…  (for the Brave web-search MCP in .mcp.json)

ANYSCALE_BASE_URL="${ANYSCALE_BASE_URL:-https://qwen3-6-27b-fp8-jgz99.cld-kvedzwag2qa8i5bj.s.anyscaleuserdata.com/v1}"
ANYSCALE_API_KEY="${ANYSCALE_API_KEY:-fULTzITwglt9TAn0kns0RAAIlFDxOk_F07xKkfPVpm0}"
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
