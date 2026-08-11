# serve_qwen3_6_27b_optimized.py
#
# OPTIMIZED deployment for 1x NVIDIA RTX PRO 6000 (96 GB Blackwell, AWS g7e.4xlarge), TP=1.
# Serves the 4-bit NVFP4 weight checkpoint (nvidia/Qwen3.6-27B-NVFP4) — the validated coding-agent default:
# NVFP4 weights + FP8 KV + full 256K context (6.53× concurrency), CUDA graphs, MTP speculative decoding, and
# (for the no-MTP path) the prebuilt compile cache. NVFP4 weights are ~22 GB (vs FP8 ~27 GB), freeing KV
# headroom; they run the Marlin (non-native) FP4 path on SM120 (no dense-NVFP4 SM120 kernel in vLLM yet:
# vllm#31085 / #33417 cover MoE only). The checkpoint is a vision-language model and serves image input
# (verified on RTX PRO 6000 / vLLM 0.23.0). Every optimization is a toggle in the CONTROL PANEL.
# Full measurements + the "knobs that can't be combined" matrix:
# notes/BENCHMARKS.md / notes/INCOMPATIBILITIES.md.
#
# STACK: ray-llm 2.57.0 / vLLM 0.25.1 (Containerfile). Except for the compile cache (knob 2, rebuilt and
# re-measured on 0.25.1), the numbers below were measured on vLLM 0.22.0-0.23.0 under ray-llm 2.56.0 and
# have NOT been re-validated — see notes/BENCHMARKS.md "Revalidation on vLLM 0.25.1" for what to re-run.
# The one behavior change the upgrade brings is the prefix router (knob 6): ray#64328 makes the stock
# router work under direct streaming, so the DirectStreamingPrefixCacheRouter adapter this repo carried
# is gone.

import os

# ════════════════════════════════ OPTIMIZATION CONTROL PANEL ════════════════════════════════
# Flip each ON/OFF. Mutually-exclusive combos are flagged with ⚠ (and enforced by a guard below).

# (0) NVFP4 WEIGHTS — use NVIDIA's ~22 GB 4-bit checkpoint instead of the ~27 GB FP8 checkpoint.
#     ON is the RTX PRO 6000 default. Turn OFF for the FP8 baseline or for older FP8-capable GPUs such as
#     Hopper H100. This changes model weights only; FP8 KV cache is controlled independently by knob 3.
#     ⚠ The prebuilt compile cache is NVFP4-specific, so turning this OFF also disables knob 2.
ENABLE_NVFP4_WEIGHTS = True

# (1) FAST MODEL LOADING — optional cold-start path, not the default. RunAI Streamer streams the selected
#     checkpoint from S3 -> GPU (~85s -> ~25s cold start). Needs runai-model-streamer in the image
#     (Containerfile) + cluster S3 read access. Validated on RTX PRO 6000 / vLLM 0.23.0.
#     ⚠ Mutually exclusive with ENABLE_SPEC_DECODE (vllm#42060). To opt into fast loading instead of MTP
#     decode speed, set:
#       ENABLE_SPEC_DECODE = False
#       ENABLE_FAST_MODEL_LOADING = True
ENABLE_FAST_MODEL_LOADING = False

# (2) COMPILE CACHE — download the prebuilt inductor + AOT torch.compile caches from S3 so a cold replica
#     skips the whole compile (validated 74.5s -> 8.8s; 48.5s -> 6.0s as re-measured on vLLM 0.25.1 — the
#     ratio holds, the absolutes move per vLLM version). The cache is keyed to the no-MTP text graph; MTP
#     and image-heavy graphs differ, so those cold-compile regardless. OFF -> compile cold.
ENABLE_COMPILE_CACHE = True

# (3) FP8 KV CACHE — store K/V in fp8: ~half the KV memory, which is what lets the full 256K context fit
#     (6.53× concurrency on 96GB).  OFF -> default bf16 KV; 256K won't fit, so lower max_model_len.
#     This is independent of the NVFP4 *weight* format. NVFP4 KV is datacenter-Blackwell-only and crashes
#     on SM120 (vllm#43562), so FP8 remains the KV-cache dtype on RTX PRO 6000.
ENABLE_FP8_KV_CACHE = True

# (4) CUDA GRAPHS — the single biggest free decode win (~2.87x on Blackwell).  ON = no enforce_eager.
#     OFF -> enforce_eager=True (only to debug, or to fit spec-decode on a small GPU; see notes/).
ENABLE_CUDA_GRAPHS = True

# (5) SPECULATIVE DECODING (MTP) — env-settable, default ON. MTP is the biggest single-stream decode win
#     (NVFP4+MTP 121 tok/s vs 65 without). Its draft/verify overhead lowers throughput once the GPU is
#     saturated by many concurrent users (notes/BENCHMARKS.md §5). For high-concurrency deployments set
#     ENABLE_SPEC_DECODE=0 or try vLLM dynamic speculative decoding. ⚠ Needs the HF loader, so it turns
#     FAST MODEL LOADING off (vllm#42060).
ENABLE_SPEC_DECODE = os.environ.get("ENABLE_SPEC_DECODE", "1") == "1"

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

