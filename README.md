# llm-serving-for-coding-agents

Self-host an open-source coding-assistant LLM on **Anyscale + Ray Serve LLM** and use it from
**Claude Code, Codex, and Cursor**.

This repo serves `qwen3.6-27b`, a 27B FP8 hybrid-reasoning and tool-calling model. With **direct
streaming** enabled, the served model exposes the native Anthropic and OpenAI APIs the agents expect —
no separate proxy.

## What This Repo Shows

| Step | Goal | Folder |
|---|---|---|
| 1 | Deploy `qwen3.6-27b` on Anyscale with Ray Serve LLM. | [`part1-deploy-naive/`](./part1-deploy-naive/) |
| 2 | Connect Claude Code, Codex, and Cursor to the served model. | [`part2-connect-clients-direct/`](./part2-connect-clients-direct/) |
| 3 | Optimize the deployment for a 1x RTX PRO 6000 with 256K FP8 context. | [`part3-optimize/`](./part3-optimize/) |

## API Endpoints (via Direct Streaming)

Direct streaming lets one Ray Serve LLM deployment expose the OpenAI and Anthropic Messages APIs
without a separate proxy. Enable it with service-level environment variables (see
[`part1-deploy-naive/service_naive.yaml`](./part1-deploy-naive/service_naive.yaml)):

```yaml
env_vars:
  RAY_SERVE_ENABLE_HA_PROXY: "1"
  RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING: "1"
```

Set these at the **service level**, not in a per-deployment `runtime_env`, so the Ray Serve controller sees
them during startup. See the [Part 1 README](./part1-deploy-naive/README.md) for details.

With direct streaming enabled, the deployment exposes each agent's expected API path:

| Path | Used by |
|---|---|
| `POST /v1/messages` | Claude Code |
| `POST /v1/responses` | Codex |
| `POST /v1/chat/completions` | Cursor |

## Prerequisites

- An Anyscale account and the Anyscale CLI (`pip install anyscale`, then `anyscale login`).
- Claude Code, Codex, and/or Cursor.
- The Ray LLM image `anyscale/ray-llm:2.56.0-py312-cu130` (vLLM 0.22.0) for the naive service. Claude Code's
  `/v1/messages` needs **vLLM ≥ 0.23** — see [Part 2](./part2-connect-clients-direct/README.md).

## Quick Start

### 1. Deploy the model

```bash
cd part1-deploy-naive
anyscale service deploy -f service_naive.yaml
```

Wait for `RUNNING`, then grab the service URL + bearer token from the console (**Services → your service → Query**).

### 2. Connect a coding agent

Point Claude Code, Codex, or Cursor at the served model — full steps in
[`part2-connect-clients-direct/`](./part2-connect-clients-direct/README.md). In short: Claude Code and Codex reach a
workspace-hosted model over an SSH tunnel (with Brave web-search MCP); Cursor uses the public service URL + token.

### 3. (Optional) Deploy the optimized service

The Part 1 deployment uses 4× L4 GPUs. Part 3 optimizes for a single **RTX PRO 6000 96 GB** GPU with FP8,
256K context, and faster cold starts:

```bash
cd ../part3-optimize
anyscale service deploy -f service_optimized.yaml
```

Optimizations include:

- **RunAI Streamer** — loads weights from S3 directly to GPU (~25 s vs ~85 s).
- **Torch.compile cache** — restores prebuilt caches from S3 (~9 s vs ~74 s).
- **FP8 KV cache** — halves KV memory so the full 256K context fits.
- **CUDA graphs** — ~2.87× decode speedup on Blackwell.
- **Autoscale** — scales 1→4 replicas with round-robin routing.

Then point your agent at the new service URL (Part 2). See the [Part 3 README](./part3-optimize/README.md)
for toggle defaults, [`BENCHMARKS.md`](./part3-optimize/BENCHMARKS.md) for measured numbers, and
[`NOTES-incompatibilities.md`](./part3-optimize/NOTES-incompatibilities.md) for knobs that can't be combined.
