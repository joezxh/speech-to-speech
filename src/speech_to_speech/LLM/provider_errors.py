"""Classify LLM provider failures and surface the real upstream reason.

The OpenAI SDK hides the upstream response body: a GPUStack 500 such as
``Failed to parse tools: Missing tool function`` reaches the pipeline as
``Error code: 500 - None``, so the pipeline can only report "the provider
failed" and the operator has no clue why. These helpers extract the status code
and the response body, and classify the failure into a small set of kinds the
pipeline can act on (different spoken fallback, different log wording).
"""
from __future__ import annotations

import httpx

# The upstream endpoint is unavailable: retrying later may succeed.
KIND_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
# The request timed out (connect or read).
KIND_TIMEOUT = "timeout"
# The provider rejected the request or failed for a request-specific reason.
KIND_PROVIDER_ERROR = "provider_error"

BODY_SNIPPET_LIMIT = 400

# Class names of the OpenAI SDK exceptions that carry no HTTP status but still
# mean "the upstream is not usable right now".
_CLASS_NAME_KINDS = {
    "APIConnectionError": KIND_UPSTREAM_UNAVAILABLE,
    "APITimeoutError": KIND_TIMEOUT,
    "APIStatusError": KIND_PROVIDER_ERROR,
}


def _status_code(exc: BaseException) -> int | None:
    """Return the HTTP status code carried by a provider exception, if any."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def upstream_body_snippet(exc: BaseException, limit: int = BODY_SNIPPET_LIMIT) -> str:
    """Return the upstream error body as a single-line, length-capped string."""
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        text = response.text
    except Exception:
        return ""
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def classify_provider_error(exc: BaseException) -> tuple[str, str]:
    """Classify a provider exception into ``(kind, detail)``.

    ``detail`` always starts with ``str(exc)`` so existing log lines and error
    assertions keep their content, and is extended with the upstream status
    code and the upstream response body when the provider supplied them.
    """
    detail = str(exc) or exc.__class__.__name__
    status = _status_code(exc)
    kind = _CLASS_NAME_KINDS.get(exc.__class__.__name__, KIND_PROVIDER_ERROR)
    if isinstance(exc, httpx.TimeoutException):
        kind = KIND_TIMEOUT
    elif isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        kind = KIND_UPSTREAM_UNAVAILABLE
    elif status is not None and status >= 500:
        kind = KIND_UPSTREAM_UNAVAILABLE
    elif status is None and exc.__class__.__name__ == "APIConnectionError":
        kind = KIND_UPSTREAM_UNAVAILABLE

    parts = [detail]
    if status is not None:
        parts.append(f"upstream_status={status}")
    body = upstream_body_snippet(exc)
    if body:
        parts.append(f"upstream_body={body}")
    return kind, " | ".join(parts)