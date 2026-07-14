/anyscale-workload-llm-serving Deploy Qwen3.6-27B (FP8) as an OpenAI-compatible endpoint on an Anyscale Service using Ray Serve LLM, per the requirements below. These requirements are complete and final — skip the requirements interview and the confirmation step, and generate the two files directly: `serve_qwen3_6_27b_naive.py` (`LLMConfig` + `build_openai_app`) and `service_naive.yaml`.

| Requirement | Value |
|---|---|
| Model | `qwen3.6-27b` ← `Qwen/Qwen3.6-27B-FP8` (FP8), loaded from an **S3 mirror** (not Hugging Face) |
| GPU Type | L4 |
| GPU Count | 4 (`tensor_parallel_size=4`) → `g6.12xlarge` |
| Workload Type | Balanced |
| Use Case | Agentic / code generation (Claude Code, Codex, Cursor) |
| Context Length | `max_model_len=131072` (128K) |
| Availability Mode | Always-on (`min_nodes=1`) |
| Autoscaling | min=1, max=1 |
| Target Metric | n/a |
| Load Balancing | Default `RoundRobinRouter` (single replica) |
| Features | Tool calling + reasoning; no LoRA; no structured output |
| Tool calling | ON — `tool_call_parser="qwen3_coder"` + `enable_auto_tool_choice=True` |
| Reasoning parser | ON — `reasoning_parser="qwen3"` |
| Speculative decoding | OFF |

Also required:
- **Load weights from S3, not Hugging Face**: set `model_source` to your `s3://…/Qwen3.6-27B-FP8/` path — Ray Serve LLM auto-downloads a remote `s3://` source to local before loading. Avoids HF rate limits when many people deploy at once; works with the stock image (no RunAI streamer; the cluster needs S3 read access).
- Direct streaming (one endpoint serving `/v1/chat/completions`, `/v1/messages`, `/v1/responses`): set `RAY_SERVE_ENABLE_HA_PROXY=1` and `RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1` as service-level `env_vars` (NOT `runtime_env`).
- Image: stock `anyscale/ray-llm:2.56.0-py312-cu130` (no Containerfile).
- Keep 4× L4 / TP=4 — do not substitute a bigger GPU.
- Other `engine_kwargs`: `gpu_memory_utilization=0.85`, `max_num_seqs=16`, `max_num_batched_tokens=8192`, `enable_prefix_caching=True`, `trust_remote_code=True`, `limit_mm_per_prompt={"image":0,"video":0}`; `runtime_env` env `HF_HUB_ENABLE_HF_TRANSFER=1`.
- `service_naive.yaml`: `name: qwen3-6-27b-fp8-naive`; worker `g6.12xlarge` (`min_nodes:1`, `max_nodes:1`); `working_dir: .`; `applications: [{import_path: serve_qwen3_6_27b_naive:app}]`.
