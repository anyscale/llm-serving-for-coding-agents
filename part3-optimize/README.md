# Part 3 — Optimize the deployment

Re-architect the naive Part-1 service into a multi-user, low-latency, cost-aware one — **same model id
(`qwen3.6-27b`), same clients** (Part 2 keeps working; just repoint `ANYSCALE_BASE_URL` here). The main
optimization defaults are **measured, not guessed** — the numbers are in [`BENCHMARKS.md`](BENCHMARKS.md),
the incompatible-combo matrix in [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md). One exception:
the autoscale `target_ongoing_requests` is a **conservative default not yet measured on the Pro 6000**
(see the BENCHMARKS "TODO").

## What changes vs. naive

| | Naive (Part 1) | Optimized (Part 3) |
|---|---|---|
| GPU | 4× L4, TP=4 | **1× RTX PRO 6000 96 GB (Blackwell), TP=1** — `g7e.4xlarge` |
| Precision / context | FP8, 128K | **FP8, full 256K** (native 262144; 96 GB fits it — 6.53× concurrency) |
| Model load | HF download (~85 s) | **RunAI Streamer** S3→GPU (~25 s) |
| Compile | recompiles every cold start (~74 s) | **torch.compile cache** (S3) → ~9 s |
| Scaling | single replica (~1 user) | **autoscale 1→4**, round-robin (prefix routing off — it hotspots) |
| Endpoints | OpenAI chat only | **+ direct streaming** → native `/v1/messages` & `/v1/responses` |

> **Why RTX PRO 6000 + FP8 (not 4-bit)?** FP8 weights (~27 GB) + a 256K FP8 KV cache leave plenty of room
> (~6.5× concurrency at 256K) on the 96 GB card, at higher quality than 4-bit. NVFP4/4-bit also fits (~7×)
> if you need more headroom — both validated on this GPU.

## The control panel

`serve_qwen3_6_27b_optimized.py` opens with one `ENABLE_*` toggle per optimization — flip each on/off.
The measured effect of every default is in [`BENCHMARKS.md`](BENCHMARKS.md) (one section per knob).

| knob | default | why |
|---|---|---|
| `ENABLE_FAST_MODEL_LOADING` | **True** | RunAI Streamer S3→GPU, ~85 s → ~25 s cold start. Auto-off if you enable spec decode (loader conflict #42060). |
| `ENABLE_COMPILE_CACHE` | **True** | prebuilt inductor + AOT torch.compile cache from S3, ~74.5 s → ~8.8 s. |
| `ENABLE_FP8_KV_CACHE` | **True** | fp8 K/V ≈ half the KV → the full 256K fits (6.53× concurrency). |
| `ENABLE_CUDA_GRAPHS` | **True** | biggest free win, ~2.87× decode on Blackwell. Off → `enforce_eager`. |
| `ENABLE_SPEC_DECODE` | **False** | MTP is ~1.9× decode and coherent on Blackwell, but forfeits the fast S3 loader (#42060); when on it uses `num_speculative_tokens=3` (the measured sweet spot). |
| `ENABLE_PREFIX_ROUTING` | **False** | hotspots hard on shared-prefix agent traffic (up to 263× worse TTFT; see BENCHMARKS §6). Round-robin wins. |

**Direct streaming is always on (not a toggle)** — Parts 1 & 2 connect the agents to native
`/v1/messages` + `/v1/responses`. It's set at the **service level** (`service_optimized.yaml` `env_vars`,
so the Serve *controller* sees it). It conflicts with the stock prefix router, so enabling
`ENABLE_PREFIX_ROUTING` swaps in the `DirectStreamingPrefixCacheRouter` subclass (upstream fix
[ray#64328](https://github.com/ray-project/ray/pull/64328), lands in ray-llm 2.57).

`accelerator_type` is intentionally omitted (`LLMConfig`'s enum rejects `RTX-PRO-6000`); the compute
config in `service_optimized.yaml` pins the g7e node.

## Files
- `serve_qwen3_6_27b_optimized.py` — the optimized app + control panel.
- `service_optimized.yaml` — Service config (1× RTX PRO 6000 / g7e.4xlarge, autoscale 1→4).
- `direct_streaming_prefix_router.py` — subclass for prefix routing under direct streaming (only if you opt in).
- `Containerfile` — `ray-llm:2.56.0` + `runai-model-streamer` (for the S3 fast loader).
- [`BENCHMARKS.md`](BENCHMARKS.md) — measured effect of every knob + the spec-decode & prefix-routing studies.
- [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) — knobs that can't be combined, with root causes.

## Deploy

```bash
cd part3-optimize
anyscale service deploy -f service_optimized.yaml      # builds the Containerfile image, then deploys
```

The fast loader streams weights from S3: upload the FP8 weights once (`hf download Qwen/Qwen3.6-27B-FP8`
→ `aws s3 sync` to your bucket) and point `model_source` at that `s3://…` path in the serve file. To skip
S3, set `ENABLE_FAST_MODEL_LOADING=False` (plain HF download) — you still get CUDA graphs + compile cache + autoscale.

Then repoint your agents: in `../part2-connect-clients-direct/.env`, set `ANYSCALE_BASE_URL` to this
service's URL and relaunch. Nothing else changes.

> **Before flipping more knobs:** the two workload-dependent ones are already off for measured reasons —
> **spec decode** (a real ~1.9× but it forfeits the fast loader) and **prefix routing** (hotspots on
> shared-prefix agent traffic). Read [`BENCHMARKS.md`](BENCHMARKS.md) §5–§6 and
> [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md) before turning either on.

← Back: [Part 2](../part2-connect-clients-direct/README.md) · Overview: [top-level README](../README.md)
