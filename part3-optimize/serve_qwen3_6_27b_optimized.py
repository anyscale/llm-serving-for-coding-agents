# serve_qwen3_6_27b_optimized.py
#
# OPTIMIZED deployment for 1x NVIDIA RTX PRO 6000 (96 GB Blackwell, AWS g7e.4xlarge), TP=1.
# Every optimization is a toggle in the CONTROL PANEL below — flip each ON/OFF to see its effect.
# The defaults are the validated coding-agent setup: FP8 weights + FP8 KV + full 256K context (6.53×
# concurrency), CUDA graphs, MTP speculative decoding, and the prebuilt compile cache. Fast S3 model
# loading is kept below as an opt-in cold-start alternative, but it is not the default because it conflicts
# with MTP on vLLM 0.22.0.
# Full measurements + the "knobs that can't be combined" matrix:
# notes/BENCHMARKS.md / notes/INCOMPATIBILITIES.md.

# ════════════════════════════════ OPTIMIZATION CONTROL PANEL ════════════════════════════════
# Flip each ON/OFF. Mutually-exclusive combos are flagged with ⚠ (and enforced by a guard below).

# (1) FAST MODEL LOADING — optional cold-start path, not the coding-agent default.
#     RunAI Streamer streams FP8 weights S3 -> GPU (~85s -> ~25s cold start).
#     Needs runai-model-streamer in the image (Containerfile) + cluster S3 read access.
#     ⚠ Mutually exclusive with ENABLE_SPEC_DECODE (vllm#42060). To opt into fast loading instead of
#     MTP decode speed, set:
#       ENABLE_SPEC_DECODE = False
#       ENABLE_FAST_MODEL_LOADING = True
ENABLE_FAST_MODEL_LOADING = False

# (2) COMPILE CACHE — download the prebuilt inductor + AOT torch.compile caches from S3 so a cold replica
#     skips the whole compile (validated 74.5s -> 8.8s).  OFF -> each fresh replica compiles cold.
ENABLE_COMPILE_CACHE = True

# (3) FP8 KV CACHE — store K/V in fp8: ~half the KV memory, which is what lets the full 256K context fit
#     (6.53× concurrency on 96GB).  OFF -> default bf16 KV; 256K won't fit, so lower max_model_len.
ENABLE_FP8_KV_CACHE = True

# (4) CUDA GRAPHS — the single biggest free decode win (~2.87x on Blackwell).  ON = no enforce_eager.
#     OFF -> enforce_eager=True (only to debug, or to fit spec-decode on a small GPU; see notes/).
ENABLE_CUDA_GRAPHS = True

# (5) SPECULATIVE DECODING (MTP) — default ON for coding-agent traffic.
#     ~1.9x decode on RTX PRO 6000, coherent output (the #40880 degenerate-output bug does NOT occur on
#     Blackwell). ⚠ Needs the HF loader, so it turns FAST MODEL LOADING off (vllm#42060): you trade the
#     fast S3 cold-start for faster multi-token generation during agent work. See notes/BENCHMARKS.md.
ENABLE_SPEC_DECODE = True

# (6) PREFIX-AWARE ROUTING — send a session's turns to the replica that cached its prefix. Keep OFF for the
#     single-user coding-agent trace used here: most requests share the same system prompts, skills, and
#     harness context, so round-robin still benefits from each replica's local vLLM prefix cache. Consider
#     enabling only for multi-user traffic with diverse byte-stable prefixes, then tune the imbalance knobs
#     so affinity does not overload one replica. Only matters with max_replicas > 1.
ENABLE_PREFIX_ROUTING = False

# DIRECT STREAMING is REQUIRED for this demo (Parts 1 & 2 connect Claude Code / Codex / Cursor straight to
# native /v1/messages + /v1/responses), so it is NOT a toggle — it's always on. It's enabled at the SERVICE
# level in the service YAML `env_vars` (RAY_SERVE_ENABLE_HA_PROXY + RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING):
# the Ray Serve *controller* reads those at startup, while a runtime_env reaches only replicas (the deploy
# fails "ingress_request_router requires HAProxy" otherwise). Keep those two vars in the YAML — don't remove them.
# ═════════════════════════════════════════════════════════════════════════════════════════════

