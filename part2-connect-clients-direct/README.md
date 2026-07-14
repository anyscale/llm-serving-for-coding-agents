# Part 2 — Connect your coding agent to the served model

Two paths, reflecting how each agent reaches a model:

- **Claude Code → the model in a workspace, over `localhost`** *(live)*. Claude Code runs on your
  machine, so it talks to the workspace's `localhost:8000` through an SSH tunnel. Web search comes
  from a local **Brave Search MCP** server.
- **Cursor → a public Anyscale Service** *(shown, not run live)*. Cursor routes every call through
  *its own cloud*, so it can't reach `localhost` — it needs a public HTTPS endpoint.

```
Claude Code ──/v1/messages────────────▶ localhost:8000  (workspace model, via SSH tunnel)   ← live
Cursor      ──/v1/chat/completions─────▶ https://….anyscaleuserdata.com/v1  (public service) ← show-only
```

Both endpoints have **direct streaming** on, which exposes vLLM's native `/v1/messages` (Anthropic)
and `/v1/chat/completions` (OpenAI) routes — no proxy, no `pip install`.

## Claude Code (live) — workspace model + Brave web search

Prereqs:
- The `qwen3.6-27b` model is served inside a workspace on `localhost:8000` (direct streaming on).
- A Brave Search API key exported in your shell: `export BRAVE_API_KEY=…`

1. Open the SSH tunnel to the workspace — leave it running in its own terminal:
   ```bash
   anyscale workspace_v2 ssh -n <workspace> -- -N -L 8000:localhost:8000
   ```
2. From this folder, launch Claude Code:
   ```bash
   cd part2-connect-clients-direct
   ./claude-workspace.sh
   ```

`claude-workspace.sh` points Claude Code at `localhost:8000` (native `/v1/messages`), uses a dummy
token (the workspace serve has no auth), and pins every model tier to `qwen3.6-27b`. Launching **from
this folder** is what makes Claude Code pick up **`.mcp.json`** — a local (stdio) **Brave Search** MCP
server — so the model gets web search (Anthropic's built-in `WebSearch`/`WebFetch` aren't available on
a self-hosted model). Ask it to look something up online to see the MCP tools fire.

## Cursor (show-only) — public service

Cursor can't use the workspace/localhost path, so it's demonstrated against the **pre-deployed public
service**. Walk through **[`cursor-setup.md`](./cursor-setup.md)**: override the OpenAI base URL to the
service's `/v1`, set the bearer token, add a custom model `qwen3.6-27b`, and **Verify**.

## Why the split

- **Claude Code is a local process** → `localhost:8000` (the tunneled workspace) works directly; no
  public endpoint needed.
- **Cursor proxies through its own servers** → they refuse `localhost`/private IPs
  (*"Access to private networks is forbidden"*). It needs a **publicly reachable HTTPS** endpoint, so
  it uses the Anyscale Service. An SSH tunnel doesn't help — it only exposes the port on *your* laptop.

## Notes
- **Brave MCP** — `.mcp.json` runs `@brave/brave-search-mcp-server` via `npx` (stdio, local). Requires
  `BRAVE_API_KEY` in the shell you launch from. Keep MCP servers minimal — every request carries the
  tool schemas.
- **Latency** — a reasoning model on 4× L4 pauses to think; the first turn can take tens of seconds.
  Not a hang.
- **Public service cold start** — warm it with one small request first; a single request past 300s
  hits the Anyscale ALB timeout (`504`).

## Troubleshooting
| Symptom | Fix |
|---|---|
| `claude-workspace.sh`: "not reachable" | Workspace down or tunnel closed — (re)open the SSH tunnel. |
| Brave MCP tools don't show up | `export BRAVE_API_KEY=…` before launching, and launch from this folder so `.mcp.json` loads. |
| Claude Code warns "both token and key set" | Clear any inherited `ANTHROPIC_API_KEY`; the launcher uses `ANTHROPIC_AUTH_TOKEN`. |
| Cursor: "Access to private networks is forbidden" | Expected for `localhost` — Cursor needs the public service URL, not the tunnel. |

Back: [Part 1 — deploy with direct streaming](../part1-deploy-naive/README.md)
