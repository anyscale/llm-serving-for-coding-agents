# Part 1 — Deploy `qwen3.6-27b` on Anyscale (the naive way)

Goal: get a working OpenAI-compatible endpoint with the **least** configuration. It's deliberately
un-optimized — the point is to prove the model serves and to give you a baseline to optimize later.

**What "naive" means here:** 1× RTX PRO 6000 96GB (`g7e.4xlarge`, TP=1), single replica, default engine
settings — deliberately **highly un-optimized**. It runs on the **same GPU as the optimized Part 3 service**,
so the "before vs. after" is about the software optimizations alone, not a GPU change. It works; it's just the
wrong *shape* for a team (≈ one concurrent user, slow cold start) until you add the
[Part 3](../part3-optimize/) optimizations.

## Files
- `serve_qwen3_6_27b_naive.py` — the Ray Serve LLM app (one `LLMConfig`, built with `build_openai_app`).
- `service_naive.yaml` — the Anyscale Service config (compute + image + import path).
- `client.py` — a tiny OpenAI-SDK script to sanity-check the endpoint.

## Deploy

Run it in an **Anyscale workspace** on the image + 1× RTX PRO 6000 96GB (`g7e.4xlarge`) node from **Why this image / GPU** (below).
Set the two direct-streaming env vars on the workspace (**Dependencies → environment variables**) so
the Ray Serve controller inherits them at startup:

```
RAY_SERVE_ENABLE_HA_PROXY=1
RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1
```

Then, from a workspace terminal:

```bash
cd part1-deploy-naive
serve run serve_qwen3_6_27b_naive:app
```

`serve run` builds the app on the workspace's Ray cluster and serves it at **`http://localhost:8000`**
(OpenAI base URL `http://localhost:8000/v1`). Leave it running and sanity-check it with `client.py` below.

> To connect coding agents, deploy the same app as an Anyscale **Service** (the production target):
> `anyscale service deploy -f service_naive.yaml`, then follow Part 2 to point Claude Code, Codex, and
> Cursor at the service's public URL + token.

## Verify

```bash
# In a second workspace terminal — client.py defaults to http://localhost:8000, no token needed:
cd part1-deploy-naive
python client.py        # sends a chat completion, prints the reply
```

The first call after `serve run` (or after idle) **cold-starts** for ~2–3 min. That slowness is one of the
things [Part 3](../part3-optimize/) removes.

## Native multi-API endpoint (direct streaming)

This deployment turns on **direct streaming**, so this one endpoint speaks all three agent APIs natively —
no proxy needed:

| Path | Used by |
|---|---|
| `POST /v1/chat/completions` | Cursor (OpenAI) |
| `POST /v1/messages` | Claude Code (Anthropic) |
| `POST /v1/responses` | Codex (OpenAI Responses) |

Connect your agents in **[Part 2](../part2-connect-clients-production/)** — point Claude Code, Codex, and
Cursor **directly** at the paths above, **no proxy, no `pip install`**. (A LiteLLM-gateway alternative
also exists — handy for a service *without* direct streaming — but this repo uses the direct path.)

> **How it's enabled (and a gotcha):** direct streaming needs
> `RAY_SERVE_ENABLE_HA_PROXY=1` + `RAY_SERVE_LLM_ENABLE_DIRECT_STREAMING=1` in the Ray Serve
> **controller's** environment — the controller reads the flag at startup (`build_app.py`). A
> per-deployment `runtime_env` (e.g. `LLMConfig(runtime_env=…)`) reaches only the **replicas**, not the
> controller, so setting them there makes the app fail with *"ingress_request_router requires
> HAProxy."*
>
> In a **workspace**, set both as **workspace environment variables** (Dependencies → environment
> variables) so they apply cluster-wide and the controller inherits them at boot; if you add them to an
> already-running workspace, restart it so the controller comes back with the vars. To check, curl the
> endpoint: `/v1/messages` and `/v1/responses` should respond (not
> `404`); a `404` means direct streaming isn't active. *(Validated: all three native endpoints return
> 200.)*
>
> Deploying as a **Service** instead? Put the same two vars in `service_naive.yaml`'s top-level
> `env_vars:` — Anyscale applies those cluster-wide too.

## Why this image / GPU

- **Image `us-docker.pkg.dev/anyscale-workspace-templates/workspace-templates/llm-serving-for-coding-agents:2.56.0`**
  — a prebuilt public image (pullable with no creds) built on `anyscale/ray-llm:2.56.0-py312-cu130`, which
  upgrades the base's vLLM 0.22.0 to **0.23.0** so the native `/v1/messages` endpoint accepts Claude Code's
  request schema. Stock `ray-llm:2.56.0` (vLLM 0.22.0) works for Codex and Cursor, but 0.22.0 rejects Claude
  Code's `system` role; the older GA `ray-llm:2.55.x` ships vLLM 0.18 (too old) and fails to load Qwen3.6.
- **1× RTX PRO 6000 96GB / TP=1** (`g7e.4xlarge`) — the **same GPU Part 3 optimizes on**. Part 1 uses it as
  the un-optimized baseline; holding the hardware fixed isolates the tutorial's before/after to the software
  optimizations, which all live in [Part 3](../part3-optimize/). (Use `g7e.4xlarge` or larger, not
  `g7e.2xlarge` — its 64 GiB host RAM OOMs while loading the 27B.)

→ Next: **[Part 2 — connect Claude Code / Codex / Cursor](../part2-connect-clients-production/README.md)** (no proxy).
