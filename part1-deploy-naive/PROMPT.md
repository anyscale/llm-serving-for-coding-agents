# Part 1 — deploy with a prompt

Paste this into your coding agent (Claude Code, Codex, or Cursor). The `/anyscale-workload-llm-serving` skill turns it into a Ray Serve LLM app and deploys it:

```
/anyscale-workload-llm-serving Deploy qwen3.6-27b with 4x L4 GPUs, weights located at s3://llm-guide/data/ray-serve-llm/hf_repo/Qwen3.6-27B-FP8/. No optimization needed. Use an Anyscale workspace.
```
