# serve_qwen3_6_27b_naive.py
#
# NAIVE baseline — the "before" in TUTORIAL.md (Step 0). It works, but it's the wrong
# shape for a multi-user team. Deploy this only to feel the difference vs. the optimized
# version; don't run it in production.
#
# What makes it naive:
#   - 4x L4 (g6.12xlarge), tensor_parallel_size=4 — this is the GPU shape available for the
#     Ray Summit training session, so the lab uses it. L4 is the slowest serving GPU
#     (~300 GB/s) and the 4 GPUs are PCIe (no NVLink), so TP=4 pays a comms tax.
#     (The FP8 model actually fits on ONE L40S — see the optimized version.)
#   - Single replica -> ~2 concurrent full-length requests = effectively one user.
#   - Weights downloaded from Hugging Face on every cold start (~85 s).
#   - No compile cache -> recompiles (~90-137 s) on every fresh replica.
#   - No speculative decoding, no prefix-aware routing.
#
# The ONE thing it DOES turn on: DIRECT STREAMING — an API-surface feature (not a perf tweak) that
# puts vLLM's native app behind HAProxy so this single endpoint serves
#   /v1/chat/completions (Cursor) + /v1/messages (Claude Code) + /v1/responses (Codex)
# all at once, which is what lets Part 2 connect all three agents with NO proxy / no LiteLLM.
# It's enabled by two SERVICE-LEVEL env_vars set in service_naive.yaml (top-level `env_vars:`):
#   RAY_SERVE_ENABLE_HA_PROXY=1  +  RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1
# They MUST be service/cluster-level, NOT a per-deployment runtime_env / in-module os.environ: the Ray
# Serve *controller* reads RAY_SERVE_ENABLE_HA_PROXY at startup (ray/serve/_private/build_app.py); a
# runtime_env reaches only the replicas, so setting it there fails "ingress_request_router requires
# HAProxy". Anyscale applies service-level env_vars cluster-wide, so the controller inherits them.
# Safe here because there's no custom request router (direct streaming conflicts with the stock
# PrefixCacheAffinityRouter; the single-replica default RoundRobinRouter used here is fine).
from ray.serve.llm import LLMConfig, build_openai_app

llm_config = LLMConfig(
    model_loading_config=dict(
        model_id="qwen3.6-27b",
        model_source="Qwen/Qwen3.6-27B-FP8",   # plain HF download (slow cold start)
    ),
    accelerator_type="L4",
    deployment_config=dict(
        # Single replica: no autoscaling, no routing. One node serves everyone.
        autoscaling_config=dict(min_replicas=1, max_replicas=1),
    ),
    runtime_env=dict(env_vars={"HF_HUB_ENABLE_HF_TRANSFER": "1"}),
    engine_kwargs=dict(
        tensor_parallel_size=4,        # 4x L4 on one g6.12xlarge node
        max_model_len=131072,          # 128K
        gpu_memory_utilization=0.85,   # 24 GB GPU rule of thumb
        # kv_cache_dtype left at the default (bf16) — the full 128K context fits on 4x L4 without
        # quantizing the KV cache (652,346-token cache, 4.98x concurrency at 128K). See README.
        max_num_seqs=16,
        max_num_batched_tokens=8192,
        enable_prefix_caching=True,
        trust_remote_code=True,
        reasoning_parser="qwen3",
        tool_call_parser="qwen3_coder",
        enable_auto_tool_choice=True,
        limit_mm_per_prompt={"image": 0, "video": 0},
    ),
)

app = build_openai_app({"llm_configs": [llm_config]})
