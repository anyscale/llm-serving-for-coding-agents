# Part 2 — Connect your coding agent to the served model

Two paths, split by how each agent reaches the model:

| Agent | How it connects | In the demo |
|---|---|---|
| **Claude Code** | workspace model over an SSH tunnel → `localhost:8000` (`/v1/messages`) | **live** — with Brave web-search MCP |
| **Cursor** | public Anyscale Service (`/v1/chat/completions`); its cloud can't reach `localhost` | **show-only** |

Both endpoints run **direct streaming**, which exposes vLLM's native `/v1/messages` (Anthropic) and `/v1/chat/completions` (OpenAI) — no proxy, no `pip install`.

## Claude Code (live) — workspace model + web search

Prereqs: the model is served in a workspace on `localhost:8000`; `export BRAVE_API_KEY=…`.

1. Open the tunnel (leave it running):
   ```bash
   anyscale workspace_v2 ssh -n <workspace> -- -N -L 8000:localhost:8000
   ```
2. Launch from this folder (so `.mcp.json` loads):
   ```bash
   cd part2-connect-clients-direct && ./claude-workspace.sh
   ```

`claude-workspace.sh` points Claude Code at `localhost:8000` with a dummy token and pins every model tier to `qwen3.6-27b`. `.mcp.json` adds a local **Brave Search** MCP server for web search — Anthropic's built-in `WebSearch`/`WebFetch` don't work on a self-hosted model. First turn is slow (reasoning model on 4× L4) — not a hang.

## Cursor (show-only) — public service

Cursor can't use the workspace tunnel, so it's shown against the pre-deployed public service — see **[`cursor-setup.md`](./cursor-setup.md)**.

## Why the split

- **Claude Code runs locally** → hits `localhost:8000` (the tunneled workspace) directly; no public endpoint needed.
- **Cursor proxies through its own cloud** → refuses `localhost`/private IPs (`Access to private networks is forbidden`), so it needs a public HTTPS endpoint. A tunnel doesn't help — it only opens the port on *your* laptop.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `claude-workspace.sh`: "not reachable" | Workspace down or tunnel closed — (re)open the tunnel. |
| Brave MCP tools don't appear | `export BRAVE_API_KEY=…`, and launch from this folder so `.mcp.json` loads. |
| Claude Code: "both token and key set" | Clear inherited `ANTHROPIC_API_KEY`; the launcher uses `ANTHROPIC_AUTH_TOKEN`. |
| Cursor: "Access to private networks is forbidden" | Expected for `localhost` — use the public service URL. |

Back: [Part 1 — deploy with direct streaming](../part1-deploy-naive/README.md)
