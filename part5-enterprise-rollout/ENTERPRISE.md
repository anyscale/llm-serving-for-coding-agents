# Part 5 — Zero-touch rollout via Claude Code managed settings

Part 4 connects Claude Code to the LiteLLM gateway with a per-developer
launcher ([`run-claude-router.sh`](../part4-litellm-router/run-claude-router.sh)
+ a local `.env`). Part 5 removes that last per-user step: push the config
**centrally** so plain `claude` "just works" — the gateway URL, model routing,
gateway key, and the Brave MCP are all injected by Claude Code itself. Users
don't set any env vars.

This replaces the local launcher for a team/org. The launcher remains useful
for one-off / personal use or quick testing.

Before deploying, fill in the two placeholders in
[`managed-settings.json`](./managed-settings.json):

- `ANTHROPIC_BASE_URL` — your Part 4 gateway URL, from
  `anyscale service status --name litellm-router-gateway` (service ROOT, no
  `/v1`, no trailing slash)
- the `sk-...` key in `ANTHROPIC_CUSTOM_HEADERS` — the `LITELLM_MASTER_KEY`
  you set in [`../part4-litellm-router/gateway/service.yaml`](../part4-litellm-router/gateway/service.yaml)

and `BRAVE_API_KEY` in [`managed-mcp.json`](./managed-mcp.json). **Never commit
the filled-in files** — treat them like `.env`.

## What gets deployed

| File (this folder) | Deploy to (per OS below) | Purpose |
|---|---|---|
| `managed-settings.json` | `.../ClaudeCode/managed-settings.json` | gateway URL + `x-litellm-api-key` header + model tiers → `smart-router` |
| `managed-mcp.json` | `.../ClaudeCode/managed-mcp.json` | provisions the Brave Search MCP for everyone (no `--mcp-config`) |

> **Shared Brave key.** `managed-mcp.json` embeds one `BRAVE_API_KEY` that every
> machine shares — fine for a small team, but it's a **single shared search
> quota** and a plaintext key distributed to every device. For a larger org,
> provision a per-user key (e.g. have the MCP `env` read from a user-scoped
> secret) or use a Brave plan with a pooled quota sized for headcount.

**Managed-settings file paths:**

| OS | Path |
|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

(`managed-mcp.json` sits next to `managed-settings.json` in the same directory.)

## How to deploy

Managed settings are the **highest-precedence** tier — they override user
(`~/.claude/settings.json`), project (`.claude/settings.json`), local, and even
shell exports, and users **cannot** override them. Deploy via any of:

- **MDM** (Jamf, Intune, …) — push the JSON files to the paths above (plist on
  macOS, registry/file on Windows). Most common for laptop fleets.
- **Anthropic server-managed settings** — `claude.ai/admin-settings/claude-code`
  (Claude for Teams/Enterprise). Fetched at auth; good for the `env` block.
  ⚠️ Note: the exclusive `managed-mcp.json` must be a system file (MDM/config-mgmt) —
  it can't be delivered via server-managed settings.
- **Config management** (Ansible/Puppet/Chef) or direct file write with root/admin.

Verify on a user machine: run `claude`, then `/status` and check all four:

- **API base URL** shows your gateway
  (`https://...s.anyscaleuserdata.com`)
- **Model** shows `smart-router`
- **Setting sources** include `managed`
- **Login method** is the user's Claude account (NOT `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_API_KEY`) — that's the OAuth-preservation working: the user's
  subscription login stays intact for the Claude Opus fallback.

## Validate WITHOUT admin rights (no MDM, no enterprise plan)

You can prove every claim in this doc from an unprivileged laptop. Fill in the
real gateway URL + master key in `managed-settings.json` first (see above) —
every command below reads the values from that file. All commands are run from
this folder. (Validated 2026-07-21 with Claude Code 2.1.201/2.1.217 — all
steps passed.)

