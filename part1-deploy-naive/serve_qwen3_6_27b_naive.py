# serve_qwen3_6_27b_naive.py
#
# NAIVE baseline — the "before" in this tutorial. Deploy this only to feel the difference
# vs. the optimized Part 3 version; don't run it in production.
#
# ── What makes it naive ─────────────────────────────────────────────────────────────
#
# GPU choice: 4× L4 (g6.12xlarge), tensor_parallel_size=4
#   All 4 L4s sit on one node, connected via PCIe (no NVLink).
#   L4 has the lowest memory bandwidth of serving GPUs (~300 GB/s),
#   and PCIe interconnect adds communication overhead between the GPUs.
#   (The FP8 model actually fits on a single bigger GPU — see Part 3.)
#
# Capacity: single replica, 652,346-token KV cache (4.98× raw capacity at 128K).
#
# Cold start: weights downloaded from S3 every time (~85 s).
#
# Compilation: no compile cache, so each fresh replica recompiles (~90–137 s).
#
# Missing: no speculative decoding, no prefix-aware routing.
#
# ── One thing it DOES enable: direct streaming ──────────────────────────────────────
#
# Direct streaming is an API feature (not a performance tweak) that puts vLLM's native
# app behind HAProxy so this single endpoint serves all three agent protocols:
#
#   /v1/chat/completions  (Cursor)
#   /v1/messages          (Claude Code)
#   /v1/responses         (Codex)
#
# This is what lets Part 2 connect all three agents with no proxy and no LiteLLM.
#
# It's enabled by two CLUSTER-LEVEL env vars. In a workspace, set them as workspace
# environment variables; in a Service, put them in service_naive.yaml (top-level env_vars):
#
#   RAY_SERVE_ENABLE_HA_PROXY=1
#   RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1
#
# IMPORTANT: these must be cluster-level, NOT per-deployment runtime_env or
# in-module os.environ. The Ray Serve controller reads RAY_SERVE_ENABLE_HA_PROXY at
# startup (ray/serve/_private/build_app.py); a runtime_env only reaches the replicas,
# so the app fails with "ingress_request_router requires HAProxy." Anyscale applies
# cluster-level env vars across the cluster, so the controller inherits them.
#
# Safe here because there's no custom request router: direct streaming conflicts with
# the stock PrefixCacheAffinityRouter, but the single-replica default RoundRobinRouter
# used here is fine.
from ray.serve.llm import LLMConfig, build_openai_app

llm_config = LLMConfig(
    model_loading_config=dict(
        model_id="qwen3.6-27b",
        model_source="s3://llm-guide/data/ray-serve-llm/hf_repo/Qwen3.6-27B-FP8/",
    ),
    accelerator_type="L4",
    deployment_config=dict(
        # Single replica: no autoscaling, no routing.
        autoscaling_config=dict(min_replicas=1, max_replicas=1),
    ),
    runtime_env=dict(env_vars={"HF_HUB_ENABLE_HF_TRANSFER": "1"}),
    engine_kwargs=dict(
        tensor_parallel_size=4,        # 4xL4 GPUs on one g6.12xlarge (PCIe, no NVLink)
        max_model_len=131072,          # 128K
        gpu_memory_utilization=0.85,   
        # kv_cache_dtype left at the default (bf16). GPU KV cache: 652,346 tokens,
        # 10.38 GiB/GPU, 4.98× raw concurrency at 128K. (vLLM 0.22.0 log output.)
        max_num_seqs=16,
        max_num_batched_tokens=8192,
        enable_prefix_caching=True,
        trust_remote_code=True,
        reasoning_parser="qwen3",
        tool_call_parser="qwen3_coder",
        enable_auto_tool_choice=True,
        # Image input ENABLED by default (Qwen3.6-27B is a VLM). Set image:0 for a text-only endpoint.
        # NOTE: verified on the Part 3 single-GPU 96GB shape; this 4x L4 (24GB) baseline is tighter and
        # was not separately load-tested — if you hit OOM at startup, lower max_pixels (mm_processor_kwargs)
        # or reduce max_model_len.
        limit_mm_per_prompt={"image": 4, "video": 0},
    ),
)

app = build_openai_app({"llm_configs": [llm_config]})
