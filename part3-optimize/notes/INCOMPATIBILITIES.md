# Optimization Compatibility Notes

Read this before changing toggles in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py).

These findings were measured or root-caused on `qwen3.6-27b`, 1× RTX PRO 6000 96 GB
(`g7e.4xlarge`), `ray-llm:2.56.0-py312-cu130`, and vLLM 0.22.0–0.23.0. The current weight default is
`nvidia/Qwen3.6-27B-NVFP4`; FP8 remains the KV-cache dtype. Full numbers are in
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

- Default: enable MTP for ~1.86× faster NVFP4 single-stream decode and accept the slower HF loader.
- Optional cold-start path: keep RunAI Streamer for faster cold starts and turn MTP off.

The control panel automatically disables `ENABLE_FAST_MODEL_LOADING` when `ENABLE_SPEC_DECODE=True`.

MTP + CUDA graphs is coherent on RTX PRO 6000. The older `#40880` degenerate-output issue does not occur
here, so CUDA graphs can stay on with MTP.

### 2. MTP and the No-MTP Compile Cache

The prebuilt NVFP4 cache is keyed to the no-MTP text graph. MTP and image-heavy requests produce different
compile graphs, so they cannot reuse that cache. The control panel automatically disables
`ENABLE_COMPILE_CACHE` when MTP is enabled.

### 3. Direct Streaming and Built-In Prefix Routing

Direct streaming plus Ray's built-in `PrefixCacheAffinityRouter` hangs on ray-llm 2.56. The direct-streaming
ingress puts the raw body in `pending_request.kwargs["request_body"]`, but that router only checks
`args`, so prefix routing never sees the request body correctly.

Options:

- Use the default `RoundRobinRouter` for the single-user replay data in this tutorial.
- If you opt into prefix routing, use `DirectStreamingPrefixCacheRouter`.
- On Ray Serve LLM 2.57 or newer, use Ray's built-in router after
  [ray#64328](https://github.com/ray-project/ray/pull/64328) lands.

In this tutorial, direct streaming is always on. That is why prefix routing, when enabled, uses the subclass.

## What Composes

This default set works together and is enabled in
[`serve_qwen3_6_27b_optimized.py`](../serve_qwen3_6_27b_optimized.py):

- NVFP4 weights
- FP8 KV cache
- CUDA graphs
- MTP speculative decoding (`qwen3_next_mtp`)
- autoscale
- direct streaming
- tool calling (`qwen3_coder`)
- reasoning parser (`qwen3`)

With MTP off, the no-MTP NVFP4 text-graph compile cache composes with FP8 KV, CUDA graphs, autoscaling, and
direct streaming. The deliberate opt-ins are `ENABLE_FAST_MODEL_LOADING` and `ENABLE_PREFIX_ROUTING`. Fast
loading is useful when cold-start time matters more than decode speed; prefix routing depends on traffic
shape. See
[`BENCHMARKS.md`](BENCHMARKS.md) for the spec-decode numbers and the prefix-routing guidance.
