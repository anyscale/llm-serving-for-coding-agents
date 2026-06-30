#!/usr/bin/env bash
set -euo pipefail

# Smoke-test the DIRECT-streaming service: pings all THREE native endpoints with your Anyscale
# token (no proxy). This is the "is direct streaming on?" gate for Part 2a — /v1/messages and
# /v1/responses only exist when direct streaming is active (Part 1 enables it).
#
# Usage:
#   ./smoke-test-direct.sh                 # uses ./.env
#   TIMEOUT=600 ./smoke-test-direct.sh     # override per-request timeout (seconds)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
fi

BASE="${ANYSCALE_BASE_URL:?ANYSCALE_BASE_URL not set}"   # ends in /v1
BASE="${BASE%/}"
ROOT="${BASE%/v1}"; ROOT="${ROOT%/}"
TOKEN="${ANYSCALE_API_KEY:?ANYSCALE_API_KEY not set}"
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"
TIMEOUT="${TIMEOUT:-600}"
AUTH=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")
CURL=(curl -sS -m "${TIMEOUT}" -o /dev/stdout -w "\n--- HTTP %{http_code} in %{time_total}s ---\n")

echo "Service : ${ROOT}"
echo "Model   : ${MODEL}   Timeout: ${TIMEOUT}s (first call may cold-start the service)"
echo

echo "=== 1) OpenAI       POST /v1/chat/completions   (Cursor) ==="
"${CURL[@]}" "${AUTH[@]}" -X POST "${BASE}/chat/completions" \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: CHAT_OK\"}],\"max_tokens\":16,\"chat_template_kwargs\":{\"enable_thinking\":false}}"

echo
echo "=== 2) Anthropic    POST /v1/messages           (Claude Code) ==="
"${CURL[@]}" "${AUTH[@]}" -H "anthropic-version: 2023-06-01" -X POST "${ROOT}/v1/messages" \
  -d "{\"model\":\"${MODEL}\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: MSG_OK\"}]}"

echo
echo "=== 3) OpenAI Resp. POST /v1/responses          (Codex) ==="
"${CURL[@]}" "${AUTH[@]}" -X POST "${BASE}/responses" \
  -d "{\"model\":\"${MODEL}\",\"input\":\"Reply with exactly: RESP_OK\",\"max_output_tokens\":16}"

echo
echo "All three HTTP 200  => direct streaming is live; Part 2a launchers will work."
echo "A 404 on /v1/messages or /v1/responses => direct streaming NOT active on this service."
echo "  -> check the env_vars in ../part1-deploy-naive/service_naive.yaml (see Part 1's README)."
