# Part 2 — Connect Claude Code, Codex, and Cursor

Use the `qwen3.6-27b` service from Part 1 directly from your coding agents. There is no proxy and no
Python package to install. All agents read the same `.env` file.

```
Claude Code -> /v1/messages
Codex      -> /v1/responses
Cursor     -> /v1/chat/completions
              |
              v
Anyscale qwen3.6-27b service with direct streaming enabled
```

## 1. Configure

```bash
cd part2-connect-clients-direct
cp .env.example .env
$EDITOR .env
```

Set these values in `.env`:

- `ANYSCALE_BASE_URL`: your service URL ending in `/v1`
- `ANYSCALE_API_KEY`: your Anyscale bearer token
- `ANYSCALE_MODEL`: the served model id, usually `qwen3.6-27b`

Before launching agents, confirm direct streaming is enabled. These routes should respond instead of
returning `404`:

- `/v1/chat/completions`
- `/v1/messages`
- `/v1/responses`

If `/v1/messages` or `/v1/responses` returns `404`, check the direct-streaming `env_vars` in
`../part1-deploy-naive/service_naive.yaml`.

## 2. Launch

| Agent | How to run |
|---|---|
| Claude Code | `./run-claude-direct.sh` |
| Codex | `./run-codex-direct.sh` |
| Cursor | Follow [`cursor-setup.md`](./cursor-setup.md) |

You can pass normal CLI arguments through the launchers:

```bash
./run-claude-direct.sh -p "explain this repo"
./run-codex-direct.sh "explain this repo"
```

## 3. Why This Works

Part 1 enables direct streaming, which exposes vLLM's native routes behind HAProxy:

- Claude Code uses the Anthropic-compatible `/v1/messages` route.
- Codex uses the OpenAI Responses `/v1/responses` route.
- Cursor uses the OpenAI Chat Completions `/v1/chat/completions` route.

The Codex launcher also disables extra client features by default so requests stay close to standard
tool calls. You can loosen those flags in `run-codex-direct.sh` if your Codex build and service config
support them.

## Notes for qwen

- Anthropic server-side tools such as `WebSearch` and `WebFetch` are not available; use an MCP search
  tool instead.
- Keep MCP servers minimal because every request includes tool schemas.
- For more reliable tool calls, enable reasoning in the Part 1 service config with
  `chat_template_kwargs`.
- Warm the service with a small request before long sessions. A single request past 300 seconds can hit
  the Anyscale load-balancer timeout.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `404` on `/v1/messages` or `/v1/responses` | Direct streaming is not active; check `../part1-deploy-naive/service_naive.yaml`. |
| `401` | Refresh `ANYSCALE_API_KEY` from Anyscale. |
| `404 / model not found` | Make sure `ANYSCALE_MODEL` matches the served model id. |
| Claude Code warns "both token and key set" | Clear any inherited `ANTHROPIC_API_KEY`; the launcher uses `ANTHROPIC_AUTH_TOKEN`. |
| First request times out | The service is likely cold-starting; wait a few minutes and retry. |

Back: [Part 1 — deploy with direct streaming](../part1-deploy-naive/README.md)