# Resolve the one hard conflict automatically: MTP needs the HF loader, so turning spec decode on makes
# fast loading turn itself off (vllm#42060). Flipping ENABLE_SPEC_DECODE on "just works" — no second edit.
if ENABLE_SPEC_DECODE and ENABLE_FAST_MODEL_LOADING:
    print("[config] ENABLE_SPEC_DECODE=True -> disabling ENABLE_FAST_MODEL_LOADING "
          "(RunAI Streamer conflicts with MTP, vllm#42060); using the HF loader instead.")
    ENABLE_FAST_MODEL_LOADING = False

import os

from ray.serve.llm import LLMConfig, build_openai_app

# ── Fixed for this deployment ────────────────────────────────────────────────
MODEL_ID   = "qwen3.6-27b"
HF_SOURCE  = "Qwen/Qwen3.6-27B-FP8"                                          # plain HF download
S3_WEIGHTS = "s3://llm-guide/data/ray-serve-llm/hf_repo/Qwen3.6-27B-FP8/"    # for RunAI Streamer

# Compile-cache locations (used only when ENABLE_COMPILE_CACHE). The S3 PREFIXES ENCODE the exact stack a
# torch.compile cache is keyed to (vLLM version + GPU arch + flags); these were rebuilt + validated
# 2026-06-30 on vLLM 0.22.0 / RTX PRO 6000 (SM120) / FP8 weights+KV / TP=1 / 256K. vLLM caches in two dirs
# (inductor + AOT), restored to the two local paths below. Change the image/GPU/flags -> rebuild + new prefix.
COMPILE_CACHE_S3      = "s3://llm-guide/data/ray-serve-llm/compiled-cache/qwen3.6-27b/vllm0.22.0-rtxpro6000-sm120-fp8-tp1-256k/"
COMPILE_CACHE_DIR     = "/home/ray/.cache/vllm/torch_compile_cache/qwen3.6-27b"
COMPILE_CACHE_AOT_S3  = "s3://llm-guide/data/ray-serve-llm/compiled-cache/qwen3.6-27b-aot/vllm0.22.0-rtxpro6000-sm120-fp8-tp1-256k/"
COMPILE_CACHE_AOT_DIR = "/home/ray/.cache/vllm/torch_compile_cache/torch_aot_compile/d2d5f6429cf68f56db205af1548136d88bf1d13247d0d6a24209dbe6420ebc9b"

# ── Build the engine config from the toggles ─────────────────────────────────
engine_kwargs = dict(
    tensor_parallel_size=1,        # single RTX PRO 6000, no TP comms
    max_model_len=262144,          # 256K — Qwen3.6-27B native (262144), no YaRN
    gpu_memory_utilization=0.9,    # RTX PRO 6000 96 GB
    max_num_seqs=32,
    max_num_batched_tokens=8192,   # chunked prefill (256K prompts arrive in chunks)
    enable_prefix_caching=True,
    trust_remote_code=True,
    reasoning_parser="qwen3",
    tool_call_parser="qwen3_coder",   # validated: returns structured tool_calls
    enable_auto_tool_choice=True,
    limit_mm_per_prompt={"image": 0, "video": 0},  # text-only; the recipe's language_model_only= is equivalent here (measured: no KV gain, it just zeros these limits)
)
# Attention backend: intentionally unset — on RTX PRO 6000 (SM120) + fp8 KV, vLLM 0.22 auto-selects
# FlashInfer (its strongest Blackwell attention kernel); forcing VLLM_ATTENTION_BACKEND=FLASHINFER is a no-op.

# (1) Fast model loading
if ENABLE_FAST_MODEL_LOADING:
    model_source = S3_WEIGHTS
    engine_kwargs["load_format"] = "runai_streamer"
else:
    model_source = HF_SOURCE

# (3) FP8 KV cache
if ENABLE_FP8_KV_CACHE:
    engine_kwargs["kv_cache_dtype"] = "fp8"

# (4) CUDA graphs (default on; only set enforce_eager to turn them OFF)
if not ENABLE_CUDA_GRAPHS:
    engine_kwargs["enforce_eager"] = True

