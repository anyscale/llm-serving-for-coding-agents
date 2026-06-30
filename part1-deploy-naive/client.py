"""client.py — OpenAI-compatible smoke client for the Qwen3.6-27B endpoint.

Works against either service in this tutorial (naive or optimized) — just set the URL + token.

Local (inside a workspace, after `serve run`):
    python client.py                      # defaults to http://localhost:8000

Against a deployed Anyscale Service (uses the same ANYSCALE_* vars as Part 2's .env):
    export ANYSCALE_BASE_URL="https://YOUR-HOST.s.anyscaleuserdata.com/v1"   # include /v1
    export ANYSCALE_API_KEY="your-bearer-token"
    python client.py
"""
import os

from openai import OpenAI

# Accept the tutorial-wide ANYSCALE_* names (Part 2 .env) or the plain ones; localhost by default.
API_KEY = os.environ.get("ANYSCALE_API_KEY") or os.environ.get("API_KEY", "FAKE_KEY")
BASE_URL = os.environ.get("ANYSCALE_BASE_URL") or os.environ.get("BASE_URL", "http://localhost:8000")
MODEL = os.environ.get("ANYSCALE_MODEL") or os.environ.get("MODEL", "qwen3.6-27b")

# ANYSCALE_BASE_URL already ends in /v1; a local URL doesn't — normalize to exactly one /v1.
_base = BASE_URL.rstrip("/")
if not _base.endswith("/v1"):
    _base += "/v1"
client = OpenAI(base_url=_base, api_key=API_KEY)


def get_reasoning(message):
    """Safely read the reasoning trace. It's absent when thinking is OFF, and the
    typed SDK object raises on the missing attr — so read it off pydantic extras."""
    extra = getattr(message, "model_extra", None) or {}
    return getattr(message, "reasoning_content", None) or extra.get("reasoning_content") or extra.get("reasoning")


def chat_thinking_off():
    """Direct answer, no <think> trace — good for quick/simple steps."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Write a Python one-liner to flatten a list of lists."}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        max_tokens=512,
    )
    print("=== thinking OFF ===")
    print("reasoning:", get_reasoning(resp.choices[0].message))
    print("answer:", resp.choices[0].message.content)


def chat_thinking_on():
    """Step-by-step reasoning in reasoning_content — good for hard coding problems."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Find and fix the bug: def add(a, b): return a - b"}],
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
        max_tokens=2048,
    )
    print("\n=== thinking ON ===")
    print("reasoning:", (get_reasoning(resp.choices[0].message) or "")[:400], "...")
    print("answer:", resp.choices[0].message.content)


def tool_calling():
    """Agentic tool calling (parser=qwen3_coder, enable_auto_tool_choice=True).

    If the tool call comes back as raw text in `content` instead of `tool_calls`,
    the tool-call parser is wrong for this model — switch to "hermes" in the serve file.
    """
    tools = [{
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command and return stdout.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string", "description": "command to run"}},
                "required": ["cmd"],
                "additionalProperties": False,
            },
        },
    }]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "List the Python files in the current directory."}],
        tools=tools,
        tool_choice="auto",
        max_tokens=512,
    )
    msg = resp.choices[0].message
    print("\n=== tool calling ===")
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"tool: {tc.function.name}  args: {tc.function.arguments}")
    else:
        print("no tool call (check tool_call_parser); content:", msg.content)


def streaming():
    """Stream reasoning, then the final answer."""
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Implement binary search in Python and explain the invariant."}],
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
        stream=True,
        max_tokens=2048,
    )
    print("\n=== streaming ===")
    for chunk in stream:
        delta = chunk.choices[0].delta
        # vLLM 0.18+ may emit reasoning under `reasoning` (typed SDK hides it) — read extras too.
        extra = getattr(delta, "model_extra", None) or {}
        piece = getattr(delta, "reasoning_content", None) or extra.get("reasoning") or extra.get("reasoning_content")
        if piece:
            print(piece, end="", flush=True)
        if delta.content:
            print(delta.content, end="", flush=True)
    print()


if __name__ == "__main__":
    chat_thinking_off()
    chat_thinking_on()
    tool_calling()
    streaming()
