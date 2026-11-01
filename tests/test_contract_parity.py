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
    for name in (
        "status-machine.json",
        "webhook-vectors.json",
        "markup-vectors.json",
        "deeplink-vectors.json",
        "webhook-v2-vectors.json",
        "campaign-status-machine.json",
        "giveaway-status-machine.json",
        "series-status-machine.json",
    ):
        assert load_contract(name)["contract_version"] == CONTRACT_VERSION


# ─── B4: status-machine parity (mirrors the TS contract.test.ts assertions) ──

def test_completed_is_terminal():
    """A completed order is final, like a delivered one: wait_for_order stops on it."""
    from mystars_faas import is_terminal

    assert is_terminal("completed")


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
    assert len(TERMINAL_STATUSES) == 6
    # every terminal status is also a known status
    for t in fixture["terminal"]:
        assert t in ORDER_STATUSES

    assert WEBHOOK_TERMINAL_STATUSES == set(fixture["webhook_terminal"])
    assert CANCELLABLE_STATUSES == set(fixture["cancellable_from"])
    assert INITIAL_STATUS == fixture["initial_on_create"]


# ─── partner state machines (contract 2.1.0) ─────────────────────────────────

def test_partner_state_machines_match_python_constants():
    from typing import get_args

    from mystars_faas.models import TENANT_EVENT_TYPES
    from mystars_faas.partner_types import (
        TERMINAL_CAMPAIGN_STATUSES,
        CampaignDeliveryStatus,
        CampaignStatus,
        CampaignValidationVerdict,
        GiveawayPrizeType,
        GiveawaySeriesStatus,
        GiveawayStatus,
    )

    campaign = load_contract("campaign-status-machine.json")
    giveaway = load_contract("giveaway-status-machine.json")
    series = load_contract("series-status-machine.json")
    for machine in (campaign, giveaway, series):
        statuses = set(machine["statuses"])
        assert set(machine["terminal"]) <= statuses
        for source, targets in machine["transitions"].items():
            assert source in statuses and set(targets) <= statuses, source

    assert TERMINAL_CAMPAIGN_STATUSES == set(campaign["terminal"])
    assert set(get_args(CampaignStatus)) == set(campaign["statuses"])
    assert set(get_args(CampaignValidationVerdict)) == set(campaign["validation_verdicts"])
    assert set(get_args(CampaignDeliveryStatus)) == set(campaign["delivery_statuses"])
    assert set(get_args(GiveawayStatus)) == set(giveaway["statuses"])
    assert set(get_args(GiveawayPrizeType)) == set(giveaway["prize_types"])
    assert set(get_args(GiveawaySeriesStatus)) == set(series["statuses"])

    events = campaign["events"] + giveaway["events"] + series["events"]
    assert len(set(TENANT_EVENT_TYPES)) == len(TENANT_EVENT_TYPES)
    assert sorted(TENANT_EVENT_TYPES) == sorted(events)


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
