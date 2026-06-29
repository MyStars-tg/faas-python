"""Webhook signature verification (stdlib ``hmac``/``hashlib`` only).

Reimplements the server's signer byte-for-byte: ``X-Faas-Signature`` is the
lowercase-hex HMAC-SHA256 of the RAW request body under the tenant secret, with
NO timestamp. During a 24h rotation the header is ``"current,previous"`` — split
on ``,`` and constant-time-compare each, so verification holds with either secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from .errors import WebhookVerificationError
from .models import WebhookEvent


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


class WebhookVerifier:
    """Holds a tenant secret and verifies/parses incoming webhooks."""

    def __init__(self, secret: str) -> None:
        """Construct a verifier bound to a tenant webhook secret.

        Args:
            secret: The tenant webhook secret (issued once in the bot; separate from the API key).
        """
        self._secret = secret

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
