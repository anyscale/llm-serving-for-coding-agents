# Optimization knobs that can't be combined (and what's actually worth it)

Measured on `qwen3.6-27b` (FP8). Production image is `ray-llm:2.56.0-py312-cu130` (GA, vLLM 0.22.0) —
core serving + the incompatibility verdicts below were re-validated on it (2026-06-29); the spec-decode
*throughput* numbers were gathered on its nightly predecessor (vLLM 0.23) and the verdicts are unchanged.
**These are findings, not guesses** — each has a measurement or a traced root cause. Read before flipping
any toggle in `serve_qwen3_6_27b_optimized.py`.

> **Hardware note (RTX PRO 6000 re-eval, 2026-06-29):** the optimized config now targets **1× RTX PRO
> 6000 96GB (Blackwell, g7e.4xlarge)** — full **256K context in FP8** (6.53× concurrency). The matrix
> below was measured on the earlier **48 GB L40S**; the 96 GB Blackwell **flips one conclusion**:
> **speculative decoding (MTP) now WORKS and is worth it** — spec decode + CUDA graphs fits (no OOM) and
> produces **coherent** output (the #40880 garbage does NOT occur on Blackwell), at **1.89×** (86 vs 46
> tok/s). CUDA graphs give an even bigger **2.87×** here. KV offload **still fails** (architectural).
> Prefix-routing/direct-streaming are serving-layer (GPU-independent) → unchanged. See `BENCHMARKS.md`.

## TL;DR — what to turn on

| Optimization | On a single L40S? | Why |
|---|---|---|
| **CUDA graphs** (default, no `enforce_eager`) | ✅ **Yes — the biggest free win** | ~**1.9×** decode (9.8 → 18.8 tok/s). Costs nothing. |
| **RunAI Streamer** (S3→GPU weights) | ✅ Yes | ~85s → ~25s model load (3.4× faster cold start). |
| **torch.compile cache** (shared / S3) | ✅ Yes | ~137s → ~0s recompile; bring-up 288s → 76s. |
| **FP8 KV cache** | ✅ Yes | Fits **full 256K** on the 96GB RTX PRO 6000 (was 128K on a 48GB L40S). |
| **Autoscale (multi-replica)** | ✅ Yes (`max_replicas>1`) | Multi-user throughput. |
| **Prefix-aware routing** | ⚠️ **Measure first** | Hotspotted ~13× worse TTFT than round-robin on the real agent replay (load imbalance). Tune `imbalanced_threshold` + validate on diverse traffic. See **BENCHMARKS.md**. |
| **Direct streaming** (`/v1/messages`, `/v1/responses`) | ✅ Yes (with router fix) | One endpoint serves Claude Code + Codex natively. **Perf-wise:** 2.2× on long-output/high-conc, but **neutral on agent traffic** (keep it for the API surface, not as a throughput lever). See **BENCHMARKS.md**. |
| **Speculative decoding (MTP)** | L40S: ❌ no · **RTX PRO 6000: ✅ ~1.9×** | On L40S spec+graphs OOM'd & MTP hit #40880; on the 96GB Blackwell MTP+graphs fits, is **coherent**, and runs **1.89×** (needs HF loader — drops RunAI fast-load). ngram only +5%. Use **`num_speculative_tokens=3`** (sweet spot on the agent replay; 4 regresses), and MTP served real 73K-tok prompts with 0 errors on 0.22 (#40756 doesn't reproduce). See ❶❷❸ + BENCHMARKS. |

**Bottom line for 1× L40S:** turn on CUDA graphs (default) + RunAI Streamer + compile cache + FP8 KV
+ autoscale/prefix routing + direct streaming. **Leave speculative decoding off.**

---

## The hard incompatibilities

### ❶ RunAI Streamer ✗ MTP speculative decoding
Fast model streaming (`load_format="runai_streamer"`) and MTP spec decode (`speculative_config=
{"method":"qwen3_next_mtp"}`) **cannot both be on**. The MTP drafter reloads weights through the
runai loader, which globs `*.safetensors` in a streamer *cache* dir that holds none → engine fails at
init: `Cannot find any safetensors model weights … model_streamer/<hash>`. Known upstream bug
[vllm#42060](https://github.com/vllm-project/vllm/issues/42060); the open fix PR #42079 does **not**
resolve it (verified E2E). → Pick fast-download **or** MTP, not both.

### ❷ MTP speculative decoding ✗ CUDA graphs (on this Qwen3-Next arch)
MTP + CUDA graphs produces **degenerate/garbage output** on the Qwen3-Next hybrid architecture
([vllm#40880](https://github.com/vllm-project/vllm/issues/40880)). To get correct output you must set
`enforce_eager=True` — which **forfeits the ~1.9× CUDA-graph speedup** (the single biggest win). So
the headline "MTP = 2.27×" is only reachable with graphs, which aren't safe here.

### ❸ Speculative decoding + CUDA graphs ✗ a 44 GB L40S
Even setting #2 aside: vLLM does **full CUDA-graph capture over 51 batch sizes** for spec decode, and
that working set + the 28.7 GB weights **OOMs during profiling**, before the KV pool is sized.
Lowering `gpu_memory_utilization` doesn't help (it caps KV, not graph capture). So spec decode is
forced to `enforce_eager` on L40S anyway.

**Measured net (all eager, same agent prompts):** base **9.8** · ngram **10.8** (1.10×) ·
qwen3_next_mtp **20.8** (2.11×) tok/s. But base **with CUDA graphs is 18.8** — i.e. plain
graphs (18.8) beats ngram-eager (10.8) and ties MTP-eager (20.8) while keeping fast cold start and
correct output. **Conclusion: don't use spec decode on a single L40S.** To bank MTP's 2× safely you'd
need an H100 80 GB (fits MTP + graphs) once #40880 is fixed.

### ❹ Direct streaming ✗ stock PrefixCacheAffinityRouter
Turning on direct streaming (`RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1`) *and* a content-based router
makes every request hang (HTTP 000) — the proxy raises `No request with message or prompt attribute
found in pending_request.args` because the router never parses the raw body the direct-streaming
ingress forwards. Filed as [ray#64326](https://github.com/ray-project/ray/issues/64326). **Fix:** use
the `DirectStreamingPrefixCacheRouter` subclass (parses the body) — or fall back to the default
`RoundRobinRouter` under direct streaming. **Upstream fix:**
[ray-project/ray#64328](https://github.com/ray-project/ray/pull/64328), landing in **Ray Serve LLM 2.57** —
on ≥ 2.57 the stock `PrefixCacheAffinityRouter` works under direct streaming and the subclass can be dropped.
(In this tutorial direct streaming is **always on**, so prefix routing, when enabled, always uses the subclass.)

---

## What *does* compose (turn these on together)

RunAI Streamer + torch.compile cache + FP8 KV + CUDA graphs + autoscale + prefix routing
(with the router fix) + direct streaming + tool calling (`qwen3_coder`) + reasoning parser (`qwen3`).
That's exactly the set wired into `serve_qwen3_6_27b_optimized.py`. The only big lever deliberately left
**off** there is `ENABLE_SPEC_DECODE` (see ❶–❸).

Full measurements + the per-knob effect (incl. the spec-decode & prefix-routing studies): [`BENCHMARKS.md`](BENCHMARKS.md).
