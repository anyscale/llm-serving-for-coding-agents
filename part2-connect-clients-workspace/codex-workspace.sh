#!/usr/bin/env bash
set -euo pipefail

# One command: open the SSH tunnel to the workspace (if it isn't already open) and launch Codex against
# the qwen LLM served there. Direct streaming exposes /v1/responses; wire_api=responses POSTs to
# ${BASE}/responses on localhost:8000.
#
# Usage:
#   ./codex-workspace.sh <workspace-name>                      # interactive
#   ./codex-workspace.sh <workspace-name> "explain this repo"  # a prompt passes straight through
#   WORKSPACE_NAME=my-ws ./codex-workspace.sh                  # name via env instead of the first arg
#
# Requires: npm i -g @openai/codex   ·   Prereq: export BRAVE_API_KEY=…

BASE="${WORKSPACE_LLM_URL:-http://localhost:8000}/v1"   # ends in /v1
MODEL="${WORKSPACE_MODEL:-qwen3.6-27b}"
PROVIDER="workspace-local"
CTX="${CODEX_MODEL_CONTEXT_WINDOW:-32768}"
MAXOUT="${CODEX_MODEL_MAX_OUTPUT_TOKENS:-8192}"

# Workspace name from the first non-flag arg or $WORKSPACE_NAME (needed only to open the tunnel).
WS="${WORKSPACE_NAME:-}"
if [[ "${1:-}" == [!-]* ]]; then WS="$1"; shift; fi

command -v codex >/dev/null 2>&1 || { echo "codex-workspace: codex CLI not on PATH (npm i -g @openai/codex)." >&2; exit 1; }

# Open the tunnel ourselves unless localhost:8000 already answers (e.g. reusing claude-workspace's tunnel).
if ! curl -sf --max-time 3 "${BASE}/models" >/dev/null 2>&1; then
  command -v anyscale >/dev/null 2>&1 || { echo "codex-workspace: anyscale CLI not on PATH." >&2; exit 1; }
  [[ -n "$WS" ]] || { echo "codex-workspace: workspace name required — ./codex-workspace.sh <workspace-name> (or set WORKSPACE_NAME)." >&2; exit 1; }
  echo "codex-workspace: opening SSH tunnel to workspace '${WS}' (localhost:8000) …" >&2
  anyscale workspace_v2 ssh -n "$WS" -- -N -L 8000:localhost:8000 &
  TUNNEL_PID=$!
  trap 'kill "$TUNNEL_PID" 2>/dev/null || true' EXIT INT TERM
  for _ in $(seq 1 60); do
    curl -sf --max-time 3 "${BASE}/models" >/dev/null 2>&1 && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "codex-workspace: tunnel exited early — check the workspace name and that it's RUNNING." >&2; exit 1; }
    sleep 1
  done
  curl -sf --max-time 3 "${BASE}/models" >/dev/null 2>&1 || { echo "codex-workspace: ${BASE} still not reachable after 60s — is the serve app up in the workspace?" >&2; exit 1; }
  echo "codex-workspace: tunnel up." >&2
else
  echo "codex-workspace: localhost:8000 already reachable — reusing the open tunnel." >&2
fi

# localhost serve has no auth, but Codex requires env_key to name a non-empty var — send a dummy.
export WORKSPACE_API_KEY="local"

echo "codex-workspace: Codex -> ${MODEL} @ ${BASE}/responses (workspace via localhost tunnel)" >&2

# Hosted tools (web_search / image gen / plugins) hit routes the custom provider doesn't serve — off;
# web search comes from the local Brave MCP in .codex/config.toml. requires_openai_auth=false so a clean
# ~/.codex needs no OpenAI login. Your ~/.codex auth/trust are untouched.
# No exec: keep this shell alive so the EXIT trap can close the tunnel when Codex quits.
codex \
  -c model="${MODEL}" \
  -c model_provider="${PROVIDER}" \
  -c "model_providers.${PROVIDER}.name=Workspace-local" \
  -c "model_providers.${PROVIDER}.base_url=${BASE}" \
  -c "model_providers.${PROVIDER}.env_key=WORKSPACE_API_KEY" \
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
