"""Cross-language parity: Python must reproduce the contract/*.json fixtures."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import CONTRACT_DIR, load_contract

from mystars_faas import (
    CONTRACT_VERSION,
    apply_retail_markup,
    build_comment_payload,
    build_jetton_transfer_payload,
    ceil_usd_to_cents,
    to_micro,
    to_nano,
    verify_webhook_signature,
)
from mystars_faas.models import PaymentInstruction
from mystars_faas.payment import build_ton_deeplink
from mystars_faas.webhook import WebhookVerifier


def test_contract_version_matches_fixture():
    assert (CONTRACT_DIR / "CONTRACT_VERSION").read_text().strip() == CONTRACT_VERSION
    for name in ("status-machine.json", "webhook-vectors.json", "markup-vectors.json", "deeplink-vectors.json"):
        assert load_contract(name)["contract_version"] == CONTRACT_VERSION


# ─── B4: status-machine parity (mirrors the TS contract.test.ts assertions) ──

def test_status_machine_fixture_matches_python_constants():
    from mystars_faas.models import (
        CANCELLABLE_STATUSES,
        INITIAL_STATUS,
        ORDER_STATUSES,
        TERMINAL_STATUSES,
        WEBHOOK_TERMINAL_STATUSES,
    )

    fixture = load_contract("status-machine.json")
    assert len(fixture["statuses"]) == 15
    assert set(ORDER_STATUSES) == set(fixture["statuses"])
    assert len(ORDER_STATUSES) == 15

    assert TERMINAL_STATUSES == set(fixture["terminal"])
    assert len(TERMINAL_STATUSES) == 5
    # every terminal status is also a known status
    for t in fixture["terminal"]:
        assert t in ORDER_STATUSES

    assert WEBHOOK_TERMINAL_STATUSES == set(fixture["webhook_terminal"])
    assert CANCELLABLE_STATUSES == set(fixture["cancellable_from"])
    assert INITIAL_STATUS == fixture["initial_on_create"]


# ─── webhook vectors ─────────────────────────────────────────────────────────

def test_webhook_vectors():
    v = load_contract("webhook-vectors.json")
    case = v["cases"][0]
    assert verify_webhook_signature(case["body"], case["signature"], case["secret"]) is True
    assert verify_webhook_signature(case["body"] + " ", case["signature"], case["secret"]) is False
    assert verify_webhook_signature(case["body"], case["signature"], "wrong") is False

    rot = v["rotation"]
    assert verify_webhook_signature(rot["body"], rot["header"], rot["secret"]) is True
    assert verify_webhook_signature(rot["body"], rot["header"], rot["previous_secret"]) is True
    assert verify_webhook_signature(rot["body"], rot["header"], "neither") is False

    # An attacker-controlled non-ASCII header must return False, not raise TypeError.
    assert verify_webhook_signature(case["body"], "déadbeef", case["secret"]) is False


def test_webhook_verifier_parses_event():
    v = load_contract("webhook-vectors.json")["cases"][0]
    event = WebhookVerifier(v["secret"]).verify(v["body"], v["signature"])
    assert event.order_id == "order-123"
    assert event.status == "delivered"


# ─── markup vectors ──────────────────────────────────────────────────────────

def test_ceil_usd_to_cents_vectors():
    for case in load_contract("markup-vectors.json")["ceil_usd_to_cents"]:
        assert ceil_usd_to_cents(case["usd"]) == Decimal(str(case["cents"]))


@pytest.mark.parametrize("case", load_contract("markup-vectors.json")["retail_markup"], ids=lambda c: c["name"])
def test_retail_markup_vectors(case):
    q = apply_retail_markup(case["input"], margin_pct=case["config"]["marginPct"], pass_through_processing_fee=case["config"].get("passThroughProcessingFee", True))
    exp = case["expected"]
    assert q.goods == exp["goods"]
    assert q.markup == exp["markup"]
    assert q.subtotal == exp["subtotal"]
    assert q.processing_fee == exp["processingFee"]
    assert q.total == exp["total"]
    assert q.profit == exp["profit"]


# ─── deeplink / BoC vectors ──────────────────────────────────────────────────

def test_conversion_vectors():
    for case in load_contract("deeplink-vectors.json")["conversions"]:
        got = to_nano(case["amount"]) if case["currency"] == "ton" else to_micro(case["amount"])
        assert str(got) == case["smallest"]


def test_comment_payload_vectors():
    for case in load_contract("deeplink-vectors.json")["comment_payload"]:
        assert build_comment_payload(case["comment"]) == case["boc_base64"]


def test_jetton_payload_vectors():
    for case in load_contract("deeplink-vectors.json")["jetton_payload"]:
        boc = build_jetton_transfer_payload(case["amount_micro"], case["destination"], case["sender"], case["memo"])
        assert boc == case["boc_base64"]


def test_ton_deeplink_vectors():
    for case in load_contract("deeplink-vectors.json")["ton_deeplink"]:
        payment = PaymentInstruction(
            currency="ton", chain="ton", pay_to_address=case["pay_to_address"], memo=case["memo"],
            amount=Decimal(case["amount"]), amount_units="ton", fee=None,
        )
        assert build_ton_deeplink(payment) == case["deeplink"]
