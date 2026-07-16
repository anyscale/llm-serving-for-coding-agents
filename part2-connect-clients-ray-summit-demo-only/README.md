# Part 2 (demo) — connect from the workspace over localhost

The quick path used in the live demo: the model runs inside an **Anyscale workspace** (Part 1's
`serve run`), and your terminal agent reaches it over an SSH tunnel to `localhost:8000`. Direct
streaming exposes the native endpoints — `/v1/messages` (Claude Code) and `/v1/responses` (Codex) — so
there's no proxy and no `pip install`. Web search comes from a local **Brave Search MCP**.

> The production pattern (a public Anyscale Service for Claude Code, Codex, and Cursor) is in
> [`../part2-connect-clients-production/`](../part2-connect-clients-production/README.md).

## One command

Each launcher opens the SSH tunnel for you (if it isn't already open), waits for the model, starts the
agent, and closes the tunnel when you quit. Just pass your workspace name. Run from **this folder** so
the Brave MCP config is picked up (`.mcp.json` for Claude Code, `.codex/config.toml` for Codex).

```bash
export BRAVE_API_KEY=…                      # web search

./claude-workspace.sh <workspace-name>      # Claude Code
./codex-workspace.sh  <workspace-name>      # Codex  (npm i -g @openai/codex)
```

Launch Claude Code first and `codex-workspace.sh` reuses the tunnel it already opened (same
`localhost:8000`). First turn is slow (reasoning model on 4× L4) — not a hang.

## What the scripts do

- Open `anyscale workspace_v2 ssh -n <workspace-name> -- -N -L 8000:localhost:8000` in the background
  (skipped if `localhost:8000` already answers) and close it on exit.
- Point the agent at `localhost:8000` with a dummy token (workspace `serve run` has no auth) and pin
  every model tier to `qwen3.6-27b`.
- Add the local **Brave Search** MCP for web search — the agents' built-in web tools don't work against
  a self-hosted model.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "workspace name required" | Pass it: `./claude-workspace.sh <workspace-name>` (or `export WORKSPACE_NAME=…`). |
| "tunnel exited early" | Wrong workspace name, or it isn't RUNNING — check `anyscale workspace_v2 list`. |
| "still not reachable after 60s" | The serve app isn't up in the workspace — see [Part 1](../part1-deploy-naive/README.md). |
| Brave MCP tools don't appear | `export BRAVE_API_KEY=…`, and launch from this folder so `.mcp.json` / `.codex/config.toml` loads. |
| Claude Code: "both token and key set" | Clear inherited `ANTHROPIC_API_KEY`; the launcher uses `ANTHROPIC_AUTH_TOKEN`. |
| Codex: tool call returns "unsupported call" | Update Codex — dispatching MCP tools over a custom (non-OpenAI) provider needs a recent build. |

Back: [Part 1 — deploy in a workspace](../part1-deploy-naive/README.md)
