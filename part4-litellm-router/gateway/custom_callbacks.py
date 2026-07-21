# custom_callbacks.py
# -----------------------------------------------------------------------------
# Deployment-level auth scrubbing for the local Anyscale backend.
#
# WHY: `forward_client_headers_to_llm_api: true` forwards the caller's
# `Authorization: Bearer sk-ant-oat...` (Claude Code's subscription OAuth
# login) to every upstream. That is REQUIRED for the claude-opus-4-8 fallback
# (per-user billing) but WRONG for the Anyscale LLM service, whose ingress
# expects `Authorization: Bearer <service token>` (set via extra_headers in
# config.yaml). LiteLLM merges forwarded headers with extra_headers via a
# CASE-SENSITIVE dict update (llm_http_handler.async_anthropic_messages_handler:
# "forwarded < extra_headers"), so the forwarded lowercase `authorization`
# survives NEXT TO the configured `Authorization`, and the Anyscale ingress
# (nginx) rejects the request with 401 -> 60s cooldown -> silent fallback to
# Opus. Net effect: Claude Code "works" but the local model is never used.
#
# FIX: this hook runs AFTER the router picks a deployment and BEFORE the HTTP
# call (litellm.utils.wrapper_async -> async_pre_call_deployment_hook; fires
# for both /v1/messages and /v1/chat/completions). When the chosen deployment
# targets LOCAL_LLM_BASE_URL, drop every case-variant of `authorization` from
# the FORWARDED headers so the extra_headers service bearer is the only auth
# sent. Deployments pointing anywhere else (api.anthropic.com) are untouched,
# keeping the per-user OAuth passthrough fallback intact.
# -----------------------------------------------------------------------------
import os
from typing import Any, Dict, Optional

from litellm.integrations.custom_logger import CustomLogger


def _norm(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/").lower()


_LOCAL_LLM_BASE_URL = _norm(os.environ.get("LOCAL_LLM_BASE_URL"))


def _has_auth(headers: Dict[str, Any]) -> bool:
    return any(k.lower() == "authorization" for k in headers)


def _without_auth(headers: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in headers.items() if k.lower() != "authorization"}


class ScrubClientAuthForLocalLLM(CustomLogger):
    async def async_pre_call_deployment_hook(
        self, kwargs: Dict[str, Any], call_type: Optional[Any]
    ) -> Optional[dict]:
        if not _LOCAL_LLM_BASE_URL:
            return kwargs
        if _norm(kwargs.get("api_base")) != _LOCAL_LLM_BASE_URL:
            return kwargs
        # The caller's OAuth Authorization rides in TWO places, scrub both:
        # 1. kwargs["headers"] — generic forwarded headers (chat/completions path)
        # 2. kwargs["provider_specific_header"]["extra_headers"] — the anthropic
        #    endpoint packages `Authorization: Bearer sk-ant-oat...` here
        #    (add_provider_specific_headers_to_request), and it merges with the
        #    HIGHEST precedence in async_anthropic_messages_handler
        #    ("forwarded < extra_headers < provider_specific").
        # COPY, never mutate: these nested dicts are shared with the kwargs the
        # router reuses for its Opus fallback call, which NEEDS the OAuth header.
        fwd = kwargs.get("headers")
        if isinstance(fwd, dict) and _has_auth(fwd):
            kwargs["headers"] = _without_auth(fwd)
        psh = kwargs.get("provider_specific_header")
        if isinstance(psh, dict):
            psh_extra = psh.get("extra_headers")
            if isinstance(psh_extra, dict) and _has_auth(psh_extra):
                kwargs["provider_specific_header"] = {
                    **psh,
                    "extra_headers": _without_auth(psh_extra),
                }
        return kwargs


scrub_client_auth = ScrubClientAuthForLocalLLM()