# MTP needs the HF loader, so turning spec decode on makes fast loading turn itself off (vllm#42060).
# It also has a distinct torch.compile graph with no prebuilt cache. Resolve both here so the env toggle
# needs no second edit.
WEIGHT_FORMAT = "NVFP4" if ENABLE_NVFP4_WEIGHTS else "FP8"
if not ENABLE_NVFP4_WEIGHTS and ENABLE_COMPILE_CACHE:
    print("[config] ENABLE_NVFP4_WEIGHTS=False -> disabling ENABLE_COMPILE_CACHE "
          "(the prebuilt cache is keyed to NVFP4 weights).")
    ENABLE_COMPILE_CACHE = False

if ENABLE_SPEC_DECODE:
    ENABLE_COMPILE_CACHE = False
    if ENABLE_FAST_MODEL_LOADING:
        print("[config] ENABLE_SPEC_DECODE=True -> disabling ENABLE_FAST_MODEL_LOADING "
              "(RunAI Streamer conflicts with MTP, vllm#42060); using the HF loader instead.")
        ENABLE_FAST_MODEL_LOADING = False
    print(f"[config] {WEIGHT_FORMAT} weights + MTP. MTP has no prebuilt compile cache -> cold compile. "
          "For high concurrency set ENABLE_SPEC_DECODE=0.")
else:
    cache_status = "using the prebuilt NVFP4 compile cache" if ENABLE_COMPILE_CACHE else "compiling cold"
    print(f"[config] {WEIGHT_FORMAT} weights, no MTP (high concurrency) -> {cache_status}.")

from ray.serve.llm import LLMConfig, build_openai_app

# ── Fixed for this deployment ────────────────────────────────────────────────
MODEL_ID = "qwen3.6-27b"
if ENABLE_NVFP4_WEIGHTS:
    HF_SOURCE = "nvidia/Qwen3.6-27B-NVFP4"
    S3_WEIGHTS = "s3://llm-guide/data/ray-serve-llm/hf_repo/Qwen3.6-27B-NVFP4/"
    WEIGHT_QUANTIZATION = "modelopt"
else:
    # FP8 baseline and older FP8-capable GPU path. Ampere GPUs do not have native FP8 support.
    HF_SOURCE = "Qwen/Qwen3.6-27B-FP8"
    S3_WEIGHTS = "s3://llm-guide/data/ray-serve-llm/hf_repo/Qwen3.6-27B-FP8/"
    WEIGHT_QUANTIZATION = None  # let vLLM infer the checkpoint's FP8 quantization metadata

# NVFP4 compile cache (rebuilt + uploaded 2026-08-10; keyed to vLLM 0.25.1 / RTX PRO 6000 (SM120) / NVFP4
# weights + FP8 KV / TP=1 / 256K, no-MTP text graph). Used when ENABLE_COMPILE_CACHE and MTP is off. vLLM
# caches in two dirs (inductor + AOT), restored to the two local paths below. Rebuild + new prefix if the
# image/GPU/flags (or compile graph, e.g. image input) change.
#
# The 0.23.0 prefixes are still in the bucket but are NOT usable here: 0.25.1 renamed the per-rank cache
# subdir from rank_0_0 to rank_0_0_dev0, so the old layout doesn't even match, let alone the cache keys.
# To rebuild after the next vLLM bump:
#   1. Deploy once with ENABLE_COMPILE_CACHE=False and ENABLE_SPEC_DECODE=0 (no-MTP text graph) and let the
#      replica compile cold. cache_dir is pinned to COMPILE_CACHE_DIR on this path (see below), which is
#      REQUIRED: the AOT artifact bakes in absolute inductor-cache paths, so a cache compiled under any
#      other cache_dir cannot be restored here.
#   2. Copy COMPILE_CACHE_DIR and COMPILE_CACHE_AOT_DIR off the REPLICA's node — not the head, which never
#      runs the engine.
#   3. `aws s3 sync` each to a new prefix named for the stack, then update the two *_S3 constants.
#   4. Update COMPILE_CACHE_AOT_DIR: the hash is derived from the compile config and DOES change across
#      vLLM versions (0.23.0 -> 0.25.1 moved it), so read it off the replica rather than assuming.
#   5. Set ENABLE_COMPILE_CACHE = True, redeploy, and confirm the restore in the replica log.
#
# The "-v2" suffix is not meaningful beyond history: a first 0.25.1 upload was compiled under the wrong
# cache_dir (see step 1) and is unusable. Drop the suffix on the next rebuild.
COMPILE_CACHE_S3      = "s3://llm-guide/data/ray-serve-llm/compiled-cache/qwen3.6-27b/vllm0.25.1-rtxpro6000-sm120-nvfp4-tp1-256k-v2/"
COMPILE_CACHE_DIR     = "/home/ray/.cache/vllm/torch_compile_cache/qwen3.6-27b-nvfp4"
COMPILE_CACHE_AOT_S3  = "s3://llm-guide/data/ray-serve-llm/compiled-cache/qwen3.6-27b-aot/vllm0.25.1-rtxpro6000-sm120-nvfp4-tp1-256k-v2/"
COMPILE_CACHE_AOT_DIR = "/home/ray/.cache/vllm/torch_compile_cache/torch_aot_compile/6da065b950384cbbcb9c1388f5c6357211cfca1f0d91a9a0ed2097a3054d307e"

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
    # Image input ENABLED. The NVFP4 checkpoint carries the vision tower and serves images end-to-end on
    # 1× RTX PRO 6000 (SM120) / vLLM 0.23.0. Image graphs differ from the text-only compile cache (so they
    # cold-compile); for image-heavy prompts also watch max_pixels (mm_processor_kwargs) / KV headroom.
    limit_mm_per_prompt={"image": 4, "video": 0},
)
if WEIGHT_QUANTIZATION:
    # NVIDIA's model card serves this checkpoint with `--quantization modelopt`.
    engine_kwargs["quantization"] = WEIGHT_QUANTIZATION
