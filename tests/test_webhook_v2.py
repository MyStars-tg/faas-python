"""Signature V2 + tenant events (contract 2.1.0), pinned to contract/webhook-v2-vectors.json."""

from __future__ import annotations

import pytest
from conftest import load_contract

from mystars_faas import (
    MyStarsValidationError,
    TenantEvent,
    WebhookEvent,
    WebhookVerificationError,
    WebhookVerifier,
    verify_webhook_signature_v2,
)

V = load_contract("webhook-v2-vectors.json")
H = "X-Faas-Signature-V2"


def case(name: str) -> dict:
    return next(c for c in V["cases"] if c["name"] == name)


@pytest.mark.parametrize("c", V["cases"], ids=lambda c: c["name"])
def test_signing_cases_verify_at_their_timestamp(c):
    assert verify_webhook_signature_v2(c["body"], c["expected_headers"][H], c["secret"], now=c["timestamp"])
    if "previous_secret" in c:
        assert verify_webhook_signature_v2(c["body"], c["expected_headers"][H], c["previous_secret"], now=c["timestamp"])


@pytest.mark.parametrize("v", V["verification"], ids=lambda v: v["name"])
def test_verification_cases(v):
    assert verify_webhook_signature_v2(v["body"], v["header"], v["secret"], now=v["now"]) is v["valid"]


def test_default_tolerance_is_the_contract_one():
    assert V["tolerance_sec"] == 300
    c = case("order_delivered")
    header = c["expected_headers"][H]
    assert verify_webhook_signature_v2(c["body"], header, c["secret"], now=c["timestamp"] + 300)
    assert not verify_webhook_signature_v2(c["body"], header, c["secret"], now=c["timestamp"] + 301)
    assert not verify_webhook_signature_v2(c["body"], header, c["secret"], now=c["timestamp"] + 30, tolerance_sec=10)


def test_any_of_your_secrets_matches_and_bytes_work():
    c = case("order_delivered")
    header = c["expected_headers"][H]
    assert verify_webhook_signature_v2(c["body"].encode("utf-8"), header, ["whsec_new", c["secret"]], now=c["timestamp"])
    assert not verify_webhook_signature_v2(c["body"], header, ["whsec_new", "whsec_old"], now=c["timestamp"])
    assert not verify_webhook_signature_v2(c["body"], header, [], now=c["timestamp"])


def test_reads_the_clock_by_default():
    c = case("order_delivered")
    assert not verify_webhook_signature_v2(c["body"], c["expected_headers"][H], c["secret"])


@pytest.mark.parametrize("header", [None, "", "t=", "v1=", "t=abc,v1=00", ",,,", "t=1,v1", "t=1,v1=ünï"])
def test_never_raises_on_garbage(header):
    assert verify_webhook_signature_v2("{}", header, "s", now=1) is False


# Python refuses int() of a string over 4300 digits (ValueError); the TS verifier reads such a ``t``
# as Infinity and rejects it. A timestamp that long must be a plain rejection here too.
@pytest.mark.parametrize("digits", [21, 4301, 5000])
def test_an_overlong_timestamp_is_rejected_not_raised(digits):
    header = "t=" + "1" * digits + ",v1=ab"
    assert verify_webhook_signature_v2(b"{}", header, "s", now=1) is False
    assert WebhookVerifier("s").is_valid_v2(b"{}", header, now=1) is False
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier("s").verify_tenant_event(b"{}", header, now=1)


def test_verify_tenant_event_parses_the_envelope_without_order_id():
    c = case("envelope_campaign_paid")
    event = WebhookVerifier(c["secret"]).verify_tenant_event(c["body"], c["expected_headers"][H], now=c["timestamp"])
    assert isinstance(event, TenantEvent)
    assert (event.id, event.type, event.api_version, event.sequence) == (c["event_id"], "campaign.paid", "2.3.0", 3)
    assert event.created_at == "2026-01-01T00:00:00.000Z"
    assert event.data["campaign_id"] == "c0ffee00-1111-4222-8333-444455556666"


def test_verify_tenant_event_refuses_bad_stale_and_non_envelopes():
    c = case("envelope_campaign_paid")
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier("wrong").verify_tenant_event(c["body"], c["expected_headers"][H], now=c["timestamp"])
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier(c["secret"]).verify_tenant_event(c["body"], c["expected_headers"][H], now=c["timestamp"] + 301)
    o = case("order_delivered")
    with pytest.raises(WebhookVerificationError, match="not a tenant event envelope"):
        WebhookVerifier(o["secret"]).verify_tenant_event(o["body"], o["expected_headers"][H], now=o["timestamp"])


def test_previous_secret_is_accepted_for_v2():
    c = case("envelope_campaign_paid")
    verifier = WebhookVerifier("whsec_rotated_to", previous_secret=c["secret"])
    assert verifier.verify_tenant_event(c["body"], c["expected_headers"][H], now=c["timestamp"]).type == "campaign.paid"


def test_legacy_verify_is_unchanged_and_still_rejects_an_envelope():
    c = case("envelope_campaign_paid")
    with pytest.raises(WebhookVerificationError, match="order_id"):
        WebhookVerifier(c["secret"]).verify(c["body"], c["expected_headers"]["X-Faas-Signature"])


