# Part 1 — Deploy `qwen3.6-27b` on Anyscale (the naive way)

Goal: get a working OpenAI-compatible endpoint with the **least** configuration. It's deliberately
un-optimized — the point is to prove the model serves and to give you a baseline to optimize later.

**What "naive" means here:** 4× L4 (`g6.12xlarge`, TP=4), single replica, weights downloaded from remote storage (could also be huggingface) on every cold start,
no compile cache, no autoscaling, no speculative/routing tricks.
It works; it's just the wrong shape for a team (≈ one concurrent user, slow cold start). **We use 4× L4
here because that's the GPU shape available for the Ray Summit training session** — not because it's optimal.

## Files
- `serve_qwen3_6_27b_naive.py` — the Ray Serve LLM app (one `LLMConfig`, built with `build_openai_app`).
- `service_naive.yaml` — the Anyscale Service config (compute + image + import path).
- `client.py` — a tiny OpenAI-SDK script to sanity-check the endpoint.

## Deploy

```bash
cd part1-deploy-naive
anyscale service deploy -f service_naive.yaml
```

Wait for the service to reach **RUNNING** (`anyscale service status -n qwen3-6-27b-fp8-naive`). Then,
in the Anyscale console → **Services → qwen3-6-27b-fp8-naive → Query**, copy:
- the **base URL** (append `/v1` — e.g. `https://….s.anyscaleuserdata.com/v1`), and
- a **bearer token**.

You'll paste both into Part 2's `.env`.

> **Prefer to iterate interactively first?** Deploy into a Workspace instead of a Service:
> create a workspace on the same image/compute, `anyscale workspace_v2 push` this folder, then
> `serve run serve_qwen3_6_27b_naive:app` inside it. A Service is the right target once it works.

## Verify

```bash
# from anywhere, with the URL + token you copied:
export ANYSCALE_BASE_URL="https://YOUR-HOST.s.anyscaleuserdata.com/v1"
export ANYSCALE_API_KEY="your-token"
python client.py        # sends a chat completion, prints the reply
```

The first call after deploy/idle **cold-starts** for ~2–4 min (node provision + ~85s HF weight
download + compile). That slowness is what an optimized deployment (fast S3 loader + compile cache) removes.

## Native multi-API endpoint (direct streaming)

This deployment turns on **direct streaming**, so the one service speaks all three agent APIs natively —
no proxy needed:

| Path | Used by |
|---|---|
| `POST /v1/chat/completions` | Cursor (OpenAI) |
| `POST /v1/messages` | Claude Code (Anthropic) |
| `POST /v1/responses` | Codex (OpenAI Responses) |

Connect your agents in **[Part 2](../part2-connect-clients-direct/)** — point Claude Code, Codex, and
Cursor **directly** at the paths above, **no proxy, no `pip install`**. (A LiteLLM-gateway alternative
also exists — handy for a service *without* direct streaming — but this repo uses the direct path.)

> **How it's enabled (and a gotcha that bites a Service deploy):** direct streaming needs
> `RAY_SERVE_ENABLE_HA_PROXY=1` + `RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1` in the Ray Serve
> **controller's** environment — the controller reads the flag at startup (`build_app.py`). A
> per-deployment `runtime_env` (e.g. `LLMConfig(runtime_env=…)`) reaches only the **replicas**, not the
> controller, so setting them there makes a Service deploy fail with *"ingress_request_router requires
> HAProxy."* The fix is **service-level `env_vars`** in `service_naive.yaml` (top-level `env_vars:`),
> which Anyscale applies **cluster-wide** so the controller inherits them — **no custom image, stock
> `image_uri`**. *(Validated: all three native endpoints return 200.)*
>
> **Workspace `serve run`:** start the workspace with those two vars in its env (set them in the
> workspace's env config, or `export` them and restart Serve), then
> `serve run serve_qwen3_6_27b_naive:app`. To verify, curl the service — `/v1/messages` and
> `/v1/responses` should respond (not `404`). A `404` means direct streaming isn't active; check the
> `env_vars` in `service_naive.yaml`.

## Why this image / GPU

- **Image `anyscale/ray-llm:2.56.0-py312-cu130`** — ships vLLM 0.22.0, new enough for this model. The
  older GA `ray-llm:2.55.x` ships vLLM 0.18 (too old) and fails to load Qwen3.6.
- **4× L4 / TP=4** — chosen for **GPU availability**: 4× L4 (`g6.12xlarge`) is the shape allocated to
  attendees for the **Ray Summit hands-on session**, so the lab runs on it. It's not optimal — the FP8
  weights fit on a single bigger GPU; an optimized variant moves to **1× RTX PRO 6000 96GB** (TP=1) to
  serve the model's full 256K context in FP8.

## KV cache dtype

`serve_qwen3_6_27b_naive.py` leaves `kv_cache_dtype` at the vLLM default (bf16).

**Validated capacity** (vLLM 0.22.0, TP=4, `gpu_memory_utilization=0.85`, `max_model_len=131072`):

| Metric | Value |
|---|---|
| Available KV cache memory | **10.38 GiB / GPU** (~41.5 GiB total) |
| GPU KV cache size | **652,346 tokens** |
| Max concurrency @ 128K tokens/request | **4.98×** (raw cache capacity) |

> ⚠️ The 4.98× is the **raw KV cache capacity** (pure storage). Practical concurrency under
> real serving load will be lower due to decode-phase memory fragmentation, vLLM's safety margins,
> and PCIe bandwidth saturation between the 4 L4 GPUs (~300 GB/s each). Actual concurrent user
> capacity should be measured with real workloads.


→ Next: **[Part 2 — connect Claude Code / Codex / Cursor directly](../part2-connect-clients-direct/README.md)** (no proxy).
