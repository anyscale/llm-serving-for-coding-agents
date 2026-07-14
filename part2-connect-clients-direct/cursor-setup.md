# Connect Cursor to the served model (public service)

> **Demo note:** shown, not run live — this is how you'd point Cursor at the pre-deployed public Anyscale Service.

Cursor routes calls through its own cloud, so it needs a **public HTTPS** endpoint — not `localhost` / the workspace tunnel. Point it at the service's `/v1`.

**Get the URL + token:** in the Anyscale console, open **Services → your service → Query** and copy the base URL and the bearer token from the sample request.

**Cursor Settings → Models → OpenAI API Key:**

1. Enable **Override OpenAI Base URL** → the base URL with `/v1` appended (e.g. `https://YOUR-SERVICE-HOST.s.anyscaleuserdata.com/v1`).
2. Set **OpenAI API Key** → the bearer token from the Query panel.
3. **Add a custom model** named `qwen3.6-27b` — this must match the `model_id` set in the serve app's `LLMConfig`; it's the only id the server answers to. Enable it, and disable the default models.
4. **Verify** → then in chat pick `qwen3.6-27b` and send "say hi in 3 words".

**Gotchas**
- `localhost` / tunnel → `Access to private networks is forbidden`; use the public URL.
- Model name must equal the `LLMConfig` `model_id` (`qwen3.6-27b`) exactly.
- Chat/Ask work well; Tab and parts of Agent/Composer are tuned for Cursor's own models.
- Warm the service first — one request past 300s hits the Anyscale ALB `504` timeout.
