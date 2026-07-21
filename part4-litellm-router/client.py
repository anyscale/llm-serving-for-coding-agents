"""client.py — smoke-test the LiteLLM router gateway (OpenAI SDK).

What this CAN test with just the gateway key:
  1. anyscale-qwen3.6-27b -> your Anyscale LLM service
  2. smart-router  -> auto complexity routing (a benign task stays local)

What it CANNOT test here:
  - claude-opus-4-8 (and smart-router when it escalates a hard task) route to
    Anthropic, which needs each user's Claude OAuth token. Only Claude Code
    forwards that token — from this plain client you'll get an auth error on the
    Claude path. That's expected; test Claude routing from Claude Code itself.

Usage (reads the same .env as run-claude-router.sh):
  set -a && source .env && set +a
  python client.py
"""
import os

from openai import OpenAI

BASE_URL = os.environ["GATEWAY_BASE_URL"].rstrip("/")
if not BASE_URL.endswith("/v1"):
    BASE_URL += "/v1"
API_KEY = os.environ["LITELLM_MASTER_KEY"]

# The OpenAI SDK sends the key as `Authorization: Bearer ...`, which LiteLLM
# accepts as the gateway key (equivalent to the `x-litellm-api-key` header used
# in the README curls).
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def ask(model: str, prompt: str) -> None:
    print(f"\n=== model={model} ===")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
    )
    print(resp.choices[0].message.content)
    # LiteLLM echoes the model that actually served the request.
    print(f"[served by: {resp.model}]")


if __name__ == "__main__":
    # 1. Primary local model.
    ask("anyscale-qwen3.6-27b", "Rename this variable: `x = 1`. Reply with the new line only.")

    # 2. Smart router with a simple task -> stays on the local model (no OAuth
    #    needed). A hard task could escalate to Claude and fail here for lack of
    #    an OAuth token — keep this prompt simple.
    ask("smart-router", "Rename the variable `n` to `count` in `for n in range(10): pass`.")

    print(
        "\nNote: to test claude-opus-4-8 / Claude fallback, use Claude Code "
        "(it forwards your Claude OAuth token). This key-only client can't."
    )
