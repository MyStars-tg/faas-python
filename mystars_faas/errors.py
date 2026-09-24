"""Typed error taxonomy, keyed on the envelope ``error.code``.

The server returns ``{"error": {"code", "message", "telegram_message"?}}`` for
handled errors and a bare ``{"error": "not_found"}`` string for unmatched routes.
``error_from_response`` maps both forms — plus network/timeout failures. An
unknown future code falls back to :class:`MyStarsAPIError`, so the SDK never
crashes on a new code.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


class MyStarsError(Exception):
    """Base class for every error this SDK raises."""


class MyStarsValidationError(MyStarsError):
    """Invalid input caught client-side, before any HTTP request."""


class MyStarsTransportError(MyStarsError):
    """The request never produced an HTTP response (network/timeout/connection)."""


class TimeoutError_(MyStarsTransportError):
    """The request exceeded the configured timeout."""


class WebhookVerificationError(MyStarsError):
    """A webhook payload failed signature verification (or the header was missing/malformed)."""


class OrderWaitTimeout(MyStarsError):
    """``wait_for_order`` gave up before the order reached a terminal state."""

    def __init__(self, last_order: Any, message: str | None = None) -> None:
        """Capture the last polled order so the caller can inspect/resume.

        Args:
            last_order: The most recent :class:`~mystars_faas.Order` seen before timing out
                (available as ``self.last_order``).
            message: Optional override message; a default is derived from the order otherwise.
        """
        self.last_order = last_order
        status = getattr(last_order, "status", "?")
        order_id = getattr(last_order, "order_id", "?")
        super().__init__(message or f"order {order_id} did not finish in time (last status: {status})")


class MyStarsAPIError(MyStarsError):
    """Any error originating from an HTTP response."""

    def __init__(
        self,
        *,
        code: str,
        http_status: int,
        message: str,
        telegram_message: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        raw: Any = None,
    ) -> None:
        """Construct an API error from the parsed error envelope.

        Args:
            code: The envelope ``error.code`` (or ``"unknown"`` when absent).
            http_status: The HTTP status code.
            message: The envelope ``error.message`` (or a synthesized ``HTTP <status>``).
            telegram_message: The buyer-facing ``error.telegram_message``, if present.
            request_id: The ``X-Request-Id`` response header, if present (for support).
            retryable: Whether the SDK considers this safe to retry (set for 5xx / general 429).
            raw: The raw decoded body, kept for debugging.
        """
        super().__init__(f"[{http_status} {code}] {message}")
        self.code = code
        self.http_status = http_status
        self.message = message
        self.telegram_message = telegram_message
        self.request_id = request_id
        self.retryable = retryable
        self.raw = raw


class BadRequestError(MyStarsAPIError):
    """400."""


class AuthenticationError(MyStarsAPIError):
    """401."""


class PermissionDeniedError(MyStarsAPIError):
    """403 — tenant suspended or banned."""


# TS-SDK name parity: the TypeScript SDK exposes ``UnauthorizedError`` (401) and
# ``ForbiddenError`` (403). Keep the Pythonic names as the raised classes and
# expose these aliases so code written against either name catches the same error.
UnauthorizedError = AuthenticationError
ForbiddenError = PermissionDeniedError


class NotFoundError(MyStarsAPIError):
    """404."""


class ConflictError(MyStarsAPIError):
    """409."""


class IdempotencyConflictError(ConflictError):
    """409 — the same Idempotency-Key was reused with a different body."""


class OrderNotCancellableError(ConflictError):
    """409 — the order is not awaiting_payment and cannot be cancelled."""


class RecipientIneligibleError(MyStarsAPIError):
    """422 — the recipient cannot receive the item; no order was created.

    The 422 body carries only ``telegram_message`` (the buyer-facing reason). For
    the structured reason, call :meth:`MyStarsClient.check_recipient` first.
    """


class RateLimitedError(MyStarsAPIError):
    """429."""

    def __init__(
        self,
        *,
        retry_after_ms: int | None = None,
        limit: int | None = None,
        remaining: int | None = None,
        reset: int | None = None,
        kind: str = "general",
        **kwargs: Any,
    ) -> None:
        """Construct a 429 error, carrying the rate-limit signal.

        Args:
            retry_after_ms: Milliseconds to wait, parsed from ``Retry-After`` (both
                delta-seconds and HTTP-date forms), if present.
            limit: The ``RateLimit-Limit`` header value, if present.
            remaining: The ``RateLimit-Remaining`` header value, if present.
            reset: The ``RateLimit-Reset`` header value, if present.
            kind: ``"general"`` when RFC-9110 ``RateLimit-*`` / ``Retry-After`` are present
                (retried automatically); ``"order_cap"`` otherwise (never retried).
            **kwargs: Forwarded to :class:`MyStarsAPIError` (``code``, ``http_status``, …).
        """
        super().__init__(**kwargs)
        self.retry_after_ms = retry_after_ms
        self.limit = limit
        self.remaining = remaining
        self.reset = reset
        # "general" when RFC-9110 RateLimit-* headers are present; "order_cap" otherwise.
        self.kind = kind


class ServiceUnavailableError(MyStarsAPIError):
    """503."""


class InternalServerError(MyStarsAPIError):
    """500."""


def _to_int(value: str | None) -> int | None:
    # Mirrors the TS SDK's ``toInt`` (``Number(value)`` + ``Number.isFinite``):
    # a finite numeric header — including a float form like ``"60.0"`` — parses.
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n):
        return None
    return int(n)


def parse_retry_after_ms(value: str | None, now: datetime | None = None) -> int | None:
    """Parse a ``Retry-After`` header into milliseconds.

    Accepts both RFC-9110 forms — delta-seconds (``"120"``) and an HTTP-date
    (``"Wed, 21 Oct 2015 07:28:00 GMT"``) — matching the TS SDK's
    ``parseRetryAfterMs``. The HTTP-date branch returns the milliseconds until
    that instant, clamped at 0 for a past date. ``now`` is injectable for tests.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None and math.isfinite(seconds):
        return max(0, int(round(seconds * 1000)))
    # HTTP-date form.
    try:
        then = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if then is None:  # py<3.10 returns None on an unparseable date
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0, int(round((then - current).total_seconds() * 1000)))


