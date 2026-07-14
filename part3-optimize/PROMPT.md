/anyscale-workload-llm-serving Deploy Qwen3.6-27B (FP8) as an OpenAI-compatible endpoint on an Anyscale Service using Ray Serve LLM, optimized for a single RTX PRO 6000 (96 GB Blackwell) serving the full 256K context with fast cold starts. These requirements are complete and final — skip the requirements interview and the confirmation step, and generate the two files directly: `serve_qwen3_6_27b_optimized.py` (`LLMConfig` + `build_openai_app`) and `service_optimized.yaml`.

| Requirement | Value |
|---|---|
| Model | `qwen3.6-27b` ← `Qwen/Qwen3.6-27B-FP8` (FP8) |
| GPU Type | RTX PRO 6000 96 GB (Blackwell, SM120) |
| GPU Count | 1 (`tensor_parallel_size=1`) → AWS `g7e.4xlarge` |
| Workload Type | Decode-heavy, long-context |
| Use Case | Agentic / code generation |
| Context Length | `max_model_len=262144` (256K — Qwen3.6 native, no YaRN) |
| Availability Mode | Always-on (`min_replicas=1`) |
| Autoscaling | min=1, max=4; `target_ongoing_requests=8`, `upscale_delay_s=30`, `downscale_delay_s=600`; `max_ongoing_requests=64` |
| Target Metric | ongoing requests per replica |
| Load Balancing | round-robin (default) |
| Features | Tool calling + reasoning; no LoRA; no structured output |
| Tool calling | ON — `tool_call_parser="qwen3_coder"` + `enable_auto_tool_choice=True` |
| Reasoning parser | ON — `reasoning_parser="qwen3"` |
| Speculative decoding | Default OFF — MTP `{"method":"qwen3_next_mtp","num_speculative_tokens":3}` (~1.9× decode; needs the HF loader, so it disables RunAI Streamer — vllm#42060) |

Also required:
- **GPU / instance**: 1× RTX PRO 6000 96 GB, `g7e.4xlarge`, TP=1. OMIT `accelerator_type` (Ray Serve LLM's enum rejects `RTX-PRO-6000`) — pin the instance in the service YAML instead. Use `g7e.4xlarge` or larger (`g7e.2xlarge`'s 64 GiB host RAM OOMs on the 27B + 256K init).
- **FP8 KV cache**: `kv_cache_dtype="fp8"` — halves KV memory so the full 256K fits (~6.53× concurrency on 96 GB).
- **CUDA graphs**: on — do NOT set `enforce_eager` (~2.87× decode on Blackwell).
- **Fast model loading (RunAI Streamer)**: `load_format="runai_streamer"` with `model_source` = your S3 copy of the FP8 weights (~25 s vs ~85 s cold start). Requires `runai-model-streamer` in the image + cluster S3 read access.
- **Compile cache**: before engine init, download the prebuilt inductor + AOT `torch.compile` caches from S3 (Ray Serve LLM `callback_config` → `CloudDownloader`) and point `compilation_config.cache_dir` at them (~9 s vs ~74 s). The S3 prefixes are keyed to the exact stack (vLLM version + GPU arch + flags) — use your own rebuilt caches.
- **Direct streaming (required, always on)**: `RAY_SERVE_ENABLE_HA_PROXY=1` + `RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1` as service-level `env_vars` (NOT `runtime_env`).
- **Other `engine_kwargs`**: `max_num_seqs=32`, `max_num_batched_tokens=8192` (chunked prefill for 256K prompts), `enable_prefix_caching=True`, `trust_remote_code=True`, text-only (`limit_mm_per_prompt={"image":0,"video":0}`); `runtime_env` env `HF_HUB_ENABLE_HF_TRANSFER=1`.
- **Image**: custom — `anyscale/ray-llm:2.56.0-py312-cu130` + `runai-model-streamer` (build from a Containerfile at deploy time, or pre-build → `image_uri`).
- **`service_optimized.yaml`**: `name: qwen3-6-27b-fp8-rtxpro6000-opt`; the image above; the two direct-streaming `env_vars`; `compute_config.worker_nodes` = one `g7e.4xlarge`, `min_nodes: 1`, `max_nodes: 4`; `working_dir: .`; `applications: [{ import_path: serve_qwen3_6_27b_optimized:app }]`.
- **Optional — prefix-aware routing**: default OFF (measured to hotspot badly — up to ~263× worse TTFT). Only with `max_replicas > 1` AND many distinct large prefixes; under direct streaming the stock `PrefixCacheAffinityRouter` hangs, so a direct-streaming-aware router subclass is needed (fixed upstream in Ray Serve LLM ≥ 2.57).
