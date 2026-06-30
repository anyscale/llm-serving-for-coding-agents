# Part 2a — Connect Claude Code, Codex, and Cursor (direct, no proxy)

Point all three coding agents at your `qwen3.6-27b` service — with **no proxy and no `pip install`**.
Each agent talks **straight to the service's native endpoint**, which works because **Part 1 enables
direct streaming**:

```
Claude Code ─Anthropic /v1/messages──┐
Codex ───────OpenAI  /v1/responses───┼─►  Anyscale qwen3.6-27b service   (direct streaming:
Cursor ──────OpenAI  /v1/chat────────┘     native vLLM app behind HAProxy)   one endpoint, three APIs)
```

## Direct vs. a proxy gateway

| | **Direct (this repo)** | **LiteLLM gateway (alternative)** |
|---|---|---|
| Local proxy | **none** | yes (`localhost:4000`) |
| `pip install` | **nothing** | `litellm[proxy]` |
| Needs direct streaming on the service | ✅ yes (Part 1 enables it) | no — it translates |
| Moving parts | fewer → simpler, lower latency | more |

**Rule of thumb:** when the service has direct streaming on (Part 1 does), the **direct** path is the
simplest. A LiteLLM-gateway is the fallback for a service that only exposes Chat Completions.

## 1. One-time setup

```bash
cd part2a-connect-clients-direct
cp .env.example .env && $EDITOR .env     # paste your service URL (+/v1), token, model id

./smoke-test-direct.sh                    # pings all THREE native endpoints (cold start ~2-4 min)
```

`smoke-test-direct.sh` is the gate: it must return **HTTP 200** on `/v1/chat/completions`,
`/v1/messages`, **and** `/v1/responses`. A `404` on the last two means direct streaming isn't active on
your service — check the `env_vars` in `../part1-deploy-naive/service_naive.yaml` (see Part 1's README).

## 2. Launch an agent

| Agent | Command | What it sets |
|---|---|---|
| **Claude Code** | `./run-claude-direct.sh` | `ANTHROPIC_BASE_URL` = service root, `ANTHROPIC_AUTH_TOKEN` = your token, drops you into `claude`. Args pass through (`./run-claude-direct.sh -p "explain this repo"`). |
| **Codex** | `./run-codex-direct.sh` | Reads `.env` and configures an inline `model_provider` at `…/v1` (`wire_api=responses`) via `-c` flags — your `~/.codex` is left untouched. Needs `npm i -g @openai/codex`. |
| **Cursor** | see [`cursor-setup.md`](./cursor-setup.md) | Cursor is OpenAI-native — point it straight at `…/v1` (it always connects directly). |

No proxy is started or torn down — the agents connect to the public service directly. All three read
their connection settings from the **shared `.env`** (the single source of truth) — there's no per-agent
config file to keep in sync.

## 3. Why this works (no proxy needed)

Direct streaming puts vLLM's **native** ASGI app behind HAProxy, so the service exposes vLLM's own
`/v1/messages` (Anthropic) and `/v1/responses` (OpenAI Responses) routes alongside `/v1/chat/completions`.
Those native routes are **more permissive** than `ray.llm`'s OpenAI ingress, so two quirks a translating
proxy would have to normalize **don't apply here**:

- Codex's **duplicate system messages** — the native Responses route accepts them (a proxy would have to
  fold them).
- Non-`function` tools — `run-codex-direct.sh` still passes `features.*=false` **defensively** (keeping
  Codex to shell / `apply_patch` / `update_plan`), but you can drop them if your Codex build behaves.

## 4. Running on qwen instead of Claude — practical caveats

- **`WebSearch`/`WebFetch` won't work** — Anthropic *server-side* tools; use a search **MCP** instead.
- **Trim MCP servers** — every request ships all tool schemas; qwen is slower than Claude and can loop.
- **Tool calling is more reliable with reasoning on** — the direct path has no proxy to inject
  `enable_thinking` per request, so it follows the model's server-side default; force it in Part 1's
  serve config (`chat_template_kwargs`) if you need it always on.
- **Cold start & the 300s ALB cap** — always warm with `smoke-test-direct.sh` first; a single request
  past 300s hits the Anyscale load-balancer timeout (`504`).

## Files
| File | Purpose |
|---|---|
| `.env.example` → `.env` | **Edit `.env`** — service URL (`…/v1`), token, model id. **Shared by all three agents.** `.env` is gitignored. |
| `run-claude-direct.sh` | Launches Claude Code against native `/v1/messages` (no proxy). |
| `run-codex-direct.sh` | Launches Codex against native `/v1/responses` (no proxy); all settings from `.env`. |
| `cursor-setup.md` | Cursor instructions (points directly at `…/v1`). |
| `smoke-test-direct.sh` | Pings all three native endpoints — your "is direct streaming on?" check. |

## Troubleshooting
| Symptom | Fix |
|---|---|
| `404` on `/v1/messages` or `/v1/responses` | Direct streaming not active — check the `env_vars` in `../part1-deploy-naive/service_naive.yaml`. |
| `401` | Wrong/expired `ANYSCALE_API_KEY` — refresh from Anyscale → Query. |
| `404 / model not found` | `ANYSCALE_MODEL` ≠ served id — check `curl $BASE/models`. |
| Claude Code warns "both token and key set" | The launcher unsets `ANTHROPIC_API_KEY`; clear any inherited one in your shell. |
| Smoke test times out | Service cold-starting — re-run, wait a few min. |

→ Back: [**Part 1 — deploy (direct streaming on)**](../part1-deploy-naive/README.md).