**Step 1 — gateway + header (plain curl, no Claude Code).** `smart-router`
only exists on the gateway, so a completion proves the URL, the
`x-litellm-api-key` header format, and the router all work:

```bash
URL=$(python3 -c 'import json;print(json.load(open("managed-settings.json"))["env"]["ANTHROPIC_BASE_URL"])')
HDR=$(python3 -c 'import json;print(json.load(open("managed-settings.json"))["env"]["ANTHROPIC_CUSTOM_HEADERS"])')
curl -sS "$URL/v1/messages" -H "$HDR" -H "content-type: application/json" \
  -d '{"model":"smart-router","max_tokens":32,"messages":[{"role":"user","content":"Reply with exactly: GATEWAY_OK"}]}'
```

Expect a `"type":"message"` response (the Qwen backend's `thinking` block is a
bonus proof it hit the local model). Re-run with a wrong key → 4xx, proving
auth is enforced.

**Step 2 — the env block, injected by real Claude Code (project scope).**
Project settings use the same schema and env-injection code path as managed
settings — only the precedence tier differs, and it needs no admin:

```bash
mkdir -p /tmp/mgd-validate/.claude
cp managed-settings.json /tmp/mgd-validate/.claude/settings.json
cd /tmp/mgd-validate
# env -u strips any shell exports (e.g. from Part 4's launcher or your rc file)
# so the settings FILE has to do all the work:
env -u ANTHROPIC_BASE_URL -u ANTHROPIC_MODEL -u ANTHROPIC_CUSTOM_HEADERS \
    -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_API_KEY \
  claude -p "Reply with exactly: SETTINGS_OK" --output-format json
```

Expect `"is_error": false` and `"modelUsage"` keyed by `"smart-router"` — the
proof the request routed through the gateway. With your claude.ai login active
you can also test the Opus fallback path:
`claude -p "use opus. Reply with exactly: OAUTH_FALLBACK_OK" ...` (same prefix).

**Step 3 — the managed-settings mechanism itself (root inside a container is
free).** This exercises the real `/etc/claude-code/` system path, the
non-overridable precedence, and the managed MCP file — no admin on your host:

```bash
podman run --rm -v "$PWD":/ent:ro node:22-slim bash -lc '
  npm install -g @anthropic-ai/claude-code >/dev/null 2>&1
  mkdir -p /etc/claude-code && cp /ent/managed-*.json /etc/claude-code/
  # A: zero-touch — the two system files alone drive the request
  ANTHROPIC_AUTH_TOKEN=dummy claude -p "Reply with exactly: MANAGED_OK" --output-format json
  # B: precedence — hostile shell env must LOSE to managed settings
  ANTHROPIC_AUTH_TOKEN=dummy ANTHROPIC_BASE_URL=http://127.0.0.1:9 ANTHROPIC_MODEL=bogus \
    claude -p "Reply with exactly: PRECEDENCE_OK" --output-format json
  # C: managed-mcp.json provisions the Brave MCP with no --mcp-config
  ANTHROPIC_AUTH_TOKEN=dummy claude mcp list'
```

Expect: A and B both succeed via `"smart-router"` (B proves shell exports are
overridden), and C prints `brave-search: ... ✔ Connected`. The dummy token is
only a headless stand-in for login — and it doubles as proof the local route
served the request: a fallback to Opus would have 401'd on it. (`docker run`
works identically; on macOS run `podman machine init && podman machine start`
once first.)

What this can't cover: the MDM / admin-console *delivery* of the files (pure
distribution — the mechanism it delivers into is what Step 3 proves) and the
optional `apiKeyHelper` per-user-key variant (needs the gateway's Postgres
virtual-keys feature).

## Why this preserves the Claude-subscription OAuth (important)

