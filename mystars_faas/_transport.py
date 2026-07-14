"""Shared transport helpers used by both the sync and async clients.

Centralizes URL building, header construction, retry classification, backoff, and
response handling so the two clients stay byte-for-byte consistent.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ._version import __version__
from .errors import (
    MyStarsAPIError,
    MyStarsError,
    MyStarsTransportError,
    RateLimitedError,
    TimeoutError_,
    error_from_response,
)

PRODUCTION_BASE_URL = "https://api.mystars.tg/v1"

# A hostile or buggy upstream must not be able to OOM the SDK. Mirrors the TS
# SDK's MAX_RESPONSE_BYTES — the body is streamed and aborted past this ceiling.
MAX_RESPONSE_BYTES = 4_000_000


@dataclass
class RetryPolicy:
    """Retry/backoff configuration for both clients.

    Retries apply only to idempotent requests — GETs, writes carrying an ``Idempotency-Key``, and
    the SDK-marked-idempotent writes ``recipients/check`` and ``orders/{id}/cancel`` — and only to
    transient failures: network/timeout, 500/502/503/504, and the *general* 429
    (the ``order_cap`` 429 is never retried). Backoff is exponential
    (``base_delay * 2**attempt``, capped at ``max_delay``), optionally jittered, and never
    shorter than the server's ``Retry-After``.

    Attributes:
        max_retries: Maximum retry attempts after the first try (default 3).
        base_delay: Base backoff in seconds (default 0.5).
        max_delay: Backoff ceiling in seconds (default 30.0).
        respect_retry_after: Honour a ``Retry-After`` header as a delay floor (default ``True``).
        jitter: Apply random jitter to each backoff delay (default ``True``).
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    respect_retry_after: bool = True
    jitter: bool = True


@dataclass
class _Request:
    method: str
    path: str
    params: dict[str, Any] | None = None
    json_body: Any = None
    idempotency_key: str | None = None
    idempotent: bool | None = None  # override; default GET or has-idempotency-key


def new_idempotency_key() -> str:
    return str(uuid.uuid4())


def cancel_result(order_id: str, data: Any) -> dict[str, str]:
    """Shape a cancel response, tolerating a 204 / empty-body 2xx.

    A successful cancel may legitimately return no body; fall back to the
    requested ``order_id`` and a ``"cancelled"`` status instead of indexing a
    ``None`` body.
    """
    if not isinstance(data, Mapping):
        return {"order_id": order_id, "status": "cancelled"}
    return {
        "order_id": str(data.get("order_id", order_id)),
        "status": str(data.get("status", "cancelled")),
    }


def build_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)


def headers_for(api_key: str, idempotency_key: str | None, has_body: bool, user_agent: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "X-Api-Key": api_key}
    if user_agent:
        h["User-Agent"] = user_agent
    if idempotency_key is not None:
        h["Idempotency-Key"] = idempotency_key
    if has_body:
        h["Content-Type"] = "application/json"
    return h


def default_user_agent() -> str:
    return f"mystars-faas-python/{__version__}"


def clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


def is_idempotent(req: _Request) -> bool:
    if req.idempotent is not None:
        return req.idempotent
    return req.method == "GET" or req.idempotency_key is not None


def should_retry(err: MyStarsError, idempotent: bool) -> bool:
    if not idempotent:
        return False
    if isinstance(err, MyStarsTransportError):  # also covers TimeoutError_
        return True
    if isinstance(err, RateLimitedError):
        return err.kind == "general"
    # 503/500/502/504 → retryable flag set by error_from_response
    return bool(getattr(err, "retryable", False))


def backoff_delay(attempt: int, err: MyStarsError, policy: RetryPolicy, rnd: float) -> float:
    capped = min(policy.base_delay * (2 ** attempt), policy.max_delay)
    delay = rnd * capped if policy.jitter else capped
    if policy.respect_retry_after and isinstance(err, RateLimitedError) and err.retry_after_ms is not None:
        delay = max(delay, err.retry_after_ms / 1000.0)
    return float(delay)


def map_httpx_error(exc: Exception) -> MyStarsError:
    if isinstance(exc, httpx.TimeoutException):
        return TimeoutError_("request timed out")
    if isinstance(exc, httpx.HTTPError):
        return MyStarsTransportError(str(exc) or "network request failed")
    return MyStarsTransportError(str(exc) or "request failed")


def _too_large(status: int) -> MyStarsAPIError:
    return MyStarsAPIError(
        code="response_too_large", http_status=status, message="Response body exceeded the size limit",
    )


def read_bounded_bytes(chunks: Iterable[bytes], status: int) -> bytes:
    """Accumulate a streamed body, aborting with ``response_too_large`` past the ceiling."""
    out = bytearray()
    for chunk in chunks:
        out += chunk
        if len(out) > MAX_RESPONSE_BYTES:
            raise _too_large(status)
    return bytes(out)


async def aread_bounded_bytes(chunks: AsyncIterable[bytes], status: int) -> bytes:
    """Async counterpart of :func:`read_bounded_bytes`."""
    out = bytearray()
    async for chunk in chunks:
        out += chunk
        if len(out) > MAX_RESPONSE_BYTES:
            raise _too_large(status)
    return bytes(out)


def parse_response(status: int, headers: Mapping[str, str], body: bytes) -> tuple[Any, bool]:
    """Return (parsed_json_or_none, ok). Raises a typed error for non-2xx."""
    is_success = 200 <= status < 300
    text = body.decode("utf-8", "replace") if body else ""
    data: Any = None
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            if not is_success:
                raise error_from_response(status, None, headers) from None
            raise MyStarsAPIError(
                code="invalid_response", http_status=status, message="response was not valid JSON",
            ) from None
    if not is_success:
        raise error_from_response(status, data, headers)
    return data, True
