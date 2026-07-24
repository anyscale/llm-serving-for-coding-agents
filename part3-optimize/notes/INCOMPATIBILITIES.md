# Optimization Compatibility Notes

Read this before changing toggles in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py).

These findings were measured or root-caused on `qwen3.6-27b` FP8, 1× RTX PRO 6000 96 GB
(`g7e.4xlarge`), `ray-llm:2.56.0-py312-cu130`, and vLLM 0.22.0. Full numbers are in
[`BENCHMARKS.md`](BENCHMARKS.md).

## Claude Code Compatibility

The Ray LLM 2.56.0 base image's vLLM 0.22.0 rejects Claude Code's current Messages payload. Keep the
Part 3 `Containerfile` override at vLLM 0.23.0 or newer; vLLM 0.23.0 was validated with Claude Code 2.1.201.

## Hard Incompatibilities

### 1. RunAI Streamer and MTP Spec Decode

`load_format="runai_streamer"` and MTP spec decode cannot both be on. The MTP drafter reloads weights
through the RunAI loader, which searches for `*.safetensors` in a streamer cache directory that has none.
The engine fails at init with:

```text
Cannot find any safetensors model weights ... model_streamer/<hash>
```

This is tracked in [vllm#42060](https://github.com/vllm-project/vllm/issues/42060). The open fix PR #42079
does not resolve it in end-to-end testing.

Choose one:

- Default: enable MTP for ~1.89× faster decode and accept the slower HF loader.
- Optional cold-start path: keep RunAI Streamer for faster cold starts and turn MTP off.

The control panel automatically disables `ENABLE_FAST_MODEL_LOADING` when `ENABLE_SPEC_DECODE=True`.

MTP + CUDA graphs is coherent on RTX PRO 6000. The older `#40880` degenerate-output issue does not occur
here, so CUDA graphs can stay on with MTP.

### 2. Direct Streaming and Built-In Prefix Routing

Direct streaming plus Ray's built-in `PrefixCacheAffinityRouter` hangs on ray-llm 2.56. The direct-streaming
ingress puts the raw body in `pending_request.kwargs["request_body"]`, but that router only checks
`args`, so prefix routing never sees the request body correctly.

Options:

- Use the default `RoundRobinRouter` for the single-user replay data in this tutorial.
- If you opt into prefix routing, use `DirectStreamingPrefixCacheRouter`.
- On Ray Serve LLM 2.57 or newer, use Ray's built-in router after
  [ray#64328](https://github.com/ray-project/ray/pull/64328) lands.

In this tutorial, direct streaming is always on. That is why prefix routing, when enabled, uses the subclass.

### 3. NVFP4 Weights — the knobs it changes

`ENABLE_NVFP4` (knob 7) composes with the rest of the panel, but it adjusts a few defaults (the control panel
does this automatically):

- **Base image must be `ray-llm:2.56.1-py312-cu130`** (`Containerfile.nvfp4`) — cu13 is required for the FP4
  kernels. Keep `kv_cache_dtype="fp8"`: the `nvfp4` *KV-cache* dtype still crashes on SM120 (`BENCHMARKS.md` §3).
- **No RunAI fast-loading.** `S3_WEIGHTS` mirrors the FP8 weights, so NVFP4 loads from the HF source.
- **MTP defaults off, but IS available.** The nvidia NVFP4 checkpoint carries the `qwen3_next_mtp` drafter
  (`config.json`: `mtp_num_hidden_layers=1`, quant `ignore: [mtp*]`), so NVFP4+MTP works. It is off by default
  because MTP *hurts* multi-user throughput (`BENCHMARKS.md` §7); set `ENABLE_SPEC_DECODE=1` for the single-user
  NVFP4+MTP latency config (fastest single-stream, 121 tok/s).
- **Compile cache is per-graph.** NVFP4-no-MTP has its own prebuilt cache (`COMPILE_CACHE_*_NVFP4`, fast scale-up).
  NVFP4+MTP is a different graph with no prebuilt cache → it cold-compiles (build + upload one under a new prefix
  if you want fast scale-up there too).

NVFP4 does **not** engage native FP4 tensor cores on SM120 — vLLM has no dense NVFP4 kernel for SM120 yet
([vllm#31085](https://github.com/vllm-project/vllm/issues/31085)), so it runs the Marlin weight-only path. The
multi-user win comes from lower weight-memory bandwidth, not native FP4 math.

## What Composes

This set works together and is enabled in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py):

- torch.compile cache
- FP8 KV cache
- CUDA graphs
- MTP speculative decoding (`qwen3_next_mtp`)
- autoscale
- direct streaming
- tool calling (`qwen3_coder`)
- reasoning parser (`qwen3`)

The deliberate opt-ins are `ENABLE_FAST_MODEL_LOADING` and `ENABLE_PREFIX_ROUTING`. Fast loading is useful
when cold-start time matters more than decode speed; prefix routing depends on traffic shape. See
[`BENCHMARKS.md`](BENCHMARKS.md) for the spec-decode numbers and the prefix-routing guidance.
