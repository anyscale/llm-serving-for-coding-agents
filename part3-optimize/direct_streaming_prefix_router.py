# direct_streaming_prefix_router.py
#
# Make PrefixCacheAffinityRouter actually do prefix affinity UNDER DIRECT STREAMING on ray-llm 2.56.0.
#
# The problem (verified against the pinned ray source): under direct streaming the ingress passes the raw
# request body as `pending_request.kwargs["request_body"]` and leaves `pending_request.args` EMPTY. The
# stock router only runs its prefix logic when args is non-empty — both `_prefix_match_best_replicas`
# (the routing decision) and `on_request_routed` (the prefix-tree update) gate their text extraction on
# `pending_request.args is not None and len(pending_request.args) > 0`. So with an empty args the router
# never extracts the prompt, silently falls back to load-balancing, and does NO affinity. (An earlier
# attempt that only overrode `_extract_text_from_request` was dead code for exactly this reason — the
# guard means it's never called under direct streaming.)
#
# The fix (per review): before delegating to the stock methods, NORMALIZE the direct-streaming body into
# `args` — parse `kwargs["request_body"]` and drop a tiny stand-in (with `.messages`/`.prompt`) into
# `pending_request.args`, so the stock args-gated code path runs unchanged.
#
# Best-effort stopgap for ray-llm < 2.57 ONLY. It depends on internal method names + `args` being
# assignable; if either differs on your build it degrades gracefully to the stock behavior (round-robin —
# which is this tutorial's default anyway). Upstream fix https://github.com/ray-project/ray/pull/64328
# lands in Ray Serve LLM 2.57 — on >= 2.57 DELETE this file and use the stock PrefixCacheAffinityRouter.
#
# Usage: set request_router_class=DirectStreamingPrefixCacheRouter in deployment_config.request_router_config.
import json
from ray.llm._internal.serve.routing_policies.prefix_aware.prefix_aware_router import (
    PrefixCacheAffinityRouter,
)


class _BodyShim:
    """Minimal stand-in the stock router's args-based extraction accepts (it looks for .messages/.prompt)."""
    def __init__(self, messages=None, prompt=None):
        if messages is not None:
            self.messages = messages
        if prompt is not None:
            self.prompt = prompt


def _inject_body_into_args(pending_request):
    """If args is empty but the direct-streaming body is in kwargs['request_body'], parse it and put a
    stand-in into args so the stock prefix logic (gated on non-empty args) runs. No-op otherwise."""
    if pending_request is None or getattr(pending_request, "args", None):
        return  # normal OpenAI ingress already has the parsed request object in args
    kwargs = getattr(pending_request, "kwargs", None) or {}
    body = kwargs.get("request_body")
    if body is None:
        return
    try:
        parsed = json.loads(body) if isinstance(body, (bytes, bytearray, str)) else body
    except (ValueError, TypeError):
        return  # truncated / non-JSON body -> leave args empty -> stock fallback (round-robin)
    if not isinstance(parsed, dict):
        return
    messages, prompt = parsed.get("messages"), parsed.get("prompt")
    if messages is None and prompt is None:
        return
    shim = (_BodyShim(messages=messages, prompt=prompt),)
    try:
        pending_request.args = shim
    except Exception:
        try:
            object.__setattr__(pending_request, "args", shim)  # frozen dataclass fallback
        except Exception:
            pass  # can't normalize on this build -> stock fallback (round-robin, the safe default)


class DirectStreamingPrefixCacheRouter(PrefixCacheAffinityRouter):
    # async in the stock class — normalize the body into args, then delegate to the real prefix matcher.
    async def _prefix_match_best_replicas(self, pending_request, candidate_replicas):
        _inject_body_into_args(pending_request)
        return await super()._prefix_match_best_replicas(pending_request, candidate_replicas)

    # sync in the stock class — same normalization so the prefix tree is updated with the served prefix.
    def on_request_routed(self, pending_request, replica_id, result):
        _inject_body_into_args(pending_request)
        return super().on_request_routed(pending_request, replica_id, result)