We intentionally set **only** `ANTHROPIC_BASE_URL` + `ANTHROPIC_CUSTOM_HEADERS`
and **do not** set `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY`. Per the docs,
a gateway credential var takes precedence over the saved claude.ai login *only
if you set one* — by leaving auth vars unset, each user still authenticates with
their **own Claude subscription** (used for the Claude fallback, billed to them),
while the managed base URL + header route everything through the gateway. This
is the exact hybrid Part 4's launcher uses, now centralized.

## Per-user gateway keys (recommended for teams)

`managed-settings.json` above puts a **single shared** `LITELLM_MASTER_KEY` in
the header. For per-developer keys / usage tracking / rate limits, replace the
static header with an **`apiKeyHelper`** script that fetches each user's LiteLLM
virtual key (requires the gateway's Postgres/virtual-keys feature — see the
[Part 4 README](../part4-litellm-router/README.md)):

```json
{
  "apiKeyHelper": "/usr/local/bin/litellm-key.sh",
  "env": {
    "ANTHROPIC_BASE_URL": "https://YOUR-GATEWAY-HOST.s.anyscaleuserdata.com",
    "ANTHROPIC_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "smart-router",
    "ANTHROPIC_SMALL_FAST_MODEL": "smart-router",
    "MAX_THINKING_TOKENS": "0"
  }
}
```

`litellm-key.sh` prints the user's key to stdout; Claude Code calls it at
startup and on 401, caching for 5 min (`CLAUDE_CODE_API_KEY_HELPER_TTL_MS`).
Note: `apiKeyHelper` feeds the credential Claude Code sends; if you use it for
the LiteLLM key, keep the OAuth-passthrough design in mind (a per-user LiteLLM
virtual key via `x-litellm-api-key` + OAuth in `Authorization` is cleanest —
achievable by having the helper emit the header, or keeping the static header
and using the helper only if you switch to gateway-key auth).

## Team-scoped alternative (no MDM/admin)

If you only want this for one repo (not the whole machine), commit a **project**
`.claude/settings.json` with the same `env` block — it's shared with everyone who
clones the repo, no admin rights needed (but users *can* override it, since it's
below managed in precedence).

> **⚠️ Do NOT put the gateway key in a committed `.claude/settings.json`** — that
> file goes into git history for everyone who clones the repo. Instead: commit
> the config with a **placeholder** and have each dev put the real key in their
> **git-ignored** `.claude/settings.local.json` (higher precedence), or use
> `apiKeyHelper`. Only the URL/model settings below are safe to commit.

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "env": {
    "ANTHROPIC_BASE_URL": "https://YOUR-GATEWAY-HOST.s.anyscaleuserdata.com",
    "ANTHROPIC_CUSTOM_HEADERS": "x-litellm-api-key: Bearer <LITELLM_MASTER_KEY>",
    "ANTHROPIC_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "smart-router",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "smart-router",
    "ANTHROPIC_SMALL_FAST_MODEL": "smart-router",
    "MAX_THINKING_TOKENS": "0"
  }
}
```
Put the real key in git-ignored `.claude/settings.local.json`:
```json
{ "env": { "ANTHROPIC_CUSTOM_HEADERS": "x-litellm-api-key: Bearer sk-...realkey..." } }
```
For MCP at the repo scope, commit a `.mcp.json` with the `brave-search` block
(same caveat — keep the Brave key out of the committed file).

## What CANNOT be centralized

- **Cloud surfaces** (Claude Code on Slack / claude.ai web) ignore both
  server-managed and system-file settings — they talk to `api.anthropic.com`
  directly. Only the CLI / IDE / desktop honor these files.
- **Static shared API keys** in managed settings are discouraged — prefer
  `apiKeyHelper` for anything per-user or rotatable.

## Precedence recap (highest → lowest)

1. **Managed** settings (this doc) — non-overridable
2. Command-line flags (per session)
3. `.claude/settings.local.json` (personal, gitignored)
4. `.claude/settings.json` (project, committed)
5. `~/.claude/settings.json` (user)
6. Shell exports (what Part 4's `run-claude-router.sh` uses)
