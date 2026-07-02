# Optimization Compatibility Notes

Read this before changing toggles in `serve_qwen3_6_27b_optimized.py`.

These findings were measured or root-caused on `qwen3.6-27b` FP8, 1× RTX PRO 6000 96 GB
(`g7e.4xlarge`), `ray-llm:2.56.0-py312-cu130`, and vLLM 0.22.0. Full numbers are in
[`BENCHMARKS.md`](BENCHMARKS.md).

## Recommended Defaults

| Optimization | Default | Reason |
|---|---|---|
| CUDA graphs | On | ~2.87× decode speedup. |
| RunAI Streamer | On | Model load drops from ~85 s to ~25 s. |
| torch.compile cache | On | Compile drops from ~74.5 s to ~8.8 s. |
| FP8 KV cache | On | Full 256K context fits on the 96 GB card. |
| Autoscale | On | Needed for multi-user throughput. |
| Direct streaming | On | Required for native Claude Code and Codex endpoints. |
| Speculative decoding | Off | Faster decode, but disables RunAI Streamer. |
| Prefix routing | Off | Hotspots on shared-prefix agent traffic. |

Bottom line: ship CUDA graphs, RunAI Streamer, compile cache, FP8 KV, autoscale, and direct streaming. Leave
speculative decoding and prefix routing off unless your workload justifies the tradeoff.

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

- Keep RunAI Streamer for faster cold starts.
- Enable MTP for ~1.89× faster decode and accept the slower HF loader.

The control panel automatically disables `ENABLE_FAST_MODEL_LOADING` when `ENABLE_SPEC_DECODE=True`.

MTP + CUDA graphs is coherent on RTX PRO 6000. The older `#40880` degenerate-output issue does not occur
here, so CUDA graphs can stay on with MTP.

### 2. Direct Streaming and Stock Prefix Routing

Direct streaming plus the stock `PrefixCacheAffinityRouter` hangs on ray-llm 2.56. The direct-streaming
ingress puts the raw body in `pending_request.kwargs["request_body"]`, but the stock router only checks
`args`, so prefix routing never sees the request body correctly.

Options:

- Use the default `RoundRobinRouter` (recommended for this workload).
- If you opt into prefix routing, use `DirectStreamingPrefixCacheRouter`.
- On Ray Serve LLM 2.57 or newer, use the stock router after
  [ray#64328](https://github.com/ray-project/ray/pull/64328) lands.

In this tutorial, direct streaming is always on. That is why prefix routing, when enabled, uses the subclass.

## What Composes

This set works together and is enabled in `serve_qwen3_6_27b_optimized.py`:

- RunAI Streamer
- torch.compile cache
- FP8 KV cache
- CUDA graphs
- autoscale
- direct streaming
- tool calling (`qwen3_coder`)
- reasoning parser (`qwen3`)

The two deliberate opt-ins are `ENABLE_SPEC_DECODE` and `ENABLE_PREFIX_ROUTING`. See
[`BENCHMARKS.md`](BENCHMARKS.md) for when either might be worth testing.
