# Part 3 — Optimize the deployment

Part 3 turns the naive Part 1 service into a multi-user, lower-latency, cost-aware deployment. It keeps the
same model id (`qwen3.6-27b`) and the same Part 2 clients — point them at this service's URL.

The defaults are measured on the target GPU. See [`notes/BENCHMARKS.md`](notes/BENCHMARKS.md) for numbers and
[`notes/INCOMPATIBILITIES.md`](notes/INCOMPATIBILITIES.md) for knobs that cannot be combined. The only
unmeasured default is autoscale `target_ongoing_requests`, which is intentionally conservative. For the
cost-reduction case, including savings vs commercial seats and token-metered API billing, see
[`notes/COST-ESTIMATE.md`](notes/COST-ESTIMATE.md).

The Part 3 image builds on `anyscale/ray-llm:2.57.0-py312-cu130`, which ships **vLLM 0.25.1** — new enough
for Claude Code's current `/v1/messages` schema on its own, so the `vllm==0.23.0` override earlier versions
of this tutorial carried is gone. The compile cache was rebuilt and re-measured on 0.25.1; the other
measurements below were taken on vLLM 0.22.0–0.23.0 (ray-llm 2.56.0) and have **not been re-run**, so see
[Revalidation on vLLM 0.25.1](notes/BENCHMARKS.md#revalidation-on-vllm-0251) for what is verified and what
is still open. Ray 2.57.0 is pre-GA as of 2026-08-10 — see [`Containerfile`](Containerfile) for the
digest-pinning note.

## What Changes

| Area | [Naive](../part1-deploy-naive/serve_qwen3_6_27b_naive.py) | [Optimized](serve_qwen3_6_27b_optimized.py) |
|---|---|---|
| GPU | 4× L4, TP=4 | 1× RTX PRO 6000 96 GB, TP=1 (`g7e.4xlarge`) |
| Weights | FP8 | NVFP4 (~22 GB; FP8 fallback retained for older FP8-capable GPUs) |
| Context / KV | 128K | Full 256K with FP8 KV |
| Model load | S3 download, ~85 s | HF download, ~85 s by default; optional RunAI Streamer S3→GPU, ~25 s |
| Compile | Recompile every cold start, ~74 s | No-MTP text path: S3 torch.compile cache, ~9 s; MTP/image graphs compile cold |
| Decode | CUDA graphs only | NVFP4 + CUDA graphs + MTP: 121 tok/s vs 65 tok/s without MTP |
| Scaling | Single replica | Autoscale 1→4, round-robin via [`service-always-on.yaml`](service-always-on.yaml) (or 0→4 via [`service-work-hours.yaml`](service-work-hours.yaml)) |

Why RTX PRO 6000 + NVFP4? The `nvidia/Qwen3.6-27B-NVFP4` checkpoint reduces weight memory to about 22 GB
(vs about 27 GB for FP8), leaving more room for long-context KV cache. NVIDIA's model card reports very
similar FP8 and NVFP4 quality across its evaluation suite. On RTX PRO 6000 (SM120), vLLM currently uses the
Marlin fallback rather than a native dense-NVFP4 kernel.

Weight precision and KV precision are separate. This service uses **NVFP4 weights with FP8 KV**. Do not set
the KV cache to `nvfp4` on RTX PRO 6000: that attention kernel is datacenter-Blackwell-only and crashes on
SM120. FP8 KV provides the measured 6.53× concurrency at full 256K context.

### Older GPU architectures

For older GPUs with native FP8 support, such as Hopper H100, use the retained
`Qwen/Qwen3.6-27B-FP8` settings in `serve_qwen3_6_27b_optimized.py`. Uncomment the three FP8 weight settings,
use a service shape for that GPU, disable the RTX PRO 6000 NVFP4 compile cache, and rebuild the cache for the
exact GPU/image/graph combination. Ampere does not provide native FP8 support, so this FP8 fallback does not
apply to A100/A10.

## Control Panel

`serve_qwen3_6_27b_optimized.py` starts with one `ENABLE_*` toggle per optimization.

| Knob | Default | Why |
|---|---|---|
| `ENABLE_FAST_MODEL_LOADING` | `False` | Optional RunAI Streamer path for cold-start-focused deployments. Leave off when spec decode is on. |
| `ENABLE_COMPILE_CACHE` | `True` | Restores the no-MTP NVFP4 text-graph cache, cutting compile from ~74.5 s to ~8.8 s (~48.5 s to ~6.0 s as re-measured on vLLM 0.25.1 — the ratio holds, the absolutes shift per vLLM version). Automatically disabled when MTP is on. |
| `ENABLE_FP8_KV_CACHE` | `True` | Halves KV memory so the full 256K context fits. |
| `ENABLE_CUDA_GRAPHS` | `True` | Biggest free win: ~2.87× decode on Blackwell. |
| `ENABLE_SPEC_DECODE` | `True` | MTP gives 121 tok/s vs 65 tok/s on the NVFP4 single-stream test. Set `ENABLE_SPEC_DECODE=0` for saturated high-concurrency traffic. |
| `ENABLE_PREFIX_ROUTING` | `False` | Optional for diverse multi-user prefixes. The single-user replay data here shares the same prompts, skills, and harness context, so round-robin is the simpler default. |

Direct streaming is always on because Part 2 connects Claude Code (`/v1/messages`), Codex (`/v1/responses`), and Cursor (`/v1/chat/completions`) to these native endpoints.
It is enabled in the service YAMLs so the Serve controller sees it at startup. If you enable prefix routing,
the service uses Ray's stock `PrefixCacheAffinityRouter`:
[ray#64328](https://github.com/ray-project/ray/pull/64328) shipped in ray-llm 2.57.0, so the router now reads
the direct-streaming request body and the `DirectStreamingPrefixCacheRouter` adapter this repo used to carry
is gone. (On ray-llm 2.56.x you still need that adapter — recover it from this repo's history.)

`accelerator_type` is intentionally omitted because `LLMConfig` rejects `RTX-PRO-6000`; the service configs
pin the `g7e` node instead.

## Files

- `serve_qwen3_6_27b_optimized.py` — optimized app and toggle panel.
- `service-always-on.yaml`, `service-work-hours.yaml`, and `schedule-work-hours-warmup.yaml` — Anyscale entry points.
- `warmup.sh` — weekday morning warmup helper for work-hours mode.
- `notes/` — benchmark data, cost estimates, and compatibility notes.
- `Containerfile` — `ray-llm:2.57.0` (vLLM 0.25.1, stock) plus `runai-model-streamer`.

## Deploy

```bash
cd part3-optimize
anyscale service deploy -f service-always-on.yaml --working-dir .
```

The default downloads `nvidia/Qwen3.6-27B-NVFP4` with the Hugging Face loader so MTP speculative decoding
can stay on. If your priority is
cold-start time instead of decode speed, use the commented fast-loading recipe in
[`serve_qwen3_6_27b_optimized.py`](serve_qwen3_6_27b_optimized.py): set
`ENABLE_FAST_MODEL_LOADING=True`, uncomment `ENABLE_SPEC_DECODE: "0"` in the service YAML, and upload the
NVFP4 weights once
(`hf download nvidia/Qwen3.6-27B-NVFP4`, then
`aws s3 sync`), and point `S3_WEIGHTS` at that `s3://...` path.

Then point your Part 2 clients at this service's URL (for Cursor, copy it from the console **Query** panel).

Before turning off spec decode for fast loading, or before enabling prefix routing, read
[`notes/BENCHMARKS.md`](notes/BENCHMARKS.md) and
[`notes/INCOMPATIBILITIES.md`](notes/INCOMPATIBILITIES.md). Spec decode trades slower cold starts for faster
decode during coding-agent turns; prefix routing is an opt-in policy for diverse multi-user prefix patterns.

## Work-Hours Mode

The work-hours service config is [`service-work-hours.yaml`](service-work-hours.yaml). It is
the same deployment with
`MIN_REPLICAS=0` and `min_nodes: 0`: after 30 idle minutes the replica scales away and the GPU node
terminates, so nights and weekends cost nothing. At ~10 h/day on weekdays that is ≈ $840/mo vs
≈ $2,900 always-on — the math is in [`notes/COST-ESTIMATE.md`](notes/COST-ESTIMATE.md).

```bash
# from part3-optimize/ (containerfile: and working_dir: resolve against the CLI's CWD)
anyscale service deploy -f service-work-hours.yaml --working-dir .
```

> **⚠ Validated 2026-07-06 with a caveat:** deploying this config, waking from zero (≈ 100 s with
> the node up, ≈ 6 min with node provisioning), and replica scale-down to zero all work — but the GPU
> **node** did not terminate in our test (the CPU router deployment can pin the only worker type),
> so the cost savings were not realized. After deploying, confirm the `g7e` instance actually
> terminates after ~35 idle minutes before counting on the work-hours numbers.

Then schedule [`warmup.sh`](warmup.sh) for 7 am on weekdays so the first developer never
waits out node provisioning, NVFP4 weight loading, compilation, and engine warmup:

- **Anyscale scheduled job** — fill in the service URL and token in
  [`schedule-work-hours-warmup.yaml`](schedule-work-hours-warmup.yaml), then (from `part3-optimize/`)
  `anyscale schedule apply -f schedule-work-hours-warmup.yaml`.
- **Any other cron** (a dev box, CI) —
  `0 7 * * 1-5 ANYSCALE_BASE_URL=... ANYSCALE_API_KEY=... bash warmup.sh`;
  it is a single curl retry loop.

Trade-off: an off-hours first request (late night, weekend) waits through the cold start — keep a
commercial API key as the off-hours fallback, or use the always-on config instead.

To cut the GPU rate another ~43%, uncomment `market_type: PREFER_SPOT` (and the cross-zone flag) in
[`service-work-hours.yaml`](service-work-hours.yaml) — spot-first with on-demand fallback;
preempted replicas recover in about the ~3-minute cold start. On-demand vs spot pricing is compared
in [`notes/COST-ESTIMATE.md`](notes/COST-ESTIMATE.md).

← Back: [Part 2](../part2-connect-clients-production/README.md) · Overview: [top-level README](../README.md)