def _parse_envelope(status: int, body: Any) -> tuple[str, str, str | None]:
    if isinstance(body, Mapping) and "error" in body:
        err = body["error"]
        if isinstance(err, Mapping):
            c = err.get("code")
            m = err.get("message")
            t = err.get("telegram_message")
            code = c if isinstance(c, str) else "unknown"
            message = m if isinstance(m, str) else f"HTTP {status}"
            tg = t if isinstance(t, str) else None
            return code, message, tg
        if isinstance(err, str):  # bare {"error": "not_found"}
            return err, err, None
    return "unknown", f"HTTP {status}", None


def error_from_response(status: int, body: Any, headers: Mapping[str, str]) -> MyStarsAPIError:
    """Map an HTTP response (status + parsed body + headers) to the right typed error."""
    code, message, tg = _parse_envelope(status, body)
    request_id = headers.get("x-request-id")
    base = dict(code=code, http_status=status, message=message, telegram_message=tg, request_id=request_id, raw=body)

    if status == 400:
        return BadRequestError(**base)
    if status == 401:
        return AuthenticationError(**base)
    if status == 403:
        return PermissionDeniedError(**base)
    if status == 404:
        return NotFoundError(**base)
    if status == 409:
        low = message.lower()
        if "idempotency" in low:
            return IdempotencyConflictError(**base)
        if "cancel" in low:
            return OrderNotCancellableError(**base)
        return ConflictError(**base)
    if status == 422:
        # Surface the buyer-facing reason: telegram_message, falling back to message (TS parity).
        return RecipientIneligibleError(**{**base, "telegram_message": tg or message})
    if status == 429:
        limit = _to_int(headers.get("ratelimit-limit"))
        retry_after_ms = parse_retry_after_ms(headers.get("retry-after"))
        kind = "general" if (limit is not None or retry_after_ms is not None) else "order_cap"
        return RateLimitedError(
            retry_after_ms=retry_after_ms,
            limit=limit,
            remaining=_to_int(headers.get("ratelimit-remaining")),
            reset=_to_int(headers.get("ratelimit-reset")),
            kind=kind,
            retryable=(kind == "general"),
            **base,
        )
    if status == 503:
        base["retryable"] = True
        return ServiceUnavailableError(**base)
    if status == 500:
        base["retryable"] = True
        return InternalServerError(**base)
    base["retryable"] = status >= 500
    return MyStarsAPIError(**base)
