# direct_streaming_prefix_router.py
#
# Portable fix so PrefixCacheAffinityRouter WORKS under direct streaming.
#
# Why this is needed: under direct streaming the ingress forwards the RAW request body to the
# request router as `pending_request.args[0]` (a `bytes` object) — NOT a parsed Chat/Completion
# request. Stock `PrefixCacheAffinityRouter._extract_text_from_request` only scans args for an
# object with `.messages`/`.prompt`, finds none, and raises
# `ValueError: No request with message or prompt attribute found in pending_request.args`,
# which crashes the proxy routing loop -> every request hangs (curl HTTP 000). See
# spec_decode_validation/bug_report_direct_streaming_prefix_router.md.
#
# This subclass overrides only `_extract_text_from_request` to also parse the raw bytes/str body,
# and to degrade gracefully (return None -> load-balanced fallback) instead of raising. It's a
# proper custom router class (imported by the proxy from your working_dir), so no site-packages edits.
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
        prompt = None
        for arg in pending_request.args:
            # Normal OpenAI ingress: a parsed Chat/Completion request with .messages / .prompt.
            for valid_input_type in ("messages", "prompt"):
                if hasattr(arg, valid_input_type):
                    prompt = getattr(arg, valid_input_type)
                    break
            if prompt is not None:
                break
            # Direct streaming: the ingress forwards the RAW request body (bytes/str). Parse it.
            if isinstance(arg, (bytes, bytearray, str)):
                try:
                    body = json.loads(arg)
                except (ValueError, TypeError):
                    continue  # truncated / non-JSON body -> fall back to load-balancing
                if isinstance(body, dict):
                    prompt = body.get("messages") or body.get("prompt")
                    if prompt is not None:
                        break
        if prompt is None:
            # No extractable text -> don't crash the routing loop; let the caller load-balance.
            return None
        return self._normalize_prompt_to_string(prompt)
