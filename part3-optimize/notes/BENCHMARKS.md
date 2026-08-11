# Benchmarks

These measurements map to the `ENABLE_*` control panel in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py).

Unless noted, results are from 1× RTX PRO 6000 (`g7e.4xlarge`, 96 GB, SM120), TP=1. The current default is
`nvidia/Qwen3.6-27B-NVFP4`.

> **Except for the compile cache (§2), these numbers were measured on vLLM 0.22.0–0.23.0
> (`ray-llm:2.56.0`).** The service now runs `ray-llm:2.57.0` / vLLM 0.25.1; only knob 2 has been
> rebuilt and re-measured there — see [Revalidation on vLLM 0.25.1](#revalidation-on-vllm-0251).

Note on context length: the decode/throughput numbers were measured at `max_model_len=81920` with real
prompts up to ~73K tokens. Per-token rates are largely insensitive to the `max_model_len` cap, but treat the
production 256K-cap figures as un-benchmarked.

## Summary

Each row compares one knob off vs on, on the same hardware.

| # | Knob | Off | On | Result | Default |
|---|---|---|---|---|---|
| 0 | `ENABLE_NVFP4_WEIGHTS` | FP8, ~27 GB | NVFP4, ~22 GB | ~5 GB smaller (~19%) | On |
| 1 | `ENABLE_FAST_MODEL_LOADING` | HF download, ~85 s | RunAI Streamer, ~25 s | 3.4× faster load | Off |
| 2 | `ENABLE_COMPILE_CACHE` | Recompile, 48.5 s | Prebuilt cache, 6.0 s | 8.0× faster compile | On only without MTP |
| 3 | `ENABLE_FP8_KV_CACHE` | bf16 KV, ~3.3× concurrency at 256K | fp8 KV, full 256K | 6.53× concurrency | On |
| 4 | `ENABLE_CUDA_GRAPHS` | Eager, 15.9 tok/s | Graphs, 45.6 tok/s | 2.87× decode (FP8 measurement) | On |
| 5 | `ENABLE_SPEC_DECODE` | NVFP4 base, 65 tok/s | NVFP4 + MTP, 121 tok/s | 1.86× single-stream decode | On |

Spec decode is on by default because the tutorial targets coding-agent traffic, where lower TPOT during
multi-token generation matters more than shaving about a minute from cold weight load. Fast model loading is
kept as an opt-in because RunAI Streamer and MTP cannot currently coexist (validated through vLLM 0.23.0;
[vllm#42060](https://github.com/vllm-project/vllm/issues/42060)). Prefix routing is off by default because the
single-user replay data in this tutorial does not need replica affinity; see [Prefix Routing](#6-prefix-routing)
for when to opt in. The built-in router needs the direct-streaming fix
([ray#64328](https://github.com/ray-project/ray/pull/64328)), which shipped in ray-llm 2.57.0. See
[`INCOMPATIBILITIES.md`](INCOMPATIBILITIES.md) for combinations that cannot coexist. The MTP graph does not
use the prebuilt no-MTP compile cache, so enabling MTP automatically disables cache restoration.

## Weight Format Baseline

RTX PRO 6000 defaults to the NVIDIA 4-bit checkpoint, `nvidia/Qwen3.6-27B-NVFP4`, while retaining FP8 KV.
Weights and KV cache use independent formats:

| Component | RTX PRO 6000 default | Older FP8-capable GPU fallback |
|---|---|---|
| Weights | NVFP4 (~22 GB) | `Qwen/Qwen3.6-27B-FP8` (~27 GB) |
| KV cache | FP8 | FP8 |

NVFP4 is not half the total FP8 weight footprint because the checkpoint quantizes only linear operators
inside the transformer blocks. The vision tower and excluded modules remain at higher precision, while
per-block scales and other quantization metadata add overhead. The ~22 GB and ~27 GB figures are therefore
whole-model footprints, not just the raw bytes of the quantized matrices.

NVIDIA's model card reports closely matched FP8 and NVFP4 quality across MMLU Pro, GPQA Diamond, HLE,
τ²-Bench Telecom, MMMU Pro, SciCode, AIME 2025, AA-LCR, and IFBench. On SM120, dense NVFP4 currently runs
through vLLM's Marlin fallback rather than a native dense-NVFP4 kernel. For older architectures with native
FP8 support (for example Hopper), use the commented FP8 source settings and rebuild the compile cache for
that hardware. Ampere is not a native-FP8 fallback target.

## Workloads

| Input | Output | Source |
|---|---|---|
| Up to 73K tokens | ~60–209 tokens | Claude Code session replays |

## 1. Fast Model Loading

[RunAI Model Streamer](https://docs.ray.io/en/latest/serve/llm/user-guides/deployment-initialization.html#s3-and-runai-streamer) loads NVFP4 weights from S3 to GPU instead of using a plain Hugging Face download. It requires
`runai-model-streamer` in the image and S3 read access from the cluster.

| Loader | Cold weight load |
|---|---|
| HF download | ~85 s |
| RunAI Streamer | ~25 s |

Verdict: keep off for the default coding-agent deployment because MTP spec decode is more important for
interactive generation latency. Turn RunAI Streamer on only for cold-start-focused deployments. It cannot be
combined with MTP spec decode because the drafter reload path fails with the RunAI loader
([vllm#42060](https://github.com/vllm-project/vllm/issues/42060)); the control panel turns fast loading off
automatically when spec decode is enabled.

## 2. Compile Cache

The service restores prebuilt inductor + AOT [torch.compile](https://docs.ray.io/en/latest/serve/llm/user-guides/deployment-initialization.html#torch-compile-cache) caches from S3, so a fresh replica skips compile.
The no-MTP text-graph cache was **rebuilt and re-measured on 2026-08-10** for vLLM 0.25.1
(`ray-llm:2.57.0`), RTX PRO 6000, NVFP4 weights + FP8 KV, TP=1, and 256K context. MTP and image-heavy
requests have different graphs and compile cold. Rebuild under a new S3 prefix if the image, GPU, weight
format, or flags change.

Measured end to end on 0.25.1 — cold compile on one replica, then restore on a fresh replica:

| Compile path | Compilation | Total engine init |
|---|---|---|
| Cold compile | 48.5 s | 365.9 s |
| Prebuilt cache restored | 6.0 s | 320.3 s |

Verdict: keep on for the no-MTP text path — 8.0× on the compile step, ~45 s off engine init. The control
panel disables it automatically when MTP is enabled, so the default MTP deployment is unaffected.

Two things bite when rebuilding this cache, both learned the hard way:

- **The cache must be compiled under the same `cache_dir` it is restored into.** The AOT artifact stores
  absolute paths into the inductor cache directory. A cache compiled under a different `cache_dir` fails at
  restore with `FileNotFoundError: .../rank_0_0_dev0/backbone/artifact_compile_range_...`, and vLLM does
  **not** fall back to a cold compile — the engine dies and the service goes UNHEALTHY. The serve file
  therefore pins `cache_dir` across the whole no-MTP path, not just when downloading.
- **The old 0.23.0 cache is not merely stale, it is structurally different.** vLLM 0.25.1 renamed the
  per-rank subdir from `rank_0_0` to `rank_0_0_dev0`, and the `torch_aot_compile/<hash>` directory name
  changed too (`d2e025be…` → `6da065b9…`), so `COMPILE_CACHE_AOT_DIR` has to be re-read off the replica.

Note the cold path got cheaper on its own: 48.5 s here vs the 74.5 s measured on 0.22.0/0.23.0. The cache
still pays for itself, but the absolute saving is smaller than on the older stack.

## 3. FP8 KV Cache

`kv_cache_dtype="fp8"` roughly halves KV memory and lets the full 256K context fit on the 96 GB card.
See [Quantized KV Cache — vLLM docs](https://docs.vllm.ai/en/stable/features/quantization/quantized_kvcache/) for supported formats and calibration options.

| KV dtype | Max context that fits | Concurrency at 256K |
|---|---|---|
| bf16 | Full 256K | ~3.27× |
| fp8 | Full 256K | 6.53× |

Verdict: keep on — `fp8` is the right KV dtype here. Do **not** use `nvfp4` for the KV cache on this GPU:
vLLM accepts the flag, but the FP4 attention kernel is sm_100/sm_103-only (datacenter Blackwell), so on the
RTX PRO 6000 (SM120) it starts cleanly and then **crashes on the first request**
([vllm#43562](https://github.com/vllm-project/vllm/issues/43562)). Valid KV dtypes on SM120 are `fp8`
(= `fp8_e4m3`) and `fp8_e5m2`. (`mxfp4` is a weight-quantization format, not a KV-cache dtype at all.)

## 4. CUDA Graphs

[CUDA graphs](https://docs.vllm.ai/en/latest/design/cuda_graphs/) are enabled by leaving `enforce_eager` off.
The following older measurement used FP8 weights and real agent prompts with `max_model_len=81920`:

| Config | Decode tok/s |
|---|---|
| Eager | 15.9 |
| CUDA graphs | 45.6 |

Verdict: keep on. This is the largest free speedup; turn it off only for debugging.

## 5. Speculative Decoding

[MTP (Multi-Token Prediction)](https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/)
(`qwen3_next_mtp`) is coherent with the NVFP4 checkpoint on Blackwell and improves single-stream decode
from 65 to 121 tok/s. It is on by default because coding-agent sessions benefit more from lower TPOT during
active work than from the ~60 s RunAI cold-start win.

`num_speculative_tokens` sweep on real session replay, concurrency 8, 60 s, MTP + fp8 KV + CUDA graphs,
`max_model_len=81920`:

| `num_speculative_tokens` | Out tok/s | Turns/s | TPOT mean | TTFT mean | vs spec=2 |
|---|---|---|---|---|---|
| 2 | 80 | 0.50 | 324.9 ms | 3.17 s | — |
| 3 | 99 | 0.72 | 264.2 ms | 2.64 s | +24% tok/s, +44% turns/s, -19% TPOT |
| 4 | 74 | 0.55 | 340.5 ms | 4.01 s | Regresses below 2 |

Verdict: keep on for low-to-moderate-concurrency coding-agent use cases and use
`num_speculative_tokens=3`. Under saturated high concurrency, draft/verify overhead can reduce aggregate
throughput; set `ENABLE_SPEC_DECODE=0` or evaluate dynamic speculative decoding. All three values served the
real ~73K-token prompts with 0 errors; the vLLM
0.19.1 long-context crash ([#40756](https://github.com/vllm-project/vllm/issues/40756)) did not reproduce
on 0.22. The sweep has not been re-run on 0.25.1.

Agent traffic is often prefill-heavy: 20K–74K-token prompts with short outputs. That means MTP will not erase
prefill latency on large tool-use turns, but it still improves TPOT and turns/s on the measured coding-agent
replay.

Also tested: KV-cache offload with LMCache still fails with `Hybrid KV cache manager ... failed to convert
the KV cache specs`.

## 6. Prefix Routing

[Prefix-aware routing](https://docs.ray.io/en/latest/serve/llm/user-guides/prefix-aware-routing.html) sends the
next turn to the replica that cached the previous prefix. It is an opt-in setting here because the benchmark
trace is single-user coding-agent data: most requests share the same system prompts, skills, and harness
context, so each replica's local vLLM prefix cache sees similar reusable prefixes over time. For that traffic,
round-robin is the simpler default and avoids coupling cache affinity to replica load.

Prefix routing becomes more useful when the service handles many users with diverse byte-stable prefixes:
different system prompts, skill sets, memory blocks, RAG documents, or agent harnesses. In that case, tune
`imbalanced_threshold` and `match_rate_threshold` against real traffic. The goal is to improve prefix-cache
reuse without sending too much work to one replica just because it already has a similar prefix cached.

Under direct streaming, the stock router hung on ray-llm 2.56, and this repo shipped a
`DirectStreamingPrefixCacheRouter` adapter for it.
[ray#64328](https://github.com/ray-project/ray/pull/64328) shipped in ray-llm 2.57.0, so the service now
wires up the stock `PrefixCacheAffinityRouter` and the adapter has been removed. The fix is in the release;
this repo has not exercised prefix routing end to end on 2.57.0 (the knob stays off by default).

## Direct Streaming

[Direct streaming](https://docs.ray.io/en/latest/serve/llm/user-guides/direct-streaming.html) exposes `/v1/messages` for Claude Code and `/v1/responses` for Codex alongside
`/v1/chat/completions`. It is required for this demo and is enabled by service-level env vars in
the Part 3 service YAMLs, so keep it on.

## Revalidation on vLLM 0.25.1

The upgrade to `ray-llm:2.57.0` / vLLM 0.25.1 was made for the Claude Code `/v1/messages` schema and the
direct-streaming router fix. Only some of it has been re-measured there.

**Verified on 0.25.1 (2026-08-10):**

| What | Result |
|---|---|
| Compile cache (knob 2) | Rebuilt and re-measured: 48.5 s → 6.0 s. See [§2](#2-compile-cache). |
| Service health, both parts | Part 1 (4× L4) and Part 3 (1× RTX PRO 6000) both reach RUNNING and serve. |
| `/v1/messages`, `/v1/responses`, `/v1/chat/completions` | All 200, including a `system` role inside `messages[]` — the payload vLLM 0.22.0 rejected. |
| NVFP4 + MTP default path | Engine starts and serves; `g7e.4xlarge` reports `1xRTX-PRO-6000-96G`. |

**Still open — treat as unverified until re-run on 0.25.1:**

| What | Why it can move on 0.25.1 |
|---|---|
| NVFP4 decode throughput | Dense NVFP4 runs the Marlin fallback; kernel selection can change between vLLM minors, which moves throughput in either direction. The engine works; the *numbers* are 0.23.0's. |
| Image input | Verified on 0.23.0 only. The multimodal path and `mm_processor_kwargs` handling change often. |
| MTP spec decode | 65 → 121 tok/s and the `num_speculative_tokens` sweep are 0.23.0 numbers. |
| CUDA graphs, FP8 KV | Expected to hold, but the 2.87× and 6.53× figures are older FP8-weight measurements. |
| RunAI Streamer + MTP | Still expected to conflict ([vllm#42060](https://github.com/vllm-project/vllm/issues/42060) is open), but the failure was reproduced on ≤ 0.23.0. |
| Prefix routing | [ray#64328](https://github.com/ray-project/ray/pull/64328) is in the 2.57.0 branch; the end-to-end path has not been exercised here. |

Re-run the knob sweeps against the same Claude Code session replay so the numbers stay comparable, then
drop this section.
