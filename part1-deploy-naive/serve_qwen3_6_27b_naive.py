# serve_qwen3_6_27b_naive.py
#
# NAIVE baseline — the "before" in this tutorial. Deploy this only to feel the difference
# vs. the optimized Part 3 version; don't run it in production.
#
# ── What makes it naive ─────────────────────────────────────────────────────────────
#
# GPU: 1× NVIDIA RTX PRO 6000 96GB (g7e.4xlarge, tensor_parallel_size=1) — the SAME shape
#   Part 3 optimizes on. Part 1 deliberately keeps the hardware identical so the "before vs.
#   after" in this tutorial is about the SOFTWARE optimizations alone, not a GPU swap. The FP8
#   weights fit comfortably on this single GPU with no tensor-parallel comms.
#
# What it's missing (every one of these is added in Part 3):
#   - bf16 KV cache (the vLLM default), not FP8 KV — so 128K context here, not the full 256K.
#   - no torch.compile cache — each fresh replica recompiles cold.
#   - no fast S3 weight loader (RunAI Streamer) — weights download on every cold start.
#   - no speculative decoding (MTP).
#   - no prefix-aware routing.
#   - single replica, no autoscaling.
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
    # NOTE: accelerator_type is intentionally omitted — Ray Serve LLM's LLMConfig enum rejects
    # "RTX-PRO-6000". service_naive.yaml pins the g7e RTX PRO 6000 node and the replica's GPU request
    # places there (same approach as Part 3).
    deployment_config=dict(
        # Single replica: no autoscaling, no routing.
        autoscaling_config=dict(min_replicas=1, max_replicas=1),
    ),
    runtime_env=dict(env_vars={"HF_HUB_ENABLE_HF_TRANSFER": "1"}),
    engine_kwargs=dict(
        tensor_parallel_size=1,        # single RTX PRO 6000 96GB (g7e.4xlarge) — no TP comms
        max_model_len=131072,          # 128K. NAIVE: with the default bf16 KV, the full 256K needs FP8
                                       # KV — that's a Part 3 optimization, so it's left off here.
        gpu_memory_utilization=0.85,
        # kv_cache_dtype left at the vLLM default (bf16) — no FP8 KV optimization here. On this single
        # 96GB GPU, 128K context fits with ample headroom; exact concurrency isn't separately benchmarked
        # for this naive config (Part 3 measures the FP8-KV / 256K numbers).
        max_num_seqs=16,
        max_num_batched_tokens=8192,
        enable_prefix_caching=True,
        trust_remote_code=True,
        reasoning_parser="qwen3",
        tool_call_parser="qwen3_coder",
        enable_auto_tool_choice=True,
        # Image input ENABLED by default (Qwen3.6-27B is a VLM). Set image:0 for a text-only endpoint.
        # Verified on this single-GPU 96GB shape in Part 3; if you hit OOM at startup, lower max_pixels
        # (mm_processor_kwargs) or reduce max_model_len.
        limit_mm_per_prompt={"image": 4, "video": 0},
    ),
)

app = build_openai_app({"llm_configs": [llm_config]})
