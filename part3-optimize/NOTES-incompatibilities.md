# Optimization knobs that can't be combined (and what's actually worth it)

Measured on `qwen3.6-27b` (FP8), **1× RTX PRO 6000 96 GB (Blackwell, SM120, `g7e.4xlarge`)**, image
`ray-llm:2.56.0-py312-cu130` (GA, vLLM 0.22.0). **These are findings, not guesses** — each has a
measurement or a traced root cause. Read before flipping any toggle in `serve_qwen3_6_27b_optimized.py`.
Full per-knob numbers: [`BENCHMARKS.md`](BENCHMARKS.md).

## TL;DR — what to turn on

| Optimization | Default | Why |
|---|---|---|
| **CUDA graphs** (no `enforce_eager`) | ✅ **ON — biggest free win** | ~**2.87×** decode. Costs nothing. |
| **RunAI Streamer** (S3→GPU weights) | ✅ ON | ~85 s → ~25 s model load (3.4× faster cold start). |
| **torch.compile cache** (S3) | ✅ ON | ~74.5 s → ~8.8 s compile (full cold-start skip). |
| **FP8 KV cache** | ✅ ON | fits the **full 256K** context (6.53× concurrency) on the 96 GB card. |
| **Autoscale** (`max_replicas>1`) | ✅ ON | multi-user throughput. |
| **Direct streaming** (`/v1/messages`, `/v1/responses`) | ✅ ON (required) | one endpoint serves Claude Code + Codex natively — the demo needs it. Under a content-based router it needs the fix in ❷. |
| **Speculative decoding (MTP)** | ❌ OFF (opt-in) | Real **~1.89×** decode, coherent on Blackwell, but needs the HF loader → **forfeits RunAI fast-load** (❶). When on, use `num_speculative_tokens=3` (sweet spot; 4 regresses). |
| **Prefix-aware routing** | ❌ OFF | Hotspots hard on shared-prefix agent traffic — up to **263× worse TTFT**, still ~39× even with many users + a clean shared prefix. Only for *many distinct* large prefixes; validate on your own traffic (BENCHMARKS §6). |

**Bottom line:** ship CUDA graphs + RunAI Streamer + compile cache + FP8 KV + autoscale + direct streaming.
Leave **speculative decoding** *and* **prefix routing** off (both explained above).

---

## The hard incompatibilities

### ❶ RunAI Streamer ✗ MTP speculative decoding
Fast model streaming (`load_format="runai_streamer"`) and MTP spec decode (`speculative_config=
{"method":"qwen3_next_mtp"}`) **cannot both be on**. The MTP drafter reloads weights through the runai
loader, which globs `*.safetensors` in a streamer *cache* dir that holds none → engine fails at init:
`Cannot find any safetensors model weights … model_streamer/<hash>`. Known upstream bug
[vllm#42060](https://github.com/vllm-project/vllm/issues/42060); the open fix PR #42079 does **not**
resolve it (verified E2E). → Pick fast-download **or** MTP, not both. (The control panel auto-disables
`ENABLE_FAST_MODEL_LOADING` when you set `ENABLE_SPEC_DECODE=True`.)

> **Blackwell note:** MTP + CUDA graphs is **coherent** on the RTX PRO 6000 — the older `#40880`
> degenerate-output issue does **not** occur here — so the shipped config keeps CUDA graphs **on** with MTP.

### ❷ Direct streaming ✗ stock PrefixCacheAffinityRouter
Turning on direct streaming (`RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1`) *and* a content-based router makes
every request hang (HTTP 000) — the proxy never parses the raw body the direct-streaming ingress forwards.
On `ray-llm:2.56.0` that body arrives as `pending_request.kwargs["request_body"]` (not `args`), which the
stock router doesn't read — and its prefix logic is gated on non-empty `args`, so it silently falls back
to load-balancing. Filed as [ray#64326](https://github.com/ray-project/ray/issues/64326). **Fix:** use the
`DirectStreamingPrefixCacheRouter` subclass (it normalizes `kwargs["request_body"]` into `args` so the stock
prefix logic runs) — or fall back to the default `RoundRobinRouter`. **Upstream fix:**
[ray-project/ray#64328](https://github.com/ray-project/ray/pull/64328), landing in **Ray Serve LLM 2.57** —
on ≥ 2.57 the stock router works under direct streaming and the subclass can be dropped. (In this tutorial
direct streaming is **always on**, so prefix routing, when enabled, always uses the subclass.)

---

## What *does* compose (turn these on together)

RunAI Streamer + torch.compile cache + FP8 KV + CUDA graphs + autoscale + direct streaming + tool calling
(`qwen3_coder`) + reasoning parser (`qwen3`). That's the set wired **on** in `serve_qwen3_6_27b_optimized.py`.
Two big levers are deliberately **off**: `ENABLE_SPEC_DECODE` (❶ — forfeits the fast loader) and
`ENABLE_PREFIX_ROUTING` (hotspots on shared-prefix agent traffic — BENCHMARKS §6; the
`DirectStreamingPrefixCacheRouter` fix (❷) exists so it *can* run, but round-robin is the default).

Full measurements + the per-knob effect: [`BENCHMARKS.md`](BENCHMARKS.md).