# Attention backend: intentionally unset — on RTX PRO 6000 (SM120) + fp8 KV, vLLM auto-selects
# FlashInfer (its strongest Blackwell attention kernel); forcing VLLM_ATTENTION_BACKEND=FLASHINFER is a no-op.

# (1) Fast model loading (RunAI Streamer from the NVFP4 S3 mirror).
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

# (5) Speculative decoding (MTP). Both weight checkpoints carry the MTP drafter.
if ENABLE_SPEC_DECODE:
    # num_speculative_tokens=3 is the measured sweet spot on the real agent replay: +24% out tok/s,
    # +44% turns/s, -19% TPOT vs 2. 4 REGRESSES below 2 (draft/verify overhead > acceptance gain).
    # See notes/BENCHMARKS.md knob 5. (MTP served the traces' ~73K-tok prompts with 0 errors on vLLM 0.22;
    # the sweep has not been re-run on 0.25.1.)
    engine_kwargs["speculative_config"] = {"method": "qwen3_next_mtp", "num_speculative_tokens": 3}

# (2) Compile cache: point vLLM at the cache_dir + download both caches from S3 before engine init.
callback_config = None
if not ENABLE_SPEC_DECODE:
    # Pin cache_dir on the whole no-MTP path, not just when restoring. The AOT artifact stores ABSOLUTE
    # paths into the inductor cache dir, so a cache is only loadable under the same cache_dir it was
    # compiled under. Leaving this unset during a cold compile (as a rebuild run does) sends the artifacts
    # to a hashed default dir, and restoring that cache here dies with
    #   FileNotFoundError: .../torch_compile_cache/<hash>/rank_0_0_dev0/backbone/artifact_compile_range_...
    # which kills the engine rather than falling back to a cold compile. Pinning it unconditionally means a
    # rebuild run bakes in the same path the restore uses.
    engine_kwargs["compilation_config"] = {"cache_dir": COMPILE_CACHE_DIR}
if ENABLE_COMPILE_CACHE:
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
        target_ongoing_requests=16,  # CONSERVATIVE, untested on Pro 6000 — scale out early so the autoscaler
                                    # doesn't pile cold ~73K-tok prefills on one GPU (TTFT/preemption)
        upscale_delay_s=30,
        # service-work-hours.yaml raises this to 1800 so a lunch-break lull doesn't trigger a
        # mid-day cold start.
        downscale_delay_s=int(os.environ.get("DOWNSCALE_DELAY_S", "600")),
    ),
    max_ongoing_requests=32,
)

# (6) Prefix-aware routing (only with max_replicas > 1 AND diverse stable prefixes).
if ENABLE_PREFIX_ROUTING:
    # Tune these thresholds on real traffic. Too much affinity can overload the one replica with the closest
    # prefix cache, even when another replica has spare capacity.
    # Direct streaming is always on here. On ray-llm 2.56 the stock PrefixCacheAffinityRouter hung under it
    # (it couldn't read the raw body the direct-streaming ingress forwards) and this repo shipped a
    # DirectStreamingPrefixCacheRouter subclass to work around it. ray#64328 fixed the ingress in 2.57, so
    # the stock router is used directly and the subclass is gone. On ray-llm < 2.57, restore that adapter.
    # Note: this router has no public export, so the import path is a Ray internal and may move between
    # releases. Verified present in ray-llm 2.57.0.
    from ray.llm._internal.serve.routing_policies.prefix_aware.prefix_aware_router import (
        PrefixCacheAffinityRouter as _PrefixRouter,
    )
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
