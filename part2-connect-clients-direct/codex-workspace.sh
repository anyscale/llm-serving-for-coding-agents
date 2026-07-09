#!/usr/bin/env bash
set -euo pipefail

# Launch the OpenAI Codex CLI against the qwen LLM served INSIDE an Anyscale workspace, reached
# over the SSH tunnel on localhost:8000 (the "workspace + localhost" route).
# Direct streaming exposes /v1/responses; wire_api=responses POSTs to ${BASE}/responses.
#
# Prereq: workspace RUNNING, serve app up, and the tunnel open in another shell:
#   anyscale workspace_v2 ssh -n qwen-localhost-expt -- -N -L 8000:localhost:8000
#
# Requires: npm i -g @openai/codex
#
# Usage:
#   ./codex-workspace.sh                      # interactive
#   ./codex-workspace.sh "explain this repo"  # a prompt passes straight through

BASE="${WORKSPACE_LLM_URL:-http://localhost:8000}/v1"   # ends in /v1
MODEL="${WORKSPACE_MODEL:-qwen3.6-27b}"
PROVIDER="workspace-local"
CTX="${CODEX_MODEL_CONTEXT_WINDOW:-32768}"
MAXOUT="${CODEX_MODEL_MAX_OUTPUT_TOKENS:-8192}"

command -v codex >/dev/null 2>&1 || { echo "codex-workspace: codex CLI not on PATH (npm i -g @openai/codex)." >&2; exit 1; }

# Preflight: is the tunnel up? Fail fast with the fix instead of a cryptic connect error.
if ! curl -sf --max-time 5 "${BASE}/models" >/dev/null 2>&1; then
  echo "codex-workspace: ${BASE} not reachable — is the workspace up and the tunnel open?" >&2
  echo "  anyscale workspace_v2 ssh -n qwen-localhost-expt -- -N -L 8000:localhost:8000" >&2
  exit 1
fi

# localhost serve has no auth, but Codex requires env_key to name a non-empty var — send a dummy.
export WORKSPACE_API_KEY="local"

echo "codex-workspace: Codex -> ${MODEL} @ ${BASE}/responses (workspace via localhost tunnel)" >&2

# Feature disables keep Codex to plain function tools; web_search/image_gen/etc. would hit routes
# the custom provider doesn't serve. (Brave web search comes via MCP instead — see .codex/config.toml.)
# Your ~/.codex auth/trust are untouched.
exec codex \
  -c model="${MODEL}" \
  -c model_provider="${PROVIDER}" \
  -c "model_providers.${PROVIDER}.name=Workspace-local" \
  -c "model_providers.${PROVIDER}.base_url=${BASE}" \
  -c "model_providers.${PROVIDER}.env_key=WORKSPACE_API_KEY" \
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
