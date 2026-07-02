# Connect Cursor to `qwen3.6-27b` (direct)

Cursor is **OpenAI-compatible** and routes calls through **its own cloud**, so it always points at a
**publicly reachable** endpoint. This guide assumes the service has direct streaming enabled, as in
Part 1. Point Cursor straight at the Anyscale service's `/v1` endpoint.

## Configure

**Cursor Settings → Models** (→ *OpenAI API Key*):

1. Enable **"Override OpenAI Base URL"** and set it to your service URL **with `/v1`**:
   ```
   https://YOUR-ANYSCALE-SERVICE-HOST.s.anyscaleuserdata.com/v1
   ```
2. Set the **OpenAI API Key** to your Anyscale **bearer token** (same one in `.env`).
3. **Add a custom model** named exactly `qwen3.6-27b`, enable it, and disable the default models so
   requests route to yours.
4. Click **Verify** — Cursor pings the endpoint to confirm URL + key.

Open Cursor chat, pick `qwen3.6-27b`, send "say hi in 3 words" → a reply confirms it.

## Gotchas
- **Public URL required** — `localhost` won't work from Cursor's cloud. Use the Anyscale Service URL + token.
- **Exact model id** — the server only knows `qwen3.6-27b`; any other id errors.
- **Feature coverage** — custom OpenAI models drive Cursor **Chat/Ask** reliably. **Tab** (autocomplete)
  and parts of **Agent/Composer** are tuned for Cursor's own models and may be limited.
- **Tool calling** is server-side (`tool_call_parser=qwen3_coder`); if tool calls come back as raw text,
  that parser would need adjusting on the service.
- **Cold start / 300s cap** — warm the service first (send one quick request); a single request past
  300s hits the Anyscale ALB timeout (`504`).
