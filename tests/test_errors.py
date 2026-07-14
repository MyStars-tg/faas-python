from __future__ import annotations

from datetime import datetime, timezone

import httpx

from mystars_faas._transport import map_httpx_error, should_retry
from mystars_faas.errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    IdempotencyConflictError,
    InternalServerError,
    MyStarsTransportError,
    NotFoundError,
    OrderNotCancellableError,
    PermissionDeniedError,
    RateLimitedError,
    RecipientIneligibleError,
    ServiceUnavailableError,
    TimeoutError_,
    UnauthorizedError,
    _to_int,
    error_from_response,
    parse_retry_after_ms,
)


def env(code, message, **extra):
    return {"error": {"code": code, "message": message}, **extra}


def _h(d=None):
    return httpx.Headers(d or {})


def test_code_to_class():
    assert isinstance(error_from_response(400, env("bad_request", "x"), _h()), BadRequestError)
    assert isinstance(error_from_response(401, env("unauthorized", "x"), _h()), AuthenticationError)
    assert isinstance(error_from_response(403, env("forbidden", "x"), _h()), PermissionDeniedError)
    assert isinstance(error_from_response(404, env("not_found", "x"), _h()), NotFoundError)
    assert isinstance(error_from_response(503, env("unavailable", "x"), _h()), ServiceUnavailableError)
    assert isinstance(error_from_response(500, env("internal", "x"), _h()), InternalServerError)


def test_bare_not_found_form():
    err = error_from_response(404, {"error": "not_found"}, _h())
    assert isinstance(err, NotFoundError)
    assert err.code == "not_found"


def test_conflict_subtypes():
    assert isinstance(error_from_response(409, env("conflict", "Idempotency-Key reused with a different request body"), _h()), IdempotencyConflictError)
    assert isinstance(error_from_response(409, env("conflict", "order is delivered, cannot cancel"), _h()), OrderNotCancellableError)
    generic = error_from_response(409, env("conflict", "something else"), _h())
    assert isinstance(generic, ConflictError) and not isinstance(generic, IdempotencyConflictError)


def test_recipient_ineligible_telegram_message():
    body = {"error": {"code": "recipient_ineligible", "message": "no", "telegram_message": "Already a Premium subscriber"}}
    err = error_from_response(422, body, _h())
    assert isinstance(err, RecipientIneligibleError)
    assert err.telegram_message == "Already a Premium subscriber"


def test_rate_limit_kinds():
    general = error_from_response(429, env("rate_limited", "slow"), _h({"ratelimit-limit": "60", "retry-after": "2"}))
    assert isinstance(general, RateLimitedError) and general.kind == "general" and general.retry_after_ms == 2000 and general.retryable
    cap = error_from_response(429, env("rate_limited", "daily order cap reached"), _h())
    assert cap.kind == "order_cap" and cap.retry_after_ms is None and not cap.retryable


def test_parse_retry_after_ms():
    assert parse_retry_after_ms("3") == 3000
    assert parse_retry_after_ms(None) is None
    assert parse_retry_after_ms("soon") is None


# ─── B1: Retry-After HTTP-date parity ────────────────────────────────────────


def test_parse_retry_after_ms_http_date_future():
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    # 30 seconds in the future → 30_000 ms.
    ms = parse_retry_after_ms("Thu, 25 Jun 2026 12:00:30 GMT", now=now)
    assert ms == 30_000


def test_parse_retry_after_ms_http_date_past_clamps_to_zero():
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after_ms("Wed, 21 Oct 2015 07:28:00 GMT", now=now) == 0


def test_parse_retry_after_ms_http_date_honored_in_429():
    # An HTTP-date Retry-After should be honored on a general 429 (delay > 0).
    headers = _h({"ratelimit-limit": "60", "retry-after": "Sun, 06 Nov 2050 08:49:37 GMT"})
    err = error_from_response(429, env("rate_limited", "slow"), headers)
    assert isinstance(err, RateLimitedError)
    assert err.retry_after_ms is not None and err.retry_after_ms > 0


# ─── B6: _to_int accepts floats (TS toInt parity) ────────────────────────────


def test_to_int_accepts_float_string():
    assert _to_int("60.0") == 60
    assert _to_int("60") == 60
    assert _to_int("soon") is None
    assert _to_int(None) is None


def test_rate_limit_headers_with_float_values():
    headers = _h({"ratelimit-limit": "60.0", "ratelimit-remaining": "12.0", "ratelimit-reset": "30.0"})
    err = error_from_response(429, env("rate_limited", "slow"), headers)
    assert isinstance(err, RateLimitedError)
    assert err.limit == 60 and err.remaining == 12 and err.reset == 30
    assert err.kind == "general"


# ─── B3: Unauthorized / Forbidden aliases (TS name parity) ───────────────────


def test_unauthorized_alias_resolves_to_401_class():
    err = error_from_response(401, env("unauthorized", "x"), _h())
    assert isinstance(err, AuthenticationError)
    assert isinstance(err, UnauthorizedError)
    assert UnauthorizedError is AuthenticationError


def test_forbidden_alias_resolves_to_403_class():
    err = error_from_response(403, env("forbidden", "x"), _h())
    assert isinstance(err, PermissionDeniedError)
    assert isinstance(err, ForbiddenError)
    assert ForbiddenError is PermissionDeniedError


# ─── B5(c): timeout / transport-error retry classification ───────────────────


def test_map_httpx_error_classifies_timeout():
    assert isinstance(map_httpx_error(httpx.ConnectTimeout("t")), TimeoutError_)
    assert isinstance(map_httpx_error(httpx.ReadTimeout("t")), TimeoutError_)


def test_map_httpx_error_classifies_transport():
    err = map_httpx_error(httpx.ConnectError("c"))
    assert isinstance(err, MyStarsTransportError) and not isinstance(err, TimeoutError_)


def test_should_retry_transport_and_timeout():
    assert should_retry(TimeoutError_("t"), True) is True
    assert should_retry(MyStarsTransportError("c"), True) is True
    # never retried when the request is non-idempotent
    assert should_retry(TimeoutError_("t"), False) is False
    assert should_retry(MyStarsTransportError("c"), False) is False
