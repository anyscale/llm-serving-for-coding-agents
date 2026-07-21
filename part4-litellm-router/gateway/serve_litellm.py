# serve_litellm.py
# -----------------------------------------------------------------------------
# Runs the LiteLLM proxy as an Anyscale Service via Ray Serve.
#
# WHY A REVERSE PROXY (and not @serve.ingress):
# `@serve.ingress(app)` PICKLES the FastAPI app to ship it to replicas. With the
# fastapi/starlette versions in the Anyscale Ray image, a decorated FastAPI app
# holds a thread lock and fails to pickle ("cannot pickle '_thread.lock'
# object"). Pinning an older fastapi fixes that but breaks LiteLLM's streaming
# dep (sse-starlette needs starlette>=0.49.1) — dependency whack-a-mole.
#
# Robust, version-independent approach: launch the real `litellm` proxy on an
# internal localhost port inside each replica (its own uvicorn runs LiteLLM's
# normal startup/lifespan), and make a plain Serve deployment reverse-proxy all
# HTTP — including streaming SSE — to it. Nothing non-picklable crosses Serve.
#
# The LiteLLM proxy exposes:
#   - OpenAI-compatible:   POST /v1/chat/completions, /v1/completions, /v1/models
#   - Anthropic-compatible: POST /v1/messages   <-- what Claude Code calls
# -----------------------------------------------------------------------------
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys

import httpx
from ray import serve
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

CONFIG_PATH = os.environ.get(
    "LITELLM_CONFIG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
)

# Hop-by-hop headers that must not be forwarded/echoed by a proxy.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "content-encoding", "host",
}


_THINKING_BLOCK_TYPES = {"thinking", "redacted_thinking"}


def _is_tool_result_turn(msg) -> bool:
    """True if `msg` is a user turn carrying tool_result blocks (an active
    tool-use continuation)."""
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    content = msg.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _strip_thinking_blocks(body: bytes) -> bytes:
    """Drop `thinking`/`redacted_thinking` blocks from PRIOR assistant turns,
    but PRESERVE them on an assistant turn that is immediately followed by a
    tool_result.

    Why: with the native Anthropic Qwen passthrough, thinking blocks are signed
    by Qwen, not real Anthropic — so if a prior-turn Qwen thinking block reaches
    the Opus backend it 400s (bad signature). Per the Anthropic API, prior-turn
    thinking is OPTIONAL (safe to omit), so we strip it. BUT thinking inside a
    tool-use loop is MANDATORY and must be unmodified (omitting it 400s:
    "thinking blocks in the latest assistant message cannot be modified"), so we
    leave those intact — the tool continuation goes back to the same backend.
    Cheap: only called when the raw body contains the substring `"thinking"`.
    """
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001 -- non-JSON body: forward untouched
        return body
    messages = data.get("messages")
    if not isinstance(messages, list):
        return body
    changed = False
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        # Preserve thinking required by an active tool-use loop (next turn is a
        # tool_result); strip it everywhere else.
        if _is_tool_result_turn(messages[i + 1] if i + 1 < len(messages) else None):
            continue
        kept = [
            b for b in content
            if not (isinstance(b, dict) and b.get("type") in _THINKING_BLOCK_TYPES)
        ]
        if len(kept) != len(content):
            changed = True
            # Anthropic rejects empty content — keep a placeholder if a turn was
            # thinking-only (rare).
            msg["content"] = kept or [{"type": "text", "text": "(thinking omitted)"}]
    return json.dumps(data).encode("utf-8") if changed else body


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@serve.deployment(
    ray_actor_options={"num_cpus": 1},
    autoscaling_config=dict(
        min_replicas=1,   # always-on gateway: no cold start for the router itself
        max_replicas=3,   # scale out under concurrent Claude Code sessions
        target_ongoing_requests=32,
    ),
    max_ongoing_requests=64,
)
class LiteLLMRouter:
    """Reverse-proxies to a local `litellm` proxy process (OpenAI + Anthropic)."""

    async def __init__(self):
        self._port = _free_port()
        self._base = f"http://127.0.0.1:{self._port}"

        litellm_bin = shutil.which("litellm") or os.path.join(
            os.path.dirname(sys.executable), "litellm"
        )
        env = os.environ.copy()
        env["CONFIG_FILE_PATH"] = CONFIG_PATH
        # Single uvicorn worker: one proxy per replica, Serve handles scaling.
        self._proc = subprocess.Popen(
            [
                litellm_bin,
                "--config", CONFIG_PATH,
                "--host", "127.0.0.1",
                "--port", str(self._port),
                "--num_workers", "1",
            ],
            env=env,
        )

        # Long timeouts: agent turns + Claude fallback can be slow. No read
        # timeout so streaming responses aren't cut off.
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(None, connect=10.0),
        )

        # Wait for the proxy to become ready (model load is instant here — it's
        # just a gateway — but the process still needs a few seconds to boot).
        last_err = None
        for _ in range(180):
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"litellm proxy exited early with code {self._proc.returncode}"
                )
            try:
                r = await self._client.get("/health/readiness")
                if r.status_code == 200:
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
            await asyncio.sleep(1)
        else:
            raise RuntimeError(f"litellm proxy did not become ready: {last_err}")

    async def __call__(self, request: Request) -> StreamingResponse:
        # Forward method, full path, query, headers, and body upstream. Keeping
        # the client's Authorization + anthropic-beta headers intact is what
        # makes per-user Claude OAuth passthrough work.
        url = httpx.URL(
            path=request.url.path,
            query=request.url.query.encode("utf-8"),
        )
        fwd_headers = [
            (k, v) for k, v in request.headers.raw
            if k.decode("latin-1").lower() not in _HOP_BY_HOP
        ]
        body = await request.body()
        if body and b'"thinking"' in body:
            body = _strip_thinking_blocks(body)
        upstream_req = self._client.build_request(
            request.method, url, headers=fwd_headers, content=body
        )
        try:
            upstream_resp = await self._client.send(upstream_req, stream=True)
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {"error": {"message": f"gateway upstream error: {e}", "type": "bad_gateway"}},
                status_code=502,
            )

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in _HOP_BY_HOP
        }
        return StreamingResponse(
            upstream_resp.aiter_raw(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            background=BackgroundTask(upstream_resp.aclose),
        )

    async def __del__(self):
        # Serve drains in-flight replica requests before teardown; here we just
        # shut the local litellm proxy down gracefully (SIGTERM, brief wait,
        # then SIGKILL) so it isn't left orphaned. Its stdout/stderr are
        # inherited by the replica, so its logs already show up in Anyscale logs.
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001 -- didn't exit in time
                proc.kill()
        except Exception:  # noqa: BLE001
            pass


# Entrypoint referenced by service.yaml: `serve_litellm:entrypoint`
entrypoint = LiteLLMRouter.bind()
