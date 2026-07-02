# llm-serving-for-coding-agents

Self-host an open-source coding-assistant LLM on **Anyscale + Ray Serve LLM** and use it directly from
**Claude Code, Codex, and Cursor**.

This repo serves `qwen3.6-27b`, a 27B FP8 hybrid-reasoning and tool-calling model. With **direct
streaming** enabled, one Anyscale service exposes the native APIs expected by all three agents, without
running a separate proxy.

## What This Repo Shows

| Step | Goal | Folder |
|---|---|---|
| 1 | Deploy `qwen3.6-27b` on Anyscale with Ray Serve LLM. | [`part1-deploy-naive/`](./part1-deploy-naive/) |
| 2 | Connect Claude Code, Codex, and Cursor directly to the service. | [`part2-connect-clients-direct/`](./part2-connect-clients-direct/) |
| 3 | Optimize the deployment for a 1x RTX PRO 6000 with 256K FP8 context. | [`part3-optimize/`](./part3-optimize/) |

## API Endpoints

The same service exposes each agent's expected API path:

| Path | Used by |
|---|---|
| `POST /v1/chat/completions` | Cursor |
| `POST /v1/messages` | Claude Code |
| `POST /v1/responses` | Codex |

## Prerequisites

- An Anyscale account.
- The Anyscale CLI: `pip install anyscale`, then `anyscale login`.
- One or more coding agents: Claude Code, Codex (`npm i -g @openai/codex`), or Cursor.
- The Ray LLM image `anyscale/ray-llm:2.56.0-py312-cu130`, which includes vLLM 0.22.0.

## Quick Start

### 1. Deploy the service

```bash
cd part1-deploy-naive
anyscale service deploy -f service_naive.yaml
```

Wait for the service to reach `RUNNING`, then copy its URL and bearer token.

### 2. Configure the clients

```bash
cd ../part2-connect-clients-direct
cp .env.example .env
$EDITOR .env
```

Set these required values in `.env`:

```bash
ANYSCALE_BASE_URL="https://HOST.s.anyscaleuserdata.com/v1"
ANYSCALE_API_KEY="<bearer token>"
ANYSCALE_MODEL="qwen3.6-27b"
```

Notes:

- `ANYSCALE_BASE_URL` must end in `/v1` and must not have a trailing slash.
- `ANYSCALE_API_KEY` should be the raw token, without the `Bearer ` prefix.
- `ANYSCALE_MODEL` must match the `model_id` used by the deployed service.

### 3. Verify the service

```bash
set -a && source .env && set +a
curl -fsS -H "Authorization: Bearer $ANYSCALE_API_KEY" "$ANYSCALE_BASE_URL/models"
```

### 4. Launch an agent

```bash
./run-claude-direct.sh
```

You can also run Codex with `./run-codex-direct.sh`. For Cursor, see
[`part2-connect-clients-direct/cursor-setup.md`](./part2-connect-clients-direct/cursor-setup.md).

## How Direct Streaming Works

Direct streaming lets one Ray Serve LLM service expose the OpenAI, Anthropic Messages, and OpenAI
Responses APIs without a separate proxy. Enable it with service-level environment variables in
[`part1-deploy-naive/service_naive.yaml`](./part1-deploy-naive/service_naive.yaml):

```yaml
env_vars:
  RAY_SERVE_ENABLE_HA_PROXY: "1"
  RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING: "1"
```

Set these at the **service level**, not in a per-deployment `runtime_env`, so the Ray Serve controller sees
them during startup. See the [Part 1 README](./part1-deploy-naive/README.md) for details.
