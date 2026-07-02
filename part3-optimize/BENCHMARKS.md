# Benchmarks

These measurements map to the `ENABLE_*` control panel in `serve_qwen3_6_27b_optimized.py`.

Unless noted, results are from 1× RTX PRO 6000 (`g7e.4xlarge`, 96 GB, SM120), TP=1, vLLM 0.22.0
(`ray-llm:2.56.0`). Prefix-routing tests used 2× of the same GPU. Anything not yet remeasured on the Pro
6000 is listed in [TODO](#todo).

Note on context length: the decode/throughput numbers were measured at `max_model_len=81920` with real
prompts up to ~73K tokens. Per-token rates are largely insensitive to the `max_model_len` cap, but treat the
production 256K-cap figures as un-benchmarked.

## Summary

Each row compares one knob off vs on, on the same hardware.

| # | Knob | Off | On | Result | Default |
|---|---|---|---|---|---|
| 1 | `ENABLE_FAST_MODEL_LOADING` | HF download, ~85 s | RunAI Streamer, ~25 s | 3.4× faster load | On |
| 2 | `ENABLE_COMPILE_CACHE` | Recompile, 74.5 s | Prebuilt cache, 8.8 s | 8.5× faster compile | On |
| 3 | `ENABLE_FP8_KV_CACHE` | bf16 KV, ~3.3× concurrency at 256K | fp8 KV, full 256K | 6.53× concurrency | On |
| 4 | `ENABLE_CUDA_GRAPHS` | Eager, 15.9 tok/s | Graphs, 45.6 tok/s | 2.87× decode | On |
| 5 | `ENABLE_SPEC_DECODE` | Base, 45.6 tok/s | MTP, 86.4 tok/s | 1.89× decode | Off |
| 6 | `ENABLE_PREFIX_ROUTING` | Round-robin, 7.79 s TTFT | Prefix, 301 s TTFT | 39× worse | Off |

Spec decode is off because it disables the fast S3 loader on vLLM 0.22.0
([vllm#42060](https://github.com/vllm-project/vllm/issues/42060)). Prefix routing is off because shared-prefix
agent traffic hotspots badly under affinity routing, and the built-in router also hangs with direct streaming on
ray-llm 2.56 ([ray#64328](https://github.com/ray-project/ray/pull/64328)). See
[`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) for combinations that cannot coexist.

## Workloads

| Input | Output | Source |
|---|---|---|
| Up to 73K tokens | ~60–209 tokens | Claude Code session replays |

## 1. Fast Model Loading

RunAI Streamer loads FP8 weights from S3 to GPU instead of using a plain Hugging Face download. It requires
`runai-model-streamer` in the image and S3 read access from the cluster.

| Loader | Cold weight load |
|---|---|
| HF download | ~85 s |
| RunAI Streamer | ~25 s |

Verdict: keep on. It cannot be combined with MTP spec decode because the drafter reload path fails with the
RunAI loader ([vllm#42060](https://github.com/vllm-project/vllm/issues/42060)). The control panel turns this
off automatically when spec decode is enabled.

## 2. Compile Cache

The service restores prebuilt inductor + AOT torch.compile caches from S3, so a fresh replica skips compile.
The cache was rebuilt and validated on 2026-06-30 for vLLM 0.22.0, RTX PRO 6000, FP8 weights + KV, TP=1,
and 256K context. Rebuild under a new S3 prefix if the image, GPU, or flags change.

| Compile path | Time |
|---|---|
| Cold compile | 74.5 s |
| Prebuilt cache restored | 8.8 s |

Verdict: keep on. Turning it off makes each scale-up compile cold.

## 3. FP8 KV Cache

`kv_cache_dtype="fp8"` roughly halves KV memory and lets the full 256K context fit on the 96 GB card.

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

CUDA graphs are enabled by leaving `enforce_eager` off. On real agent prompts with FP8 and `max_model_len`
81920:

| Config | Decode tok/s |
|---|---|
| Eager | 15.9 |
| CUDA graphs | 45.6 |

Verdict: keep on. This is the largest free speedup; turn it off only for debugging.

## 5. Speculative Decoding

MTP (`qwen3_next_mtp`) is coherent on Blackwell and improves decode from 45.6 to 86.4 tok/s on real agent
prompts. It is off by default because it requires the HF loader and gives up the ~60 s RunAI cold-start win.

`num_speculative_tokens` sweep on real session replay, concurrency 8, 60 s, MTP + fp8 KV + CUDA graphs,
`max_model_len=81920`:

| `num_speculative_tokens` | Out tok/s | Turns/s | TPOT mean | TTFT mean | vs spec=2 |
|---|---|---|---|---|---|
| 2 | 80 | 0.50 | 324.9 ms | 3.17 s | — |
| 3 | 99 | 0.72 | 264.2 ms | 2.64 s | +24% tok/s, +44% turns/s, -19% TPOT |
| 4 | 74 | 0.55 | 340.5 ms | 4.01 s | Regresses below 2 |

Verdict: keep off unless decode speed matters more than cold-start time. If you turn it on, use
`num_speculative_tokens=3`. All three values served the real ~73K-token prompts with 0 errors; the vLLM
0.19.1 long-context crash ([#40756](https://github.com/vllm-project/vllm/issues/40756)) did not reproduce
on 0.22.

Agent traffic is often prefill-heavy: 20K–74K-token prompts with short outputs. That leaves less decode for
MTP to accelerate, especially on large tool-use turns.

Also tested: KV-cache offload with LMCache still fails with `Hybrid KV cache manager ... failed to convert
the KV cache specs`.

## 6. Prefix Routing

Prefix routing sends the next turn to the replica that cached the previous prefix. On shared-prefix coding
agent traffic, it hotspots instead of helping.

| Trace | Router | TTFT mean | vs round-robin |
|---|---|---|---|
| 3 real sessions | Prefix, `imbalanced=5` | 712.9 s | ~263× worse |
| 3 real sessions | Prefix, `imbalanced=1` | 260.2 s | ~96× worse |
| 48 users + clean ~57K shared prefix | Prefix, `imbalanced=5` | 301 s | ~39× worse |

Why: Claude Code users share one dominant prefix, roughly 57K tokens of a ~70K-token request. Affinity sends
everyone to the first replica that cached it, and `imbalanced_threshold` counts queue items rather than
their prefill cost. Round-robin spreads prefills evenly while still using vLLM's automatic per-replica prefix
cache.

Verdict: keep off for shared-prefix coding-agent traffic.

Prefix routing can still help when there are many distinct, byte-stable large prefixes: multi-tenant system
prompts, per-document RAG, or per-user memory. Measure your real traffic first, especially prefix diversity
and request-cost spread.

Under direct streaming, the stock router hangs on ray-llm 2.56. If this knob is enabled, the service uses
`DirectStreamingPrefixCacheRouter` until [ray#64328](https://github.com/ray-project/ray/pull/64328) lands in
ray-llm 2.57.

## Direct Streaming

Direct streaming exposes `/v1/messages` for Claude Code and `/v1/responses` for Codex alongside
`/v1/chat/completions`. It is required for this demo and is enabled by service-level env vars in
`service_optimized.yaml`, so keep it on.

## TODO

Measure the spec-decode concurrency curve on RTX PRO 6000: sweep concurrency, compare base vs MTP, and find
where throughput peaks or KV preemption starts. Use that to tune `autoscaling_config.target_ongoing_requests`,
which is currently a conservative untested `8`.

Raw per-run JSON and load-test harnesses (`serve_bench_router_rtx.py`, `ds_bench_agent*.py`,
`gen_fair_trace.py`) live in the Anyscale build workspace, not this repo.
