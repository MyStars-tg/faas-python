"""Webhook signature verification (stdlib ``hmac``/``hashlib`` only).

Reimplements the server's signer byte-for-byte. Two headers carry it:

- ``X-Faas-Signature`` (legacy, every webhook): the lowercase-hex HMAC-SHA256 of the RAW
  request body under the tenant secret, with NO timestamp. During a 24h rotation the header is
  ``"current,previous"`` — split on ``,`` and constant-time-compare each.
- ``X-Faas-Signature-V2`` (contract 2.1.0, every webhook): ``t=<unix>,v1=<hex>[,v1=<hex>]``,
  the HMAC of ``"<t>.<raw body>"`` — the send time is inside the MAC, so bounding
  ``|now - t|`` (default 300 s) refuses a replayed capture. Tenant-level events (campaigns,
  giveaways, series) are always verified with V2.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any, Union

from .errors import MyStarsValidationError, WebhookVerificationError
from .models import TenantEvent, WebhookEvent

#: Default accepted clock distance for ``X-Faas-Signature-V2``, in seconds.
SIGNATURE_V2_TOLERANCE_SEC = 300


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: str | bytes, signature_header: str | None, secret: str) -> bool:
    """Verify an ``X-Faas-Signature`` header against the raw body (rotation-aware).

    Computes ``HMAC_SHA256(secret, raw_body)`` (lowercase hex, no timestamp) and constant-time
    compares it against each comma-separated element of the header, accepting if any matches —
    correct in steady state (one signature) and across the 24h rotation (``"current,previous"``).

    Args:
        raw_body: The exact request body bytes (``str`` is UTF-8 encoded). Verify the RAW bytes,
            not a re-serialized JSON.
        signature_header: The ``X-Faas-Signature`` value, or ``None``.
        secret: The tenant webhook secret.

    Returns:
        ``True`` if the signature is valid, else ``False`` (also for a missing header). Never raises.
    """
    if not signature_header:
        return False
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    expected = _sign(secret, body).encode("ascii")
    matched = False
    for part in signature_header.split(","):
        # Compare as bytes: a non-ASCII (attacker-controlled) header byte then fails
        # cleanly to False instead of raising TypeError from compare_digest on str.
        if hmac.compare_digest(expected, part.strip().encode("utf-8")):
            matched = True
    return matched


def _secrets(secret: str | Sequence[str]) -> list[str]:
    candidates = [secret] if isinstance(secret, str) else list(secret)
    return [s for s in candidates if isinstance(s, str) and s]


def _is_window_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def _check_tolerance(tolerance_sec: object) -> None:
    """Refuse a replay window that bounds nothing: ``abs(now - t) > nan`` is False for every ``t``."""
    if not _is_window_number(tolerance_sec):
        raise MyStarsValidationError(f"tolerance_sec must be a finite number of seconds >= 0, got {tolerance_sec!r}")


def _check_now(now: object) -> None:
    if now is not None and not _is_window_number(now):
        raise MyStarsValidationError(f"now must be finite unix seconds >= 0, got {now!r}")


def verify_webhook_signature_v2(
    raw_body: str | bytes,
    signature_v2_header: str | None,
    secret: str | Sequence[str],
    *,
    tolerance_sec: int = SIGNATURE_V2_TOLERANCE_SEC,
    now: int | None = None,
) -> bool:
    """Verify an ``X-Faas-Signature-V2`` header against the raw body.

    Accepts when some ``v1`` equals ``HMAC_SHA256(secret, "<t>.<raw body>")`` under one of your
    secrets (pass ``[current, previous]`` during your own rotation) and ``t`` is within
    ``tolerance_sec`` of ``now``. Constant-time per candidate.

    Args:
        raw_body: The exact request body bytes (``str`` is UTF-8 encoded).
        signature_v2_header: The ``X-Faas-Signature-V2`` value, or ``None``.
        secret: Your webhook secret, or a sequence of secrets (current first).
        tolerance_sec: Max ``|now - t|`` in seconds (default 300).
        now: "Now" in unix seconds (default: the system clock).

    Returns:
        ``True`` if valid, else ``False``. Never raises on a malformed header or body.

    Raises:
        MyStarsValidationError: When ``tolerance_sec`` or ``now`` is not a finite number >= 0 — a
            misconfigured replay window fails closed, whatever the header.
    """
    _check_tolerance(tolerance_sec)
    _check_now(now)
    if not isinstance(signature_v2_header, str) or not signature_v2_header:
        return False
    t: str | None = None
    candidates: list[bytes] = []
    for part in signature_v2_header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if key == "t" and value.isascii() and value.isdigit():
            t = value
        elif key == "v1" and value:
            candidates.append(value.encode("utf-8"))
    secrets = _secrets(secret)
    if t is None or not candidates or not secrets:
        return False
    current = int(time.time()) if now is None else now
    try:
        sent = int(t)
    except ValueError:
        # Python 3.11+ refuses int() of a string over 4300 digits. No such ``t`` is in the window
        # (the TS verifier reads it as Infinity), so it is a plain rejection, never an exception.
        return False
    if not abs(current - sent) <= tolerance_sec:
        return False
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    signed = t.encode("ascii") + b"." + body
    matched = False
    for s in secrets:
        expected = _sign(s, signed).encode("ascii")
        for c in candidates:  # no early exit
            if hmac.compare_digest(expected, c):
                matched = True
    return matched


def _parse_object(raw_body: str | bytes) -> dict[str, Any]:
    text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WebhookVerificationError("webhook body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise WebhookVerificationError("webhook body is not a JSON object")
    return parsed


def _is_envelope(obj: Mapping[str, Any]) -> bool:
    return (
        all(isinstance(obj.get(k), str) for k in ("id", "type", "created_at", "api_version"))
        and isinstance(obj.get("data"), dict)
        and "order_id" not in obj
    )


def _order_event(obj: Mapping[str, Any]) -> WebhookEvent:
    if not isinstance(obj.get("order_id"), str):
        raise WebhookVerificationError("webhook body is missing order_id")
    if not isinstance(obj.get("status"), str):
        raise WebhookVerificationError("webhook body is missing status")
    return WebhookEvent.from_dict(obj)


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    lower = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower:
            if isinstance(value, (list, tuple)):
                return str(value[0]) if value else None
            return None if value is None else str(value)
    return None


AnyWebhookEvent = Union[WebhookEvent, TenantEvent]


class WebhookVerifier:
    """Holds a tenant secret and verifies/parses incoming webhooks."""

    def __init__(
        self, secret: str, *, previous_secret: str | None = None, tolerance_sec: int = SIGNATURE_V2_TOLERANCE_SEC
    ) -> None:
        """Construct a verifier bound to a tenant webhook secret.

        Args:
            secret: The tenant webhook secret (issued once in the bot; separate from the API key).
            previous_secret: Your previous secret, during your own rotation — accepted by the V2
                checks and by :meth:`verify_event`'s legacy fallback (the legacy :meth:`verify`
                uses ``secret`` only, as before).
            tolerance_sec: Accepted clock distance for ``X-Faas-Signature-V2`` (default 300 s).

        Raises:
            MyStarsValidationError: If ``tolerance_sec`` is not a finite number >= 0.
        """
        _check_tolerance(tolerance_sec)
        self._secret = secret
        self._v2_secrets = [secret] + ([previous_secret] if previous_secret else [])
        self._tolerance = tolerance_sec

    def is_valid(self, raw_body: str | bytes, signature_header: str | None) -> bool:
        """Return whether the ``X-Faas-Signature`` matches the raw body (rotation-aware).

        Args:
            raw_body: The exact bytes received, before any framework re-serialization.
            signature_header: The ``X-Faas-Signature`` value (may be the ``"current,previous"``
                rotation form), or ``None``.

        Returns:
            ``True`` if any signature in the header matches (constant-time), else ``False``.
            Never raises.
        """
        return verify_webhook_signature(raw_body, signature_header, self._secret)

    def verify(self, raw_body: str | bytes, signature_header: str | None) -> WebhookEvent:
        """Verify the signature then parse the body into a :class:`WebhookEvent`.

        Raises :class:`WebhookVerificationError` on a bad/missing signature, an
        unparseable body, or a body missing ``order_id``/``status``. Dedup on
        ``event.order_id`` — delivery is at-least-once.
        """
        if not self.is_valid(raw_body, signature_header):
            raise WebhookVerificationError("webhook signature verification failed")
        text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WebhookVerificationError("webhook body is not valid JSON") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("order_id"), str):
            raise WebhookVerificationError("webhook body is missing order_id")
        if not isinstance(parsed.get("status"), str):
            raise WebhookVerificationError("webhook body is missing status")
        return WebhookEvent.from_dict(parsed)

    def is_valid_v2(self, raw_body: str | bytes, signature_v2_header: str | None, *, now: int | None = None) -> bool:
        """Return whether ``X-Faas-Signature-V2`` is valid (secret or previous secret, within tolerance).

        Args:
            raw_body: The exact bytes received.
            signature_v2_header: The ``X-Faas-Signature-V2`` value, or ``None``.
            now: "Now" in unix seconds (default: the system clock).

        Returns:
            ``True`` if valid. Never raises on a malformed header or body.

        Raises:
            MyStarsValidationError: If ``now`` is not finite unix seconds >= 0.
        """
        return verify_webhook_signature_v2(raw_body, signature_v2_header, self._v2_secrets, tolerance_sec=self._tolerance, now=now)

    def verify_tenant_event(self, raw_body: str | bytes, signature_v2_header: str | None, *, now: int | None = None) -> TenantEvent:
        """Verify ``X-Faas-Signature-V2`` then parse a tenant event envelope (no ``order_id`` needed).

        Raises:
            WebhookVerificationError: On a bad / stale / missing signature or a body that is not
                an envelope. Dedupe on ``event.id``.
            MyStarsValidationError: If ``now`` is not finite unix seconds >= 0.
        """
        if not self.is_valid_v2(raw_body, signature_v2_header, now=now):
            raise WebhookVerificationError("webhook signature (X-Faas-Signature-V2) verification failed")
        obj = _parse_object(raw_body)
        if not _is_envelope(obj):
            raise WebhookVerificationError("webhook body is not a tenant event envelope")
        return TenantEvent.from_dict(obj)

    def verify_event(
        self,
        raw_body: str | bytes,
        headers: Mapping[str, Any],
        *,
        require_signature_v2: bool = False,
        now: int | None = None,
    ) -> AnyWebhookEvent:
        """One verifier for an endpoint that receives both kinds of webhook.

        With ``X-Faas-Signature-V2`` present it must verify (a valid legacy header never rescues
        a bad V2). Without it, an ORDER body still verifies on ``X-Faas-Signature`` unless
        ``require_signature_v2`` is set; a tenant envelope is never accepted on the legacy header.

        Args:
            raw_body: The exact bytes received.
            headers: The request headers (any case; values as strings or lists).
            require_signature_v2: Refuse an order webhook without V2.
            now: "Now" in unix seconds (default: the system clock).

        Returns:
            A :class:`~mystars_faas.WebhookEvent` (order) or a :class:`~mystars_faas.TenantEvent`.

        Raises:
            WebhookVerificationError: When verification fails or the body is neither kind.
            MyStarsValidationError: If ``now`` is not finite unix seconds >= 0.
        """
        _check_now(now)
        v2 = _header(headers, "X-Faas-Signature-V2")
        verified_by_v2 = False
        if v2:
            if not self.is_valid_v2(raw_body, v2, now=now):
                raise WebhookVerificationError("webhook signature (X-Faas-Signature-V2) verification failed")
            verified_by_v2 = True
        else:
            if require_signature_v2:
                raise WebhookVerificationError("X-Faas-Signature-V2 is required")
            legacy = _header(headers, "X-Faas-Signature")
            # Every one of your secrets is tried (no early exit), as the V2 check does.
            matches = [verify_webhook_signature(raw_body, legacy, s) for s in self._v2_secrets]
            if not any(matches):
                raise WebhookVerificationError("webhook signature verification failed")
        obj = _parse_object(raw_body)
        if _is_envelope(obj):
            if not verified_by_v2:
                raise WebhookVerificationError("a tenant event must carry X-Faas-Signature-V2")
            return TenantEvent.from_dict(obj)
        return _order_event(obj)
