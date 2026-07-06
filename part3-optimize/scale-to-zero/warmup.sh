#!/usr/bin/env bash
# warmup.sh — wake the scale-to-zero service before the workday.
#
# Sends one tiny completion and retries until the service answers. A cold start from zero =
# g7e node provisioning (minutes) + ~25 s weight load + ~9 s compile restore, so the default
# budget is 15 minutes (override with WARMUP_TIMEOUT_S).
#
# Reads the same variables as part2-connect-clients-direct/.env:
#   ANYSCALE_BASE_URL  — service URL ending in /v1, no trailing slash
#   ANYSCALE_API_KEY   — raw bearer token
#   ANYSCALE_MODEL     — model id (default qwen3.6-27b)
set -euo pipefail

: "${ANYSCALE_BASE_URL:?set ANYSCALE_BASE_URL (service URL ending in /v1)}"
: "${ANYSCALE_API_KEY:?set ANYSCALE_API_KEY (service bearer token)}"
MODEL="${ANYSCALE_MODEL:-qwen3.6-27b}"
DEADLINE=$((SECONDS + ${WARMUP_TIMEOUT_S:-900}))

while true; do
  if curl -fsS --max-time 120 "$ANYSCALE_BASE_URL/chat/completions" \
      -H "Authorization: Bearer $ANYSCALE_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1}" \
      > /dev/null; then
    echo "warm: $MODEL is serving"
    exit 0
  fi
  if (( SECONDS >= DEADLINE )); then
    echo "warmup timed out after ${WARMUP_TIMEOUT_S:-900}s" >&2
    exit 1
  fi
  echo "cold start in progress — retrying in 30 s"
  sleep 30
done
