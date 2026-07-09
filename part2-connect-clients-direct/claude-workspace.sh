#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code against the qwen LLM served INSIDE an Anyscale workspace, reached over
# the SSH tunnel on localhost:8000 (the "workspace + localhost" route).
# Direct streaming exposes /v1/messages; Claude Code POSTs to ${ANTHROPIC_BASE_URL}/v1/messages.
#
# Prereq: workspace RUNNING, serve app up, and the tunnel open in another shell:
#   anyscale workspace_v2 ssh -n qwen-localhost-expt -- -N -L 8000:localhost:8000
#
# Usage:
#   ./claude-workspace.sh            # interactive
#   ./claude-workspace.sh -p "hi"    # args pass straight to claude

BASE="${WORKSPACE_LLM_URL:-http://localhost:8000}"   # root, no /v1
MODEL="${WORKSPACE_MODEL:-qwen3.6-27b}"

command -v claude >/dev/null 2>&1 || { echo "claude-workspace: claude CLI not on PATH." >&2; exit 1; }

# Preflight: is the tunnel up? Fail fast with the fix instead of a cryptic connect error.
if ! curl -sf --max-time 5 "${BASE}/v1/models" >/dev/null 2>&1; then
  echo "claude-workspace: ${BASE} not reachable — is the workspace up and the tunnel open?" >&2
  echo "  anyscale workspace_v2 ssh -n qwen-localhost-expt -- -N -L 8000:localhost:8000" >&2
  exit 1
fi

# localhost serve has no auth, but Claude Code requires a non-empty token — send a dummy.
export ANTHROPIC_BASE_URL="${BASE%/}"
export ANTHROPIC_AUTH_TOKEN="workspace-local"
unset ANTHROPIC_API_KEY   # avoid the "both AUTH_TOKEN and API_KEY set" warning
export ANTHROPIC_MODEL="${MODEL}"
# Remap every named tier so /model, subagents, and background tasks all land on qwen,
# never a real Anthropic model. DEFAULT_HAIKU covers the small/fast background model.
export ANTHROPIC_DEFAULT_OPUS_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${MODEL}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${MODEL}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1200000}"   # ride out the cold start

echo "claude-workspace: Claude Code -> ${MODEL} @ ${ANTHROPIC_BASE_URL}/v1/messages (workspace via localhost tunnel)" >&2
exec claude "$@"
