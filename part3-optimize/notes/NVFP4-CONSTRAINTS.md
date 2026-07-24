# NVFP4 on the RTX PRO 6000 (SM120): weight & KV-cache constraints

NVFP4 (NVIDIA's 4-bit floating-point format) is appealing for coding-agent serving: smaller weights →
more KV headroom, and — on datacenter Blackwell — faster matmuls. This note records what actually works
on the **Part 3 GPU, the RTX PRO 6000 (Blackwell, compute capability SM120, AWS `g7e.4xlarge`)**, and why.
There are two independent axes — **weights** and the **KV cache** — and they behave very differently.

Verified 2026-07 on `g7e.4xlarge`, `ray-llm:2.56.1-py312-cu130`, vLLM 0.23.0, checkpoint
[`nvidia/Qwen3.6-27B-NVFP4`](https://huggingface.co/nvidia/Qwen3.6-27B-NVFP4).

## TL;DR

| Axis | RTX PRO 6000 (SM120) | Why |
|---|---|---|
| **NVFP4 weights** | ✅ usable, with caveats | No dense-NVFP4 SM120 kernel yet → runs the **Marlin** dequant path (memory-bandwidth win, *not* native FP4 compute). |
| **NVFP4 KV cache** | ❌ crashes on first request | The FP4 **attention** kernel is datacenter-Blackwell-only (sm_100/sm_103). |

`kv_cache_dtype` stays **`fp8`**, and NVFP4 (when used) quantizes **weights only** — hence the toggle is named
`ENABLE_NVFP4_WEIGHT`.

## Weights — usable, but not "native FP4" here

1. **No native FP4 math on SM120 → Marlin fallback.** vLLM has no dense-NVFP4 kernel for SM120 yet
   ([vllm#31085](https://github.com/vllm-project/vllm/issues/31085); the SM120 capability fix
   [#33417](https://github.com/vllm-project/vllm/pull/33417) covers **MoE** only). Dense NVFP4 therefore runs
   the **Marlin weight-only dequant** path — the engine log says it plainly:
   `marlin.py: Your GPU does not have native support for FP4 computation`. You get the **memory-bandwidth**
   benefit (4-bit weights ≈ half the bytes read per token; the checkpoint is ~22 GB vs ~27 GB for FP8, freeing
   ~5 GB for KV), but **not** the native-FP4 compute speedup. Net effect: decode is bandwidth-bound, so NVFP4
   is *faster than FP8* at low/moderate load, but there is no tensor-core FP4 acceleration.

2. **The nvidia NVFP4 checkpoint is language-model-only (text-only).** Its `model.safetensors.index.json`
   contains only `model.language_model.*` and `lm_head` weights — there are **no vision-tower weights**
   (`model.visual.*`, `patch_embed`, `merger`, mm-projector, etc. are all absent). So enabling image input
   (`limit_mm_per_prompt: {image: >0}`) crashes at engine init with
   `RuntimeError: Worker failed with error ''NoneType' object has no attribute 'size''` — vLLM tries to build
   the multimodal path and the vision weights simply aren't in the checkpoint. **Use `image: 0` with NVFP4.**
   If you need image input, use the **FP8** checkpoint (`Qwen/Qwen3.6-27B-FP8`), which ships the vision tower,
   or find/produce an NVFP4 quant that retains it.

3. **MTP works, but with two strings attached.** The checkpoint *does* carry the MTP drafter
   (`config.json`: `mtp_num_hidden_layers=1`, quant `ignore: ["mtp*"]`), so NVFP4 + `qwen3_next_mtp`
   speculative decoding runs and is the fastest single-stream config measured. However:
   - **No prebuilt compile cache for NVFP4+MTP.** It's a different `torch.compile` graph than the (no-MTP)
     cache, so the first replica cold-compiles.
   - **MTP lowers throughput under high concurrency.** Its draft/verify overhead becomes pure cost once the
     batch saturates the GPU — a property of speculative decoding in general, not NVFP4-specific. For many
     concurrent users, disable it (`ENABLE_SPEC_DECODE=0`) or use vLLM
     [dynamic speculative decoding](https://docs.vllm.ai/en/stable/features/speculative_decoding/dynamic_speculative_decoding/),
     which auto-disables SD under load (tested with Eagle/Eagle-3/DFlash; `qwen3_next_mtp` may or may not work
     out of the box).

4. **Requires the cu13 image.** NVFP4 needs `ray-llm:2.56.1-py312-cu130` — the FP4 kernels require CUDA 13.

## KV cache — not usable on SM120

vLLM accepts `kv_cache_dtype="nvfp4"`, but the FP4 **attention** kernel is **sm_100/sm_103-only (datacenter
Blackwell — B200/GB200)**. On the RTX PRO 6000 (SM120) the server starts cleanly and then **crashes on the
first request** ([vllm#43562](https://github.com/vllm-project/vllm/issues/43562)). The valid KV dtypes on
SM120 are `fp8` (= `fp8_e4m3`) and `fp8_e5m2`.

This is why the deployment keeps `kv_cache_dtype="fp8"`. FP8 KV already halves KV memory (which is what lets
the full 256K context fit on the 96 GB card), so the practical loss from not having NVFP4 KV is small here.

## Where NVFP4 becomes first-class

On **datacenter Blackwell (B200 / GB200, sm_100/sm_103)** both constraints lift: the dense NVFP4 GEMM runs on
native FP4 tensor cores (real compute speedup, not just bandwidth), and NVFP4 KV cache works. On SM120 today,
NVFP4 is a **weights-only, memory-bandwidth** optimization — worthwhile for decode-heavy multi-user traffic,
but not the native-FP4 acceleration the format offers on datacenter parts.

## References

- Marlin fallback / no dense-NVFP4 SM120 kernel: [vllm#31085](https://github.com/vllm-project/vllm/issues/31085),
  [vllm#33417](https://github.com/vllm-project/vllm/pull/33417) (MoE).
- NVFP4 KV-cache crash on SM120: [vllm#43562](https://github.com/vllm-project/vllm/issues/43562).
- Text-only checkpoint: `nvidia/Qwen3.6-27B-NVFP4` safetensors index has no vision-tower keys.
- vLLM dynamic speculative decoding: <https://docs.vllm.ai/en/stable/features/speculative_decoding/dynamic_speculative_decoding/>
