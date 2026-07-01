# direct_streaming_prefix_router.py
#
# Portable fix so PrefixCacheAffinityRouter WORKS under direct streaming.
#
# Why this is needed: under direct streaming the ingress forwards the RAW request body (a `bytes`/`str`,
# not a parsed Chat/Completion object) to the request router. WHERE it lands is version-dependent:
#   - ray-llm 2.56.0 (pinned here): as a KWARG — the ingress calls
#     `choose_replica(request_body=<bytes>, body_truncated=...)`, so the body is in
#     `pending_request.kwargs["request_body"]`, NOT `pending_request.args`.
#   - some paths/versions put the raw body in `pending_request.args` instead.
# Stock `PrefixCacheAffinityRouter._extract_text_from_request` only scans `args` for an object with
# `.messages`/`.prompt`, so on 2.56.0 it finds nothing and raises
# `ValueError: No request with message or prompt attribute found in pending_request.args`,
# which crashes the proxy routing loop -> every request hangs (curl HTTP 000). See
# spec_decode_validation/bug_report_direct_streaming_prefix_router.md and ray#64326.
#
# This subclass overrides only `_extract_text_from_request` to scan BOTH `args` and `kwargs` (incl.
# `kwargs["request_body"]`), parse the raw bytes/str body, and degrade gracefully (return None ->
# load-balanced fallback) instead of raising. It's a proper custom router class (imported by the proxy
# from your working_dir), so no site-packages edits.
#
# Upstream fix: https://github.com/ray-project/ray/pull/64328 — landing in Ray Serve LLM 2.57. Once you
# run ray-llm >= 2.57 you can DELETE this file and use the stock ray.serve.llm PrefixCacheAffinityRouter
# directly under direct streaming (this subclass is just the stopgap until then).
#
# Usage: set request_router_class=DirectStreamingPrefixCacheRouter in deployment_config.request_router_config.
import json
from ray.llm._internal.serve.routing_policies.prefix_aware.prefix_aware_router import (
    PrefixCacheAffinityRouter,
)


class DirectStreamingPrefixCacheRouter(PrefixCacheAffinityRouter):
    def _extract_text_from_request(self, pending_request):
        # Gather every place the request/body can arrive, across ray-llm versions:
        #   - OpenAI ingress: a parsed Chat/Completion object in .args (has .messages / .prompt)
        #   - Direct streaming on ray-llm 2.56.0: raw body in .kwargs["request_body"]  <-- the pinned path
        #   - older/other paths: raw body somewhere in .args
        kwargs = getattr(pending_request, "kwargs", None) or {}
        candidates = list(pending_request.args)
        if "request_body" in kwargs:
            candidates.insert(0, kwargs["request_body"])   # 2.56.0 direct-streaming body — check first
        candidates.extend(v for k, v in kwargs.items() if k != "request_body")

        prompt = None
        for arg in candidates:
            # Parsed request object (normal OpenAI ingress).
            for valid_input_type in ("messages", "prompt"):
                if hasattr(arg, valid_input_type):
                    prompt = getattr(arg, valid_input_type)
                    break
            if prompt is not None:
                break
            # Raw body (direct streaming): bytes/str JSON -> pull messages/prompt.
            if isinstance(arg, (bytes, bytearray, str)):
                try:
                    body = json.loads(arg)
                except (ValueError, TypeError):
                    continue  # truncated / non-JSON body -> try the next candidate
                if isinstance(body, dict):
                    prompt = body.get("messages") or body.get("prompt")
                    if prompt is not None:
                        break
        if prompt is None:
            # No extractable text -> don't crash the routing loop; let the caller load-balance.
            return None
        return self._normalize_prompt_to_string(prompt)
