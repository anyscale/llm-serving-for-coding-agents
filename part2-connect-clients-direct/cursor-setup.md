# Connect Cursor to `qwen3.6-27b` (public service)

> **Demo note:** in the training this is **shown, not run live** — it's how you'd wire Cursor to the
> pre-deployed public Anyscale Service.

Cursor is **OpenAI-compatible** and routes calls through **its own cloud**, so it always needs a
**publicly reachable** endpoint — it can't reach a `localhost` / workspace tunnel. Point it at the
public service's `/v1` endpoint (direct streaming enabled, as in Part 1).

## Configure

**Cursor Settings → Models** (→ *OpenAI API Key*):

1. Enable **"Override OpenAI Base URL"** and set it to the service URL **with `/v1`**:
   ```
   https://YOUR-ANYSCALE-SERVICE-HOST.s.anyscaleuserdata.com/v1
   ```
2. Set the **OpenAI API Key** to the service's **bearer token** (`anyscale service status -n <service>`
   → `query_auth_token`).
3. **Add a custom model** named exactly `qwen3.6-27b`, enable it, and disable the default models so
   requests route to yours.
4. Click **Verify** — Cursor pings the endpoint to confirm URL + key.

Open Cursor chat, pick `qwen3.6-27b`, send "say hi in 3 words" → a reply confirms it.

## Gotchas
- **Public URL required** — `localhost` / the workspace tunnel won't work from Cursor's cloud
  (*"Access to private networks is forbidden"*). Use the public Service URL + token.
- **Exact model id** — the server only knows `qwen3.6-27b`; any other id errors.
- **Feature coverage** — custom OpenAI models drive Cursor **Chat/Ask** reliably. **Tab** (autocomplete)
  and parts of **Agent/Composer** are tuned for Cursor's own models and may be limited.
- **Tool calling** is server-side (`tool_call_parser=qwen3_coder`); if tool calls come back as raw text,
  that parser would need adjusting on the service.
- **Cold start / 300s cap** — warm the service first (send one quick request); a single request past
  300s hits the Anyscale ALB timeout (`504`).
