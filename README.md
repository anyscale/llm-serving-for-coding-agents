# llm-serving-for-coding-agents

Self-host an open-source coding-assistant LLM on **Anyscale + Ray Serve LLM** and use it directly from
**Claude Code, Codex, and Cursor**.

This repo serves `qwen3.6-27b`, a 27B FP8 hybrid-reasoning and tool-calling model that
[Qwen positions as comparable to Claude Opus 4.5](https://qwen.ai/blog?id=qwen3.6-27b). With
**direct streaming** enabled, one Anyscale service exposes the native APIs expected by all three agents,
without running a separate proxy.

## What This Repo Shows

| Step | Goal | Folder |
|---|---|---|
| 1 | Deploy `qwen3.6-27b` on Anyscale with Ray Serve LLM. | [`part1-deploy-naive/`](./part1-deploy-naive/) |
| 2 | Connect Claude Code, Codex, and Cursor directly to the service. | [`part2-connect-clients-direct/`](./part2-connect-clients-direct/) |
| 3 | Optimize the deployment for a 1x RTX PRO 6000 with 256K FP8 context. | [`part3-optimize/`](./part3-optimize/) |

## API Endpoints (via Direct Streaming)

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

With direct streaming enabled, the same service exposes each agent's expected API path:

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

### 5. (Optional) Deploy the cost-optimized service

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

Then update `../part2-connect-clients-direct/.env`: point `ANYSCALE_BASE_URL` to the new service URL and
relaunch the clients. See the [`Part 3 README`](./part3-optimize/README.md) for toggle defaults and the
work-hours caveat, [`BENCHMARKS.md`](./part3-optimize/notes/BENCHMARKS.md) for measured numbers, and
[`INCOMPATIBILITIES.md`](./part3-optimize/notes/INCOMPATIBILITIES.md) for knobs that can't be combined.

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
