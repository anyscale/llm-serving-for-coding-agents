# Part 3 — Optimize the deployment

Part 3 turns the naive Part 1 service into a multi-user, lower-latency, cost-aware deployment. It keeps the
same model id (`qwen3.6-27b`) and the same Part 2 clients — point them at this service's URL.

The defaults are measured on the target GPU. See [`BENCHMARKS.md`](BENCHMARKS.md) for numbers and
[`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) for knobs that cannot be combined. The only
unmeasured default is autoscale `target_ongoing_requests`, which is intentionally conservative.

## What Changes

| Area | [Naive](../part1-deploy-naive/serve_qwen3_6_27b_naive.py) | [Optimized](serve_qwen3_6_27b_optimized.py) |
|---|---|---|
| GPU | 4× L4, TP=4 | 1× RTX PRO 6000 96 GB, TP=1 (`g7e.4xlarge`) |
| Context | FP8, 128K | FP8, full 256K |
| Model load | HF download, ~85 s | RunAI Streamer S3→GPU, ~25 s |
| Compile | Recompile every cold start, ~74 s | S3 torch.compile cache, ~9 s |
| Scaling | Single replica | Autoscale 1→4, round-robin |

Why RTX PRO 6000 + FP8? FP8 weights plus an FP8 256K KV cache fit comfortably on the 96 GB card, with about
6.5× concurrency at full context and better quality than 4-bit. (Note: `nvfp4` KV cache is not usable on this
GPU — its FP4 attention kernel is datacenter-Blackwell-only and crashes on SM120; use `fp8`.)

## Control Panel

`serve_qwen3_6_27b_optimized.py` starts with one `ENABLE_*` toggle per optimization.

| Knob | Default | Why |
|---|---|---|
| `ENABLE_FAST_MODEL_LOADING` | `True` | Streams weights from S3, cutting load time from ~85 s to ~25 s. Auto-disabled when spec decode is on. |
| `ENABLE_COMPILE_CACHE` | `True` | Restores prebuilt torch.compile caches, cutting compile from ~74.5 s to ~8.8 s. |
| `ENABLE_FP8_KV_CACHE` | `True` | Halves KV memory so the full 256K context fits. |
| `ENABLE_CUDA_GRAPHS` | `True` | Biggest free win: ~2.87× decode on Blackwell. |
| `ENABLE_SPEC_DECODE` | `False` | MTP gives ~1.9× decode, but loses the fast S3 loader. Opt in only if decode speed matters more than cold start. |
| `ENABLE_PREFIX_ROUTING` | `False` | Hotspots badly on shared-prefix agent traffic. Round-robin is faster for this workload. |

Direct streaming is always on because Part 2 uses the native `/v1/messages` (Claude Code) and `/v1/chat/completions` (Cursor) endpoints.
It is enabled in `service_optimized.yaml` so the Serve controller sees it at startup. If you enable prefix
routing, the service uses `DirectStreamingPrefixCacheRouter` until the upstream fix
[ray#64328](https://github.com/ray-project/ray/pull/64328) lands in ray-llm 2.57.

`accelerator_type` is intentionally omitted because `LLMConfig` rejects `RTX-PRO-6000`; the compute config
in `service_optimized.yaml` pins the `g7e` node instead.

## Files

- `serve_qwen3_6_27b_optimized.py` — optimized app and toggle panel.
- `service_optimized.yaml` — service config for 1× RTX PRO 6000 with autoscale 1→4.
- `direct_streaming_prefix_router.py` — prefix-routing adapter for direct streaming, only used if you opt in.
- `Containerfile` — `ray-llm:2.56.0` plus `runai-model-streamer`.
- [`BENCHMARKS.md`](BENCHMARKS.md) — measured effect of each knob.
- [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) — incompatibilities and root causes.

## Deploy

```bash
cd part3-optimize
anyscale service deploy -f service_optimized.yaml
```

**Stage the artifacts first** (once per cloud). The app reads the FP8 weights and the torch.compile caches
from `$ANYSCALE_ARTIFACT_STORAGE/qwen-3.6/` — the cloud's
[artifact storage](https://docs.anyscale.com/resources/environment-variables). Upload the weights there
(`hf download Qwen/Qwen3.6-27B-FP8`, then `aws s3 sync … "$ANYSCALE_ARTIFACT_STORAGE/qwen-3.6/Qwen3.6-27B-FP8/"`),
plus the prebuilt compile caches under `…/qwen-3.6/compiled-cache[-aot]/`. To skip S3 loading, set
`ENABLE_FAST_MODEL_LOADING=False` (the other optimizations still work).

Then point your Part 2 clients at this service's URL (for Cursor, copy it from the console **Query** panel).

Before turning on spec decode or prefix routing, read [`BENCHMARKS.md`](BENCHMARKS.md) and
[`NOTES-incompatibilities.md`](NOTES-incompatibilities.md). Both are off by default for measured reasons.

← Back: [Part 2](../part2-connect-clients-direct/README.md) · Overview: [top-level README](../README.md)
