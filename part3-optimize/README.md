# Part 3 — Optimize the deployment

Part 3 turns the naive Part 1 service into a multi-user, lower-latency, cost-aware deployment. It keeps the
same model id (`qwen3.6-27b`) and the same Part 2 clients; repoint `ANYSCALE_BASE_URL` to this service.

The defaults are measured on the target GPU. See [`BENCHMARKS.md`](BENCHMARKS.md) for numbers and
[`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) for knobs that cannot be combined. The only
unmeasured default is autoscale `target_ongoing_requests`, which is intentionally conservative. For the
cost-reduction case, including savings vs commercial seats and token-metered API billing, see
[`COST-ESTIMATE.md`](COST-ESTIMATE.md).

## What Changes

| Area | [Naive](../part1-deploy-naive/serve_qwen3_6_27b_naive.py) | [Optimized](serve_qwen3_6_27b_optimized.py) |
|---|---|---|
| GPU | 4× L4, TP=4 | 1× RTX PRO 6000 96 GB, TP=1 (`g7e.4xlarge`) |
| Context | FP8, 128K | FP8, full 256K |
| Model load | HF download, ~85 s | RunAI Streamer S3→GPU, ~25 s |
| Compile | Recompile every cold start, ~74 s | S3 torch.compile cache, ~9 s |
| Scaling | Single replica | Autoscale 1→4, round-robin (or 0→4 with [`scale-to-zero/`](scale-to-zero/)) |

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
| `ENABLE_PREFIX_ROUTING` | `False` | Optional for diverse multi-user prefixes. The single-user replay data here shares the same prompts, skills, and harness context, so round-robin is the simpler default. |

Direct streaming is always on because Part 2 uses the native `/v1/messages` and `/v1/responses` endpoints.
It is enabled in `service_optimized.yaml` so the Serve controller sees it at startup. If you enable prefix
routing, the service uses `DirectStreamingPrefixCacheRouter` until the upstream fix
[ray#64328](https://github.com/ray-project/ray/pull/64328) lands in ray-llm 2.57.

`accelerator_type` is intentionally omitted because `LLMConfig` rejects `RTX-PRO-6000`; the compute config
in `service_optimized.yaml` pins the `g7e` node instead.

## Files

- `serve_qwen3_6_27b_optimized.py` — optimized app and toggle panel.
- `service_optimized.yaml` — service config for 1× RTX PRO 6000 with autoscale 1→4 (always-on).
- `scale-to-zero/` — scale-to-zero variant: `service_scale_to_zero.yaml` (autoscale 0→4) plus the
  weekday-morning warm-up (`warmup.sh`, `warmup_schedule.yaml`).
- `direct_streaming_prefix_router.py` — prefix-routing adapter for direct streaming, only used if you opt in.
- `Containerfile` — `ray-llm:2.56.0` plus `runai-model-streamer`.
- [`BENCHMARKS.md`](BENCHMARKS.md) — measured effect of each knob.
- [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) — incompatibilities and root causes.
- [`COST-ESTIMATE.md`](COST-ESTIMATE.md) — savings estimate vs commercial seats and token-metered API billing.

## Deploy

```bash
cd part3-optimize
anyscale service deploy -f service_optimized.yaml
```

For fast loading, upload the FP8 weights once (`hf download Qwen/Qwen3.6-27B-FP8`, then `aws s3 sync`) and
point `model_source` at that `s3://...` path. To skip S3, set `ENABLE_FAST_MODEL_LOADING=False`; the other
optimizations still work.

Then update `../part2-connect-clients-direct/.env`: set `ANYSCALE_BASE_URL` to this service URL and relaunch
the clients.

Before turning on spec decode or prefix routing, read [`BENCHMARKS.md`](BENCHMARKS.md) and
[`NOTES-incompatibilities.md`](NOTES-incompatibilities.md). Spec decode trades faster decode for slower cold
starts; prefix routing is an opt-in policy for diverse multi-user prefix patterns.

## Scale to Zero Outside Work Hours

Everything for this mode lives in [`scale-to-zero/`](scale-to-zero/).
[`service_scale_to_zero.yaml`](scale-to-zero/service_scale_to_zero.yaml) is the same deployment with
`MIN_REPLICAS=0` and `min_nodes: 0`: after 30 idle minutes the replica scales away and the GPU node
terminates, so nights and weekends cost nothing. At ~10 h/day on weekdays that is ≈ $840/mo vs
≈ $2,900 always-on — the math is in [`COST-ESTIMATE.md`](COST-ESTIMATE.md).

```bash
# from part3-optimize/ (containerfile: and working_dir: resolve against the CLI's CWD)
anyscale service deploy -f scale-to-zero/service_scale_to_zero.yaml --working-dir .
```

> **⚠ Validated 2026-07-06 with a caveat:** deploying this config, waking from zero (≈ 100 s with
> the node up, ≈ 6 min with node provisioning), and replica scale-to-zero all work — but the GPU
> **node** did not terminate in our test (the CPU router deployment can pin the only worker type),
> so the cost savings were not realized. After deploying, confirm the `g7e` instance actually
> terminates after ~35 idle minutes before counting on the work-hours numbers.

Then schedule [`warmup.sh`](scale-to-zero/warmup.sh) for 7 am on weekdays so the first developer never
waits out the cold start (node provisioning + ~25 s weight load + ~9 s compile restore):

- **Anyscale scheduled job** — fill in the service URL and token in
  [`warmup_schedule.yaml`](scale-to-zero/warmup_schedule.yaml), then (from `part3-optimize/`)
  `anyscale schedule apply -f scale-to-zero/warmup_schedule.yaml`.
- **Any other cron** (a dev box, CI) —
  `0 7 * * 1-5 ANYSCALE_BASE_URL=... ANYSCALE_API_KEY=... scale-to-zero/warmup.sh`;
  it is a single curl retry loop.

Trade-off: an off-hours first request (late night, weekend) waits through the cold start — keep a
commercial API key as the off-hours fallback, or use the always-on `service_optimized.yaml` instead.

To cut the GPU rate another ~43%, uncomment `market_type: PREFER_SPOT` (and the cross-zone flag) in
[`service_scale_to_zero.yaml`](scale-to-zero/service_scale_to_zero.yaml) — spot-first with on-demand fallback;
preempted replicas recover in about the ~3-minute cold start. On-demand vs spot pricing is compared
in [`COST-ESTIMATE.md`](COST-ESTIMATE.md).

← Back: [Part 2](../part2-connect-clients-direct/README.md) · Overview: [top-level README](../README.md)