# (5) Speculative decoding (MTP). The guard above guarantees the HF loader is in use here (#42060).
if ENABLE_SPEC_DECODE:
    model_source = HF_SOURCE
    # num_speculative_tokens=3 is the measured sweet spot on the real agent replay: +24% out tok/s,
    # +44% turns/s, -19% TPOT vs 2. 4 REGRESSES below 2 (draft/verify overhead > acceptance gain).
    # See notes/BENCHMARKS.md knob 5. (MTP served the traces' ~73K-tok prompts with 0 errors on vLLM 0.22.)
    engine_kwargs["speculative_config"] = {"method": "qwen3_next_mtp", "num_speculative_tokens": 3}

# (2) Compile cache: point vLLM at the cache_dir + download both caches from S3 before engine init.
callback_config = None
if ENABLE_COMPILE_CACHE:
    engine_kwargs["compilation_config"] = {"cache_dir": COMPILE_CACHE_DIR}
    callback_config = {
        "callback_class": "ray.llm._internal.common.callbacks.cloud_downloader.CloudDownloader",
        "callback_kwargs": {"paths": [
            (COMPILE_CACHE_S3, COMPILE_CACHE_DIR),          # inductor kernels -> compilation_config.cache_dir
            (COMPILE_CACHE_AOT_S3, COMPILE_CACHE_AOT_DIR),  # AOT compiled fn  -> torch_aot_compile/<hash>
        ]},
    }

# ── Deployment / autoscaling ─────────────────────────────────────────────────
deployment_config = dict(
    autoscaling_config=dict(
        # 1 (default) = always-on: no cold start during work hours. service-work-hours.yaml
        # sets MIN_REPLICAS=0 (+ compute min_nodes: 0) so idle nights/weekends cost nothing — pair it
        # with warmup.sh on a weekday-morning cron; cost math in notes/COST-ESTIMATE.md.
        min_replicas=int(os.environ.get("MIN_REPLICAS", "1")),
        max_replicas=4,            # scale out for peak; each replica = 1 RTX PRO 6000 node (g7e.4xlarge)
        target_ongoing_requests=8,  # CONSERVATIVE, untested on Pro 6000 — scale out early so the autoscaler
                                    # doesn't pile cold ~73K-tok prefills on one GPU (TTFT/preemption). TODO: measure
                                    # the Pro 6000 capacity cliff (notes/BENCHMARKS.md "TODO") and tune; raise toward 16 if prompts cache well.
        upscale_delay_s=30,
        # service-work-hours.yaml raises this to 1800 so a lunch-break lull doesn't trigger a
        # mid-day cold start.
        downscale_delay_s=int(os.environ.get("DOWNSCALE_DELAY_S", "600")),
    ),
    max_ongoing_requests=64,
)

# (6) Prefix-aware routing (only with max_replicas > 1 AND diverse stable prefixes).
if ENABLE_PREFIX_ROUTING:
    # Tune these thresholds on real traffic. Too much affinity can overload the one replica with the closest
    # prefix cache, even when another replica has spare capacity.
    # Direct streaming is always on here, and the stock PrefixCacheAffinityRouter HANGS under it (it can't
    # read the raw body the direct-streaming ingress forwards). So use the DirectStreamingPrefixCacheRouter
    # subclass in direct_streaming_prefix_router.py, which parses that body. Upstream fix:
    # https://github.com/ray-project/ray/pull/64328 (lands in Ray Serve LLM 2.57) — once you're on
    # ray-llm >= 2.57 you can drop the subclass and use the stock PrefixCacheAffinityRouter directly.
    from direct_streaming_prefix_router import DirectStreamingPrefixCacheRouter as _PrefixRouter
    deployment_config["request_router_config"] = dict(
        request_router_class=_PrefixRouter,
        request_router_kwargs=dict(imbalanced_threshold=5, match_rate_threshold=0.15),
    )

# NOTE: accelerator_type is intentionally omitted — Ray Serve LLM's LLMConfig enum rejects "RTX-PRO-6000".
# The service YAML pins the g7e RTX PRO 6000 node and the replica's GPU request places there.
llm_kwargs = dict(
    model_loading_config=dict(model_id=MODEL_ID, model_source=model_source),
    deployment_config=deployment_config,
    runtime_env=dict(env_vars={"HF_HUB_ENABLE_HF_TRANSFER": "1"}),
    engine_kwargs=engine_kwargs,
)
if callback_config:
    llm_kwargs["callback_config"] = callback_config

llm_config = LLMConfig(**llm_kwargs)
app = build_openai_app({"llm_configs": [llm_config]})
