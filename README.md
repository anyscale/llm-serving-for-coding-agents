# llm-serving-for-coding-agents

Self-host an open-source coding-assistant LLM on **Anyscale + Ray Serve LLM** and use it from
**Claude Code, Codex, and Cursor**.

This repo serves `qwen3.6-27b`, a 27B FP8 hybrid-reasoning and tool-calling model that
[Qwen positions as comparable to Claude Opus 4.5](https://qwen.ai/blog?id=qwen3.6-27b). With
**direct streaming** enabled, one Anyscale service exposes the native APIs expected by all three agents,
without running a separate proxy.

## What This Repo Shows

| Step | Goal | Folder |
|---|---|---|
| 1 | Deploy `qwen3.6-27b` on Anyscale with Ray Serve LLM. | [`part1-deploy-naive/`](./part1-deploy-naive/) |
| 2 | Connect Claude Code, Codex, and Cursor to the served model. | [workspace](./part2-connect-clients-workspace/) · [service](./part2-connect-clients-production/) |
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
- The prebuilt **public** image `us-docker.pkg.dev/anyscale-workspace-templates/workspace-templates/llm-serving-for-coding-agents:2.56.0`
  (ray-llm 2.56.0 + **vLLM 0.23.0**), pullable with no creds — Part 1 uses it so Claude Code's `/v1/messages`
  works (stock `ray-llm:2.56.0` ships vLLM 0.22.0, which rejects a `system` role inside `messages[]`).

## Quick Start

### 1. Deploy the model

From a terminal in an **Anyscale workspace** (running the image above):

```bash
cd part1-deploy-naive
serve run serve_qwen3_6_27b_naive:app     # serves at http://localhost:8000
```

Or deploy as a public Anyscale **Service** (needed for Cursor, and for sharing):
`anyscale service deploy -f service_naive.yaml`, then grab the URL + token from the console
(**Services → your service → Query**).

### 2. Connect a coding agent

Point Claude Code, Codex, or Cursor at the served model. Two paths:
[**workspace**](./part2-connect-clients-workspace/README.md) — Claude Code and Codex reach a
workspace-hosted model over an SSH tunnel (with Brave web-search MCP); and
[**service**](./part2-connect-clients-production/README.md) — all three connect to the public service URL + token.

### 3. (Optional) Deploy the optimized service

The Part 1 deployment uses 4× L4 GPUs. Part 3 optimizes the service for a single **RTX PRO 6000 96 GB**
(`g7e.4xlarge`) GPU with TP=1, FP8 weights, FP8 KV cache, full 256K context, MTP speculative decoding, and
autoscale 1→4:

```bash
cd ../part3-optimize
anyscale service deploy -f service-always-on.yaml --working-dir .
```

Measured performance gains and options include:

- **MTP speculative decoding** — default for coding-agent traffic; improves decode **1.89×**, from 45.6 tok/s to 86.4 tok/s.
- **RunAI Streamer** — optional cold-start path; reduces cold weight-load time **3.4×**, from ~85 s to ~25 s, but cannot be combined with MTP on vLLM 0.22.0.
- **Torch.compile cache** — reduces compile startup time **8.5×**, from 74.5 s to 8.8 s.
- **FP8 KV cache** — doubles 256K-context KV concurrency, from ~3.27× to 6.53×.
- **CUDA graphs** — improves decode throughput **2.87×**, from 15.9 tok/s to 45.6 tok/s.
- **Autoscale** — grows serving capacity from 1 to 4 replicas with round-robin routing.

Deployment options include:

- **Always-on config** — [`part3-optimize/service-always-on.yaml`](./part3-optimize/service-always-on.yaml)
  keeps one warm replica online for min-replica-1 service behavior.
- **Work-hours config** — [`part3-optimize/service-work-hours.yaml`](./part3-optimize/service-work-hours.yaml)
  uses min replicas 0 plus [`warmup.sh`](./part3-optimize/warmup.sh) to target
  work-hours-only GPU spend; verify the `g7e` node actually terminates after idle before relying on
  the savings.

Then point your agent at the new service URL (Part 2). See the [`Part 3 README`](./part3-optimize/README.md)
for toggle defaults and the work-hours caveat, [`BENCHMARKS.md`](./part3-optimize/notes/BENCHMARKS.md) for
measured numbers, and [`INCOMPATIBILITIES.md`](./part3-optimize/notes/INCOMPATIBILITIES.md) for knobs that
can't be combined.

## Collecting Real Claude Code Session Data for Benchmarking

The Part 3 numbers in [`BENCHMARKS.md`](./part3-optimize/notes/BENCHMARKS.md) were measured by replaying
real Claude Code sessions rather than synthetic prompts. Claude Code saves every session locally as JSONL
(one JSON object per line) at:

```
~/.claude/projects/<project>/<session-id>.jsonl
```

where `<project>` is your working-directory path with non-alphanumeric characters replaced by `-` — a
project at `/Users/alice/code/myapp` becomes `-Users-alice-code-myapp`.

Copy the sessions you want to benchmark with, then ask your coding agent to extract the per-request token
counts and replay them against the service. Transcripts contain your source code and prompts, so treat
trace files like source code.

## How Much Does It Save?

The simple planning number is **~50 registered developers per RTX PRO 6000 GPU**. The GPU can hold
roughly **24 average-length active cached sessions** at once, and the lower planning number leaves
room for long prompts, work-hour spikes, and several developers asking the model to work at the same
time.

On that sizing, always-on self-hosting is about **$58 per developer-month**:

- **Self-hosted:** about **$2,900/month per GPU**, or **$58/dev-month** at 50 developers/GPU.
- **Subscription seats:** about **$200/dev-month** for Max-20x/Ultra-class plans.
- **Token-metered usage:** about **$800/dev-month** for heavy API or enterprise-tier usage; Pylon
  measured about **$780/dev-month**.

For a 100-developer team, plan on **2+ GPUs during busy periods**. The always-on base case is about
**$5.8K/month**, compared with **$20K/month** for seats or **$80K/month** for token-metered billing.
That works out to roughly **$14.2K/month saved vs seats** and **$74.2K/month saved vs token billing**.

Work-hours mode can be cheaper if the GPU nodes really shut down outside the workday. In that case,
the target is about **$840/month per GPU**, or **$17/dev-month** at 50 developers/GPU. For the same
100-developer planning case, that is about **$18.3K/month saved vs seats** and **$78.3K/month saved
vs token billing**.

The break-even point is small because the GPU is a shared fixed cost: about **15 developers** versus
subscription seats for always-on, about **4 developers** versus seats for work-hours, and **1–4
developers** versus token-metered billing.

These savings only matter if the model is good enough for the same coding-agent work. The quality
case is that [Qwen's launch post compares Qwen3.6-27B with Claude Opus 4.5](https://qwen.ai/blog?id=qwen3.6-27b),
but teams should still validate it on their own repos and workflows. See
[`part3-optimize/notes/COST-ESTIMATE.md`](./part3-optimize/notes/COST-ESTIMATE.md) for the full
savings tables, token math, and caveats.