def headers_of(c: dict) -> dict[str, str]:
    return {k.lower(): v for k, v in c["expected_headers"].items()}


def test_verify_event_routes_both_kinds():
    o = case("order_delivered")
    order = WebhookVerifier(o["secret"]).verify_event(o["body"], headers_of(o), now=o["timestamp"])
    assert isinstance(order, WebhookEvent) and order.order_id == "5f0c6c2e-8d1a-4c3b-9e2f-1a2b3c4d5e6f"
    u = case("utf8_body")
    tenant = WebhookVerifier(u["secret"]).verify_event(u["body"].encode("utf-8"), headers_of(u), now=u["timestamp"])
    assert isinstance(tenant, TenantEvent) and tenant.data["note"] == "Привет ⭐"


def test_verify_event_legacy_fallback_only_for_orders_and_only_without_v2():
    o = case("order_delivered")
    legacy = {"X-Faas-Signature": o["expected_headers"]["X-Faas-Signature"]}
    assert isinstance(WebhookVerifier(o["secret"]).verify_event(o["body"], legacy), WebhookEvent)
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier(o["secret"]).verify_event(o["body"], legacy, require_signature_v2=True)
    e = case("envelope_campaign_paid")
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier(e["secret"]).verify_event(e["body"], {"x-faas-signature": e["expected_headers"]["X-Faas-Signature"]})


def test_a_bad_v2_is_never_rescued_by_a_good_legacy_signature():
    o = case("order_delivered")
    headers = {**headers_of(o), "x-faas-signature-v2": "t=1,v1=00"}
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier(o["secret"]).verify_event(o["body"], headers, now=o["timestamp"])


def test_verify_event_legacy_path_also_accepts_your_previous_secret():
    o = case("order_delivered")
    legacy = {"X-Faas-Signature": o["expected_headers"]["X-Faas-Signature"]}
    verifier = WebhookVerifier("whsec_rotated_to", previous_secret=o["secret"])
    assert isinstance(verifier.verify_event(o["body"], legacy), WebhookEvent)
    with pytest.raises(WebhookVerificationError):
        WebhookVerifier("whsec_rotated_to", previous_secret="whsec_other").verify_event(o["body"], legacy)


# ─── a misconfigured replay window fails closed ──────────────────────────────

BAD_WINDOWS = [float("nan"), float("inf"), float("-inf"), -1, True, "300"]


@pytest.mark.parametrize("bad", BAD_WINDOWS, ids=repr)
def test_a_misconfigured_tolerance_raises_instead_of_accepting(bad):
    c = case("envelope_campaign_paid")
    stale = c["timestamp"] + 10_000  # only a broken tolerance check would still accept this
    with pytest.raises(MyStarsValidationError, match="tolerance_sec"):
        verify_webhook_signature_v2(c["body"], c["expected_headers"][H], c["secret"], tolerance_sec=bad, now=stale)
    with pytest.raises(MyStarsValidationError, match="tolerance_sec"):
        verify_webhook_signature_v2(c["body"], None, c["secret"], tolerance_sec=bad)
    with pytest.raises(MyStarsValidationError, match="tolerance_sec"):
        WebhookVerifier(c["secret"], tolerance_sec=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1, True], ids=repr)
def test_a_misconfigured_now_raises_instead_of_accepting(bad):
    c = case("envelope_campaign_paid")
    header = c["expected_headers"][H]
    with pytest.raises(MyStarsValidationError, match="now"):
        verify_webhook_signature_v2(c["body"], header, c["secret"], now=bad)
    verifier = WebhookVerifier(c["secret"])
    with pytest.raises(MyStarsValidationError, match="now"):
        verifier.verify_tenant_event(c["body"], header, now=bad)
    with pytest.raises(MyStarsValidationError, match="now"):
        verifier.verify_event(c["body"], headers_of(c), now=bad)
    o = case("order_delivered")
    with pytest.raises(MyStarsValidationError, match="now"):  # the legacy-only path too
        WebhookVerifier(o["secret"]).verify_event(o["body"], {"X-Faas-Signature": o["expected_headers"]["X-Faas-Signature"]}, now=bad)



def test_an_order_webhook_reads_its_reversal_reference():
    # `order.failed` / `order.reversed` carry reversal_tx since contract 2.1.4; the others do not.
    event = WebhookEvent.from_dict(
        {"order_id": "o-1", "status": "reversed", "failure_reason": "undeliverable", "reversal_tx": "abc"}
    )
    assert event.reversal_tx == "abc"
    assert WebhookEvent.from_dict({"order_id": "o-1", "status": "delivered"}).reversal_tx is None


def test_an_order_webhook_reads_fragments_refusal_text():
    # `order.failed` / `order.reversed` carry telegram_message since contract 2.3.0; the others do not.
    refusal = "You can buy a minimum of 12,500 stars"
    event = WebhookEvent.from_dict({"order_id": "o-2", "status": "failed", "telegram_message": refusal})
    assert event.telegram_message == refusal
    assert WebhookEvent.from_dict({"order_id": "o-2", "status": "delivered"}).telegram_message is None
