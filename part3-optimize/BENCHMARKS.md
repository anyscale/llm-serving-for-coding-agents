# Measured benchmarks — one section per CONTROL PANEL knob

This maps 1:1 to the **OPTIMIZATION CONTROL PANEL** in `serve_qwen3_6_27b_optimized.py`. Each `ENABLE_*`
toggle has its measured effect and the data behind its default. **All numbers here are on the target HW:
1× RTX PRO 6000** (`g7e.4xlarge`, 96 GB, SM120), TP=1, vLLM 0.22.0 (`ray-llm:2.56.0`) — prefix routing (6)
on 2× of the same card. (Older L40S measurements have been dropped; anything not yet run on the Pro 6000
is called out in **[TODO — measure on RTX PRO 6000](#todo--measure-on-rtx-pro-6000)** below.)

## TL;DR — optimization OFF vs ON, per knob

Each knob is measured **OFF vs ON on the same card**, so each row isolates that one knob's effect. (This is
*not* the 4×L4 Part-1 stack — for that whole-stack change see [`README.md`](./README.md).)

| # | Knob | OFF (baseline) | ON (optimized) | Gain | Part-3 default |
|---|---|---|---|---|---|
| 1 | `ENABLE_FAST_MODEL_LOADING` | HF download **~85 s** load | RunAI Streamer **~25 s** | **3.4×** faster load | **ON** |
| 2 | `ENABLE_COMPILE_CACHE` | recompile **74.5 s** / fresh replica | prebuilt cache **8.8 s** | **8.5×** faster compile | **ON** |
| 3 | `ENABLE_FP8_KV_CACHE` | bf16 KV → **< 256K** (must cut context) | fp8 KV → **full 256K** | **6.53×** concurrency | **ON** |
| 4 | `ENABLE_CUDA_GRAPHS` | eager **15.9 tok/s** | graphs **45.6 tok/s** | **2.87×** decode | **ON** — biggest free win |
| 5 | `ENABLE_SPEC_DECODE` | base **46 tok/s** | MTP **86 tok/s** | **1.89×** decode † | **OFF** (opt-in) |
| 6 | `ENABLE_PREFIX_ROUTING` | round-robin **7.79 s** TTFT ✅ | prefix **301 s** TTFT ✗ | **39× worse** ‡ | **OFF** |
| — | Direct streaming (always on) | — | — | perf A/B is a **[TODO](#todo--measure-on-rtx-pro-6000)** ‡ | **ON** (API surface) |

† MTP's 1.89× decode requires the HF loader, so enabling knob 5 turns knob 1 **off** ([#42060](https://github.com/vllm-project/vllm/issues/42060)) — you trade the fast cold-start for the decode speedup. That's why it's opt-in.
‡ Two knobs are **workload-dependent, not free wins**: **prefix routing is *worse*** on shared-prefix agent traffic (ON hotspots — so the optimized choice is to keep it OFF / round-robin, §6), and **direct streaming** is on for the native `/v1/messages` + `/v1/responses` **API surface**, not as a throughput lever (its perf A/B is a Pro 6000 TODO).

For knobs **5** and **6**, the baseline setting (OFF / round-robin) is *also* the optimized default. Combos that can't coexist: [`NOTES-incompatibilities.md`](NOTES-incompatibilities.md).

## Workload shapes used below
| shape | input (ISL) | output (OSL) | source |
|---|---|---|---|
| **Decode-heavy synthetic** | ~50 tok | **500 tok** (forced) | stand-in for long code generation |
| **Real multi-turn agent** | up to **73K tok** (system + ~147 tool schemas + history) | short, **~60–209 tok** | real Claude Code session replays, turns in order |

---

## (1) `ENABLE_FAST_MODEL_LOADING` — RunAI Streamer (default **True**)

Streams the FP8 weights S3 → GPU (`load_format="runai_streamer"`) instead of a plain Hugging Face
download. Needs `runai-model-streamer` in the image + cluster S3 read.

| loader | cold weight load |
|---|---|
| HF download | ~85 s |
| **RunAI Streamer (S3)** | **~25 s** (≈3.4× faster cold start) |

**Verdict: keep on.** ⚠ Mutually exclusive with `ENABLE_SPEC_DECODE` (the MTP drafter reloads through the
runai loader and fails, [vllm#42060](https://github.com/vllm-project/vllm/issues/42060)); the control
panel auto-disables this knob when spec decode is turned on.

## (2) `ENABLE_COMPILE_CACHE` — prebuilt torch.compile cache (default **True**)

Downloads the prebuilt **inductor + AOT** torch.compile caches from S3 (via a `CloudDownloader` callback)
so a cold replica skips the entire compile. Rebuilt + validated **2026-06-30** on vLLM 0.22.0 / RTX PRO
6000 (SM120) / FP8 weights+KV / TP=1 / 256K. The S3 prefix encodes that exact stack — change the
image/GPU/flags and you must rebuild under a new prefix.

| compile path | time |
|---|---|
| cold (recompile every fresh replica) | **74.5 s** |
| **prebuilt cache (inductor + AOT restored)** | **8.8 s** (≈8.5× faster; full cold-start skip) |

**Verdict: keep on.** Off → each fresh replica compiles cold on every scale-up.

## (3) `ENABLE_FP8_KV_CACHE` — fp8 K/V (default **True**)

Stores K/V in fp8 (`kv_cache_dtype="fp8"`) — roughly half the KV memory, which is exactly what lets the
**full 256K context (262144)** fit on the 96 GB card.

| KV dtype | max context that fits | concurrency @ 256K |
|---|---|---|
| bf16 (default) | < 256K (must lower `max_model_len`) | — |
| **fp8** | **full 256K** | **6.53×** |

**Verdict: keep on.** NVFP4 KV also fits (~7× concurrency, Blackwell-only) if you need more headroom;
fp8 is higher-quality and is the default. `mxfp4` is **not** a valid `kv_cache_dtype` (it's a weight/MoE
format) — valid values in vLLM 0.22 are `{fp8, fp8_e4m3, nvfp4}`.

## (4) `ENABLE_CUDA_GRAPHS` — CUDA graph capture (default **True**)

On = no `enforce_eager`. Decode tok/s on the real agent prompts (FP8, `max_model_len` 81920):

| config | decode tok/s |
|---|---|
| base + **eager** | 15.9 |
| base + **CUDA graphs** | **45.6** |

**≈2.87× over eager — the single biggest free win. Keep on.** Only turn off (`enforce_eager=True`) to debug.

## (5) `ENABLE_SPEC_DECODE` — MTP speculative decoding (default **False**)

Decode tok/s on the real agent prompts (MTP + fp8 KV + CUDA graphs):

| config | decode tok/s | note |
|---|---|---|
| **MTP (`qwen3_next_mtp`)** | **86.4** | **1.89× over base, COHERENT** ✅ (no #40880 garbage on Blackwell) |
| ngram | 47.8 | runs, but only **+5%** on agent traffic |

**Why it's default-off:** MTP needs the HF/default loader, so it forfeits knob (1)'s fast S3 cold-start
([#42060](https://github.com/vllm-project/vllm/issues/42060)). Flip it on only when the 1.89× decode
matters more than the ~60 s faster cold start.

**`num_speculative_tokens` sweep — on the REAL session replay** (`ds_bench_agent.py` + `sessions.jsonl`, conc 8, 60 s, MTP + fp8 KV + CUDA graphs, `max_model_len` 81920):

| `num_speculative_tokens` | out tok/s | turns/s | TPOT mean | TTFT mean | vs spec=2 |
|---|---|---|---|---|---|
| 2 (old default) | 80 | 0.50 | 324.9 ms | 3.17 s | — |
| **3 (new default)** | **99** | **0.72** | **264.2 ms** | **2.64 s** | **+24% tok/s, +44% turns/s, −19% TPOT** |
| 4 | 74 | 0.55 | 340.5 ms | 4.01 s | **regresses *below* 2** |

**`spec=3` is the sweet spot; `4` regresses** (extra draft/verify cost outweighs the acceptance gain — 3 is the ceiling), so when MTP is enabled the config uses `num_speculative_tokens=3`. Bonus: all three counts served the traces' real **~73K-token prompts with 0 errors** — the long-context crash [#40756](https://github.com/vllm-project/vllm/issues/40756) (reported on vLLM 0.19.1) does **not** reproduce on 0.22 — and `spec=4` did **not** EngineDeadError (just ran slower).

**On agent traffic:** Claude Code turns are **prefill-dominated** (20–74K-token prompts, ~16–209-token outputs), so on the big tool-use turns there's little decode for MTP to accelerate — **prefix caching is the lever there, and it's orthogonal to spec decode**. The per-concurrency scaling curve and the single-card capacity cliff that should set `target_ongoing_requests` were **not** re-measured on the Pro 6000 — see the TODO below.

*Also tested, still off:* **KV-cache offload (LMCache)** still fails — `Hybrid KV cache manager … failed
to convert the KV cache specs` (Qwen3-Next hybrid-arch crash is architectural; the GPU upgrade doesn't fix it).

## (6) `ENABLE_PREFIX_ROUTING` — PrefixCacheAffinityRouter (default **False**)

Sends a session's turn N+1 to the replica that cached turn N's prefix. **Measured to hotspot
catastrophically** on shared-prefix agent traffic across a 4-experiment study (2× RTX PRO 6000, real +
synthetic Claude Code replay):

| trace | router | TTFT mean | vs round-robin |
|---|---|---|---|
| 3 real sessions | prefix `imbalanced=5` | 712.9 s | ~263× worse |
| 3 real sessions | prefix `imbalanced=1` (most aggressive) | 260.2 s | ~96× worse |
| **48 users + clean ~57K shared prefix** | **prefix `imbalanced=5`** | **301 s** | **~39× worse** |

The last row is decisive: even in prefix routing's *best case* (many users + a byte-stable shared prefix)
it still hotspots ~39× worse than round-robin. **Why:** one **dominant shared prefix** — the same system
prompt + 147 tool schemas every Claude Code user sends, ≈57K of a ~70K-token request — makes affinity
funnel *everyone* onto whichever replica cached it first; `imbalanced_threshold` is a queue-*count* signal
and can't rebalance when each queued item is a ~70K-token prefill. **Round-robin spreads the prefills
evenly *and* still reaps the shared-prefix savings via vLLM's per-replica automatic prefix cache** — it
wins on both counts.

**Verdict: keep OFF (round-robin) for shared-prefix coding-agent traffic.**

**When prefix routing IS worth it** (turn on only if *all* hold): `max_replicas > 1`; a **byte-stable**
reused prefix at token 0; **many distinct** such prefixes — multi-tenant system prompts, per-doc RAG,
per-user memory, *not* one shared prompt; comparable per-request cost; and the prefixes don't all fit in
every replica's KV. A single dominant shared prefix is the anti-pattern.

**Before flipping it, collect real traffic and measure:** (1) **prefix diversity** — # of *distinct* large
prefixes concurrently active vs replica count (many → routing can help; one dominant → round-robin wins);
(2) **per-request cost spread** — wildly variable prefill cost defeats the count-based `imbalanced_threshold`.
This study's traces were thin (3 real sessions + 48 synthetic derived from them), so it validates the
shared-prefix regime, not the multi-tenant one — re-run this A/B on your own traffic first.

**Mechanics:** under direct streaming (always on here) the *stock* router hangs; enabling this knob uses the
`DirectStreamingPrefixCacheRouter` subclass ([ray#64326](https://github.com/ray-project/ray/issues/64326) /
fix [#64328](https://github.com/ray-project/ray/pull/64328), lands in ray-llm 2.57 → then drop the subclass).

## Direct streaming (always on — not a toggle)

HAProxy streams tokens straight from each replica, bypassing the `OpenAiIngress` per-token relay. The
relay tax is paid **per output token**, so it should only matter with long outputs at high concurrency —
and should be **neutral on agent traffic** (prefill-bound, short outputs). It's on here **for its real
purpose — exposing native `/v1/messages` (Claude Code) and `/v1/responses` (Codex)** so those agents
connect without a proxy, not as a throughput lever. The **direct-vs-relay throughput A/B is a Pro 6000
TODO** (see below).

---

## TODO — measure on RTX PRO 6000

Removed the legacy L40S runs; these are the experiments to (re-)run on the Pro 6000 to close the gaps:

1. **Spec-decode concurrency curve + capacity cliff** — sweep concurrency (e.g. 1 / 4 / 8 / 16 / 32) on
   one card, base vs MTP, and find where throughput peaks / KV-preemption thrashes. Use it to set
   `autoscaling_config.target_ongoing_requests` (currently a **conservative, untested `8`** in the serve
   file — pending this measurement). Harness: `benchmarks/ds_bench_agent.py` (real replay) + a concurrency sweep.
2. **Direct streaming vs relay** — A/B the same service with `RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING` on/off
   at long-output / high-concurrency, and on the agent replay, to quantify the win (expected: sizable on
   long-output high-conc, ~neutral on agent traffic) on the Pro 6000.
3. *(optional)* **ngram vs MTP** re-confirm on Pro 6000 (expected: ngram ≪ MTP on agent traffic; ngram
   avoids the RunAI-loader conflict but barely helps).

*Raw per-run JSON + the load-test harnesses (`serve_bench_router_rtx.py`, `ds_bench_agent*.py`,
`gen_fair_trace.py`) live in the Anyscale build workspace, not this repo — ask if you want them exported.*
