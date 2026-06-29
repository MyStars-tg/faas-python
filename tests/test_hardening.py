"""B5(a)/(b): the API key never leaks into an exception, and bytes webhook bodies verify."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mystars_faas import (
    MyStarsAPIError,
    MyStarsClient,
    MyStarsTransportError,
    WebhookVerifier,
    verify_webhook_signature,
)
from mystars_faas._transport import RetryPolicy

API_KEY = "faas_" + "d" * 64
CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contract"


def _load_webhook_case() -> dict:
    return json.loads((CONTRACT_DIR / "webhook-vectors.json").read_text())["cases"][0]


# ─── B5(a): the API key must never appear in any raised error ─────────────────

def test_api_key_absent_from_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"content-type": "application/json"}, content=json.dumps({"error": {"code": "unauthorized", "message": "bad key"}}).encode())

    client = MyStarsClient(API_KEY, transport=httpx.MockTransport(handler), retry=RetryPolicy(max_retries=0))
    with pytest.raises(MyStarsAPIError) as exc:
        client.list_currencies()
    assert API_KEY not in str(exc.value)
    assert API_KEY not in repr(exc.value)
    assert API_KEY not in str(exc.value.raw)


def test_api_key_absent_from_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = MyStarsClient(API_KEY, transport=httpx.MockTransport(handler), retry=RetryPolicy(max_retries=0))
    with pytest.raises(MyStarsTransportError) as exc:
        client.list_currencies()
    assert API_KEY not in str(exc.value)
    assert API_KEY not in repr(exc.value)


# ─── B5(b): bytes bodies (FastAPI/Flask hand raw bytes) verify correctly ──────

def test_verify_webhook_signature_accepts_bytes():
    case = _load_webhook_case()
    raw = case["body"].encode("utf-8")
    assert verify_webhook_signature(raw, case["signature"], case["secret"]) is True
    # A flipped byte must fail.
    assert verify_webhook_signature(raw + b" ", case["signature"], case["secret"]) is False


def test_webhook_verifier_verify_accepts_bytes():
    case = _load_webhook_case()
    raw = case["body"].encode("utf-8")
    event = WebhookVerifier(case["secret"]).verify(raw, case["signature"])
    assert event.order_id == "order-123"
    assert event.status == "delivered"
