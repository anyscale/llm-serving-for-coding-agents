# Part 3 — Optimize the deployment

Part 3 turns the naive Part 1 service into a multi-user, lower-latency, cost-aware deployment. It keeps the
same model id (`qwen3.6-27b`) and the same Part 2 clients; repoint `ANYSCALE_BASE_URL` to this service.

The defaults are measured on the target GPU. See [`notes/BENCHMARKS.md`](notes/BENCHMARKS.md) for numbers and
[`notes/INCOMPATIBILITIES.md`](notes/INCOMPATIBILITIES.md) for knobs that cannot be combined. The only
unmeasured default is autoscale `target_ongoing_requests`, which is intentionally conservative. For the
cost-reduction case, including savings vs commercial seats and token-metered API billing, see
[`notes/COST-ESTIMATE.md`](notes/COST-ESTIMATE.md).

## What Changes

| Area | [Naive](../part1-deploy-naive/serve_qwen3_6_27b_naive.py) | [Optimized](serve_qwen3_6_27b_optimized.py) |
|---|---|---|
| GPU | 4× L4, TP=4 | 1× RTX PRO 6000 96 GB, TP=1 (`g7e.4xlarge`) |
| Context | FP8, 128K | FP8, full 256K |
| Model load | HF download, ~85 s | HF download, ~85 s by default; optional RunAI Streamer S3→GPU, ~25 s |
| Compile | Recompile every cold start, ~74 s | S3 torch.compile cache, ~9 s |
| Decode | CUDA graphs only | CUDA graphs + MTP speculative decoding, ~1.9× faster decode |
| Scaling | Single replica | Autoscale 1→4, round-robin via [`service-always-on.yaml`](service-always-on.yaml) (or 0→4 via [`service-work-hours.yaml`](service-work-hours.yaml)) |

Why RTX PRO 6000 + FP8? FP8 weights plus an FP8 256K KV cache fit comfortably on the 96 GB card, with about
6.5× concurrency at full context and better quality than 4-bit. (Note: `nvfp4` KV cache is not usable on this
GPU — its FP4 attention kernel is datacenter-Blackwell-only and crashes on SM120; use `fp8`.)

## Control Panel

`serve_qwen3_6_27b_optimized.py` starts with one `ENABLE_*` toggle per optimization.

| Knob | Default | Why |
|---|---|---|
| `ENABLE_FAST_MODEL_LOADING` | `False` | Optional RunAI Streamer path for cold-start-focused deployments. Leave off when spec decode is on. |
| `ENABLE_COMPILE_CACHE` | `True` | Restores prebuilt torch.compile caches, cutting compile from ~74.5 s to ~8.8 s. |
| `ENABLE_FP8_KV_CACHE` | `True` | Halves KV memory so the full 256K context fits. |
| `ENABLE_CUDA_GRAPHS` | `True` | Biggest free win: ~2.87× decode on Blackwell. |
| `ENABLE_SPEC_DECODE` | `True` | MTP gives ~1.9× decode on the coding-agent replay. This is the default because agent work benefits more from lower TPOT than from a faster cold weight load. |
| `ENABLE_PREFIX_ROUTING` | `False` | Optional for diverse multi-user prefixes. The single-user replay data here shares the same prompts, skills, and harness context, so round-robin is the simpler default. |

Direct streaming is always on because Part 2 uses the native `/v1/messages` and `/v1/responses` endpoints.
It is enabled in the service YAMLs so the Serve controller sees it at startup. If you enable prefix routing,
the service uses `DirectStreamingPrefixCacheRouter` until the upstream fix
[ray#64328](https://github.com/ray-project/ray/pull/64328) lands in ray-llm 2.57.

`accelerator_type` is intentionally omitted because `LLMConfig` rejects `RTX-PRO-6000`; the service configs
pin the `g7e` node instead.

## Files

- `serve_qwen3_6_27b_optimized.py` — optimized app and toggle panel.
- `service-always-on.yaml`, `service-work-hours.yaml`, and `schedule-work-hours-warmup.yaml` — Anyscale entry points.
- `warmup.sh` — weekday morning warmup helper for work-hours mode.
- `notes/` — benchmark data, cost estimates, and compatibility notes.
- `direct_streaming_prefix_router.py` — prefix-routing adapter for direct streaming, only used if you opt in.
- `Containerfile` — `ray-llm:2.56.0` plus `runai-model-streamer`.

## Deploy

```bash
cd part3-optimize
anyscale service deploy -f service-always-on.yaml --working-dir .
```

The default uses the Hugging Face loader so MTP speculative decoding can stay on. If your priority is
cold-start time instead of decode speed, use the commented fast-loading recipe in
[`serve_qwen3_6_27b_optimized.py`](serve_qwen3_6_27b_optimized.py): set `ENABLE_SPEC_DECODE=False` and
`ENABLE_FAST_MODEL_LOADING=True`, upload the FP8 weights once (`hf download Qwen/Qwen3.6-27B-FP8`, then
`aws s3 sync`), and point `S3_WEIGHTS` at that `s3://...` path.

Then update `../part2-connect-clients-direct/.env`: set `ANYSCALE_BASE_URL` to this service URL and relaunch
the clients.

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
waits out the cold start (node provisioning + ~85 s HF weight load + ~9 s compile restore by default):

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

← Back: [Part 2](../part2-connect-clients-direct/README.md) · Overview: [top-level README](../README.md)
