#!/usr/bin/env bash
set -euo pipefail

# One command: open the SSH tunnel to the workspace (if it isn't already open) and launch Claude Code
# against the qwen LLM served there. Direct streaming exposes /v1/messages; Claude Code POSTs to
# ${ANTHROPIC_BASE_URL}/v1/messages on localhost:8000.
#
# Usage:
#   ./claude-workspace.sh <workspace-name>            # interactive
#   ./claude-workspace.sh <workspace-name> -p "hi"    # extra args pass to claude
#   WORKSPACE_NAME=my-ws ./claude-workspace.sh        # name via env instead of the first arg
#
# Prereq: export BRAVE_API_KEY=…  (for the Brave web-search MCP in .mcp.json)

BASE="${WORKSPACE_LLM_URL:-http://localhost:8000}"   # root, no /v1
MODEL="${WORKSPACE_MODEL:-qwen3.6-27b}"

# Workspace name from the first non-flag arg or $WORKSPACE_NAME (needed only to open the tunnel).
WS="${WORKSPACE_NAME:-}"
if [[ "${1:-}" == [!-]* ]]; then WS="$1"; shift; fi

command -v claude >/dev/null 2>&1 || { echo "claude-workspace: claude CLI not on PATH." >&2; exit 1; }

# Open the tunnel ourselves unless localhost:8000 already answers (e.g. a second agent reusing it).
if ! curl -sf --max-time 3 "${BASE}/v1/models" >/dev/null 2>&1; then
  command -v anyscale >/dev/null 2>&1 || { echo "claude-workspace: anyscale CLI not on PATH." >&2; exit 1; }
  [[ -n "$WS" ]] || { echo "claude-workspace: workspace name required — ./claude-workspace.sh <workspace-name> (or set WORKSPACE_NAME)." >&2; exit 1; }
  echo "claude-workspace: opening SSH tunnel to workspace '${WS}' (localhost:8000) …" >&2
  anyscale workspace_v2 ssh -n "$WS" -- -N -L 8000:localhost:8000 &
  TUNNEL_PID=$!
  trap 'kill "$TUNNEL_PID" 2>/dev/null || true' EXIT INT TERM
  for _ in $(seq 1 60); do
    curl -sf --max-time 3 "${BASE}/v1/models" >/dev/null 2>&1 && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "claude-workspace: tunnel exited early — check the workspace name and that it's RUNNING." >&2; exit 1; }
    sleep 1
  done
  curl -sf --max-time 3 "${BASE}/v1/models" >/dev/null 2>&1 || { echo "claude-workspace: ${BASE} still not reachable after 60s — is the serve app up in the workspace?" >&2; exit 1; }
  echo "claude-workspace: tunnel up." >&2
else
  echo "claude-workspace: localhost:8000 already reachable — reusing the open tunnel." >&2
fi

# localhost serve has no auth, but Claude Code requires a non-empty token — send a dummy.
export ANTHROPIC_BASE_URL="${BASE%/}"
export ANTHROPIC_AUTH_TOKEN="workspace-local"
unset ANTHROPIC_API_KEY   # avoid the "both AUTH_TOKEN and API_KEY set" warning
export ANTHROPIC_MODEL="${MODEL}"
# Remap every named tier so /model, subagents, and background tasks all land on qwen.
export ANTHROPIC_DEFAULT_OPUS_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${MODEL}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1200000}"   # ride out the cold start

echo "claude-workspace: Claude Code -> ${MODEL} @ ${ANTHROPIC_BASE_URL}/v1/messages (workspace via localhost tunnel)" >&2
# No exec: keep this shell alive so the EXIT trap can close the tunnel when Claude Code quits.
claude "$@"
