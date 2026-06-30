# llm-serving-for-coding-agents

Self-host an open-source coding-assistant LLM on **Anyscale + Ray Serve LLM**, and drive
**Claude Code, Codex, and Cursor** against it — with **no proxy**.

The model — `qwen3.6-27b`, a 27B FP8 hybrid-reasoning + tool-calling model — is served with **direct
streaming** on, so a single endpoint speaks all three coding-agent APIs natively:

| Path | Agent |
|---|---|
| `POST /v1/chat/completions` | Cursor (OpenAI) |
| `POST /v1/messages` | Claude Code (Anthropic) |
| `POST /v1/responses` | Codex (OpenAI Responses) |

## Two steps

| | What you get | Folder |
|---|---|---|
| **1 — Deploy** | A working endpoint on Anyscale (4× L4), with **direct streaming** enabled so it serves all three agent APIs from one service. | [`part1-deploy-naive/`](./part1-deploy-naive/) |
| **2a — Connect (direct)** | Point Claude Code, Codex, and Cursor **straight at the native endpoints** — no LiteLLM, no `pip install`. | [`part2a-connect-clients-direct/`](./part2a-connect-clients-direct/) |

## Quick start

```bash
# 1) Deploy
cd part1-deploy-naive
anyscale service deploy -f service_naive.yaml        # wait for RUNNING; grab the URL + token

# 2a) Connect your agents directly (no proxy)
cd ../part2a-connect-clients-direct
cp .env.example .env && $EDITOR .env                 # paste service URL (+/v1), token, model id
./smoke-test-direct.sh                               # all 3 native endpoints should return 200
./run-claude-direct.sh                               # Claude Code on qwen3.6-27b
#   or ./run-codex-direct.sh   |   see cursor-setup.md (Cursor)
```

## Prerequisites
- An Anyscale account + the CLI: `pip install anyscale`, then `anyscale login`.
- Image: `anyscale/ray-llm:2.56.0-py312-cu130` (GA, ships vLLM 0.22.0 — new enough for this model).
- Agents: Claude Code, `npm i -g @openai/codex`, and/or Cursor.

## How "direct streaming" works (the key enabler)

Direct streaming puts vLLM's **native** ASGI app behind HAProxy, so the service exposes `/v1/messages`
(Anthropic) and `/v1/responses` (OpenAI Responses) alongside `/v1/chat/completions`. It's turned on by two
**service-level `env_vars`** in [`part1-deploy-naive/service_naive.yaml`](./part1-deploy-naive/service_naive.yaml):

```yaml
env_vars:
  RAY_SERVE_ENABLE_HA_PROXY: "1"
  RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING: "1"
```

These must be **service-level** (not a per-deployment `runtime_env`): the Ray Serve **controller** reads
`RAY_SERVE_ENABLE_HA_PROXY` at startup, and a `runtime_env` only reaches the replicas — so setting them there
makes the deploy fail with *"ingress_request_router requires HAProxy."* Anyscale applies service-level
`env_vars` cluster-wide, so the controller inherits them. See the [Part 1 README](./part1-deploy-naive/README.md)
for the full explanation.

> A **LiteLLM-gateway** alternative also exists (translates the agent APIs to plain Chat Completions, so it
> works even against a service *without* direct streaming). This repo uses the simpler **direct** path.

---
*Model: `qwen3.6-27b` · Anyscale + Ray Serve LLM (vLLM 0.22.0) · AWS us-west-2.*
