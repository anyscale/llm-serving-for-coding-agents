# Benchmarks

These measurements map to the `ENABLE_*` control panel in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py).

Unless noted, results are from 1× RTX PRO 6000 (`g7e.4xlarge`, 96 GB, SM120), TP=1, vLLM 0.22.0
(`ray-llm:2.56.0`). Anything not yet remeasured on the Pro 6000 is listed in [TODO](#todo).

Note on context length: the decode/throughput numbers were measured at `max_model_len=81920` with real
prompts up to ~73K tokens. Per-token rates are largely insensitive to the `max_model_len` cap, but treat the
production 256K-cap figures as un-benchmarked.

## Summary

**The default deployment is NVFP4 without MTP** (knob 7, [§7](#7-nvfp4-weights-enable_nvfp4--the-multi-user-default)) — it wins the multi-user workload this service targets. The rows below are the per-knob effects on the FP8 baseline (now the single-user alternative); §7 has the NVFP4-vs-FP8 and MTP-vs-no-MTP comparison that sets the default.

| # | Knob | Off | On | Result | Default |
|---|---|---|---|---|---|
| 1 | `ENABLE_FAST_MODEL_LOADING` | HF download, ~85 s | RunAI Streamer, ~25 s | 3.4× faster load | Off |
| 2 | `ENABLE_COMPILE_CACHE` | Recompile, 74.5 s | Prebuilt cache, 8.8 s | 8.5× faster compile | On |
| 3 | `ENABLE_FP8_KV_CACHE` | bf16 KV, ~3.3× concurrency at 256K | fp8 KV, full 256K | 6.53× concurrency | On |
| 4 | `ENABLE_CUDA_GRAPHS` | Eager, 15.9 tok/s | Graphs, 45.6 tok/s | 2.87× decode | On |
| 5 | `ENABLE_SPEC_DECODE` | Base, 45.6 tok/s | MTP, 86.4 tok/s | 1.89× single-stream decode | On (FP8) / off (NVFP4) |
| 7 | `ENABLE_NVFP4` | FP8 weights | NVFP4 4-bit weights | +53% multi-user out tok/s (§7) | On (multi-user default) |

MTP (spec decode) is the biggest single-stream lever, but it **hurts multi-user throughput** (draft/verify
overhead once the batch saturates the GPU — see §7), so it is on for the FP8 single-user path and **off for the
NVFP4 multi-user default**; set `ENABLE_SPEC_DECODE=1` for the single-user NVFP4+MTP config. Fast model loading is
an opt-in because RunAI Streamer and MTP cannot coexist on vLLM 0.22.0
([vllm#42060](https://github.com/vllm-project/vllm/issues/42060)); NVFP4 loads from HF regardless. Prefix routing
is off by default because the single-user replay data does not need replica affinity; see
[Prefix Routing](#6-prefix-routing), and the built-in router needs the ray-llm 2.57 direct-streaming fix
([ray#64328](https://github.com/ray-project/ray/pull/64328)). See
[`INCOMPATIBILITIES.md`](INCOMPATIBILITIES.md) for combinations that cannot coexist.

## Workloads

| Input | Output | Source |
|---|---|---|
| Up to 73K tokens | ~60–209 tokens | Claude Code session replays |

## 1. Fast Model Loading

[RunAI Model Streamer](https://docs.ray.io/en/latest/serve/llm/user-guides/deployment-initialization.html#s3-and-runai-streamer) loads FP8 weights from S3 to GPU instead of using a plain Hugging Face download. It requires
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
The cache was rebuilt and validated on 2026-06-30 for vLLM 0.22.0, RTX PRO 6000, FP8 weights + KV, TP=1,
and 256K context. Rebuild under a new S3 prefix if the image, GPU, or flags change.

| Compile path | Time |
|---|---|
| Cold compile | 74.5 s |
| Prebuilt cache restored | 8.8 s |

Verdict: keep on. Turning it off makes each scale-up compile cold.

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

[CUDA graphs](https://docs.vllm.ai/en/latest/design/cuda_graphs/) are enabled by leaving `enforce_eager` off. On real agent prompts with FP8 and `max_model_len`
81920:

| Config | Decode tok/s |
|---|---|
| Eager | 15.9 |
| CUDA graphs | 45.6 |

Verdict: keep on. This is the largest free speedup; turn it off only for debugging.

## 5. Speculative Decoding

[MTP (Multi-Token Prediction)](https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/) (`qwen3_next_mtp`) is coherent on Blackwell and improves decode from 45.6 to 86.4 tok/s on real agent
prompts. It is on by default **for the FP8 single-user path**, where lower TPOT during active work matters more
than the ~60 s RunAI cold-start win. **Note the concurrency crossover:** MTP's benefit shrinks as the batch fills
and reverses under real multi-user load — [§7](#7-nvfp4-weights-enable_nvfp4--the-multi-user-default) shows it
*lowers* throughput at C=16–32, which is why the NVFP4 multi-user default turns MTP off.

`num_speculative_tokens` sweep on real session replay, concurrency 8, 60 s, MTP + fp8 KV + CUDA graphs,
`max_model_len=81920`:

| `num_speculative_tokens` | Out tok/s | Turns/s | TPOT mean | TTFT mean | vs spec=2 |
|---|---|---|---|---|---|
| 2 | 80 | 0.50 | 324.9 ms | 3.17 s | — |
| 3 | 99 | 0.72 | 264.2 ms | 2.64 s | +24% tok/s, +44% turns/s, -19% TPOT |
| 4 | 74 | 0.55 | 340.5 ms | 4.01 s | Regresses below 2 |

Verdict: keep on for coding-agent use cases and use `num_speculative_tokens=3`. All three values served the
real ~73K-token prompts with 0 errors; the vLLM
0.19.1 long-context crash ([#40756](https://github.com/vllm-project/vllm/issues/40756)) did not reproduce
on 0.22.

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

Under direct streaming, the stock router hangs on ray-llm 2.56. If this knob is enabled, the service uses
`DirectStreamingPrefixCacheRouter` until [ray#64328](https://github.com/ray-project/ray/pull/64328) lands in
ray-llm 2.57.

## 7. NVFP4 Weights (`ENABLE_NVFP4`) — the multi-user default

Serve the 4-bit NVFP4 checkpoint ([`nvidia/Qwen3.6-27B-NVFP4`](https://huggingface.co/nvidia/Qwen3.6-27B-NVFP4))
instead of FP8. This is a **weight** format (distinct from the `nvfp4` *KV-cache* dtype in §3, which crashes on
SM120). Requires the `ray-llm:2.56.1-py312-cu130` image ([`Containerfile.nvfp4`](../Containerfile.nvfp4)).
NVFP4 weights are ~22 GB vs FP8 ~27 GB (more KV headroom). Note SM120 has no dense-NVFP4 kernel in vLLM yet
([vllm#31085](https://github.com/vllm-project/vllm/issues/31085),
[#33417](https://github.com/vllm-project/vllm/pull/33417) cover MoE only), so weights run the **Marlin**
weight-only dequant path (log: `marlin.py: Your GPU does not have native support for FP4 computation`) — the win
here is memory-bandwidth per token, not native FP4 math.

The checkpoint **does carry the MTP drafter** (`config.json`: `mtp_num_hidden_layers=1`, quant `ignore: [mtp*]`),
so NVFP4+MTP runs — it just isn't the multi-user default (see below).

Measured 2026-07-23 on 1× RTX PRO 6000 (`g7e.4xlarge`), **vLLM 0.23.0** (`ray-llm:2.56.1`), fp8 KV + CUDA graphs.
Two harnesses (the `ds_bench_agent*` / results JSON live in the build workspace, not this repo — see [TODO](#todo)):
a single-stream decode microbench (fixed prompt, 256 out tok — the FP8-no-MTP row reproduces the ~46 tok/s in
`results_rtx_base_graph.json`, calibrating it) and the fair multi-user replay (`ds_bench_agent_fair.py` on
`sessions_fair.jsonl`, 48 users, shared 7K prefix, warmed).

**Single-stream decode (one user / low concurrency):**

| Config | Decode tok/s |
|---|---|
| **NVFP4 + MTP** | **121** |
| FP8 + MTP | 86 |
| NVFP4 (no MTP) | 65 |
| FP8 (no MTP) | 46 |

**Fair multi-user throughput (aggregate out tok/s):**

| Config | C=8 | C=16 | C=32 | C=16 TPOT |
|---|---|---|---|---|
| **NVFP4 (no MTP)** | 232 | **244** | **276** | **414 ms** |
| NVFP4 + MTP | 205 | 165 | 237 | 793 ms |
| FP8 + MTP | — | 160 | 269 | 946 ms |

The two regimes want opposite MTP settings. At low concurrency the GPU is idle, so **both** NVFP4's 4-bit weight
bandwidth **and** MTP's speculative decoding help → NVFP4+MTP is fastest single-stream (121 tok/s, +40% over
FP8+MTP). Under multi-user load the batch already saturates the GPU, so MTP's draft+verify overhead becomes pure
cost: adding MTP to NVFP4 *drops* C=16 throughput 244→165 and nearly doubles TPOT. FP8+MTP shows the same MTP
drag (160 @C16). So **MTP is the lever that flips with concurrency**, independent of weight format.

**Verdict:**
- **Multi-user (this service's default): NVFP4 without MTP** — +53% out tok/s and ~half the TTFT/TPOT vs FP8+MTP
  at C=16. Shipped as [`service-nvfp4.yaml`](../service-nvfp4.yaml) with a prebuilt compile cache (fast scale-up).
- **Single-user / latency: NVFP4 + MTP** — 121 tok/s single-stream, the fastest config; set `ENABLE_SPEC_DECODE=1`
  ([`service-nvfp4-mtp.yaml`](../service-nvfp4-mtp.yaml)). Cold-compiles (its graph differs from the cached no-MTP one).
- FP8 + MTP remains the single-user alternative on the stock `ray-llm:2.56.0` image (no cu13 requirement).

**Correctness:** all configs produce coherent output + structured `qwen3_coder` tool calls; no NVFP4 garbling.

**Caveat:** the fair replay has 48 users / short windows — treat the absolute numbers as indicative and the
*ranking* as the takeaway. Re-evaluate when native dense-NVFP4 SM120 kernels land (they'd lift NVFP4 further).

## Direct Streaming

[Direct streaming](https://docs.ray.io/en/latest/serve/llm/user-guides/direct-streaming.html) exposes `/v1/messages` for Claude Code and `/v1/responses` for Codex alongside
`/v1/chat/completions`. It is required for this demo and is enabled by service-level env vars in
the Part 3 service YAMLs, so keep it on.

## TODO

Measure the spec-decode concurrency curve on RTX PRO 6000: sweep concurrency, compare base vs MTP, and find
where throughput peaks or KV preemption starts. Use that to tune `autoscaling_config.target_ongoing_requests`,
which is currently a conservative untested `8`.

Raw per-run JSON and load-test harnesses (`serve_bench_router_rtx.py`, `ds_bench_agent*.py`,
`gen_fair_trace.py`) live in the Anyscale build workspace, not this repo.
