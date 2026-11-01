"""Partner error mapping (contract 2.1.0) and giveaway funding blocks (one-time deposit, memo null)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mystars_faas import (
    ConflictError,
    FeatureUnavailableError,
    IdempotencyConflictError,
    IdempotencyInFlightError,
    MyStarsValidationError,
    OrderNotCancellableError,
    PaymentInstruction,
    RecipientIneligibleError,
    ServiceUnavailableError,
    UnprocessableError,
    build_funding_payment_request,
    build_jetton_transfer_payload,
    build_ton_deeplink,
    payment_comment,
    verify_funding_payment,
)
from mystars_faas._transport import should_retry
from mystars_faas.errors import error_from_response

DEPOSIT = "UQDRpcD_7gARIjNEVWZ3iJmqu8zd7v8AESIzRFVmd4iZqgwB"
NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def env(code: str, message: str, **extra):
    return {"error": {"code": code, "message": message, **extra}}


# ─── errors ───────────────────────────────────────────────────────────────────


def test_in_flight_is_typed_retryable_and_carries_retry_after():
    e = error_from_response(409, env("idempotency_in_flight", "a request with this Idempotency-Key is still in progress"), {"retry-after": "1"})
    assert isinstance(e, IdempotencyInFlightError) and isinstance(e, ConflictError)
    assert not isinstance(e, IdempotencyConflictError)
    assert e.retry_after_ms == 1000 and e.retryable
    assert should_retry(e, idempotent=True)


def test_idempotency_conflict_by_code():
    assert isinstance(error_from_response(409, env("idempotency_conflict", "reused"), {}), IdempotencyConflictError)


def test_cannot_cancel_is_order_specific_only_for_orders():
    assert isinstance(error_from_response(409, env("conflict", "order is delivered, cannot cancel"), {}), OrderNotCancellableError)
    campaign = error_from_response(409, env("conflict", "campaign is completed, cannot cancel"), {})
    assert type(campaign) is ConflictError
    giveaway = error_from_response(409, env("not_cancellable", "a drawn giveaway cannot be cancelled", status="drawn"), {})
    assert not isinstance(giveaway, OrderNotCancellableError) and giveaway.details == {"status": "drawn"}


@pytest.mark.parametrize("code", ["product_not_available", "currency_not_available", "channel_checks_failed", "schedule_out_of_bounds", "unprocessable"])
def test_422_other_than_recipient_ineligible_is_unprocessable(code):
    e = error_from_response(422, env(code, "m"), {})
    assert isinstance(e, UnprocessableError) and not isinstance(e, RecipientIneligibleError)


def test_422_recipient_ineligible_and_bare_422_keep_the_legacy_class():
    assert isinstance(error_from_response(422, env("recipient_ineligible", "no", telegram_message="x"), {}), RecipientIneligibleError)
    assert isinstance(error_from_response(422, None, {}), RecipientIneligibleError)


@pytest.mark.parametrize(
    "code",
    ["prize_type_unavailable", "partner_conditions_unavailable", "antibot_enforce_unavailable", "autopost_unavailable", "series_unavailable"],
)
def test_feature_unavailable_is_never_retried(code):
    e = error_from_response(503, env(code, "not yet"), {})
    assert isinstance(e, FeatureUnavailableError) and isinstance(e, ServiceUnavailableError)
    assert not e.retryable and not should_retry(e, idempotent=True)


def test_catalog_unavailable_is_transient():
    e = error_from_response(503, env("gift_catalog_unavailable", "stale"), {})
    assert not isinstance(e, FeatureUnavailableError) and should_retry(e, idempotent=True)


def test_details_are_none_without_extra_fields():
    assert error_from_response(400, env("bad_request", "x"), {}).details is None
    checks = {"bot_is_admin": False, "bot_can_post": False, "owner_is_admin": True}
    assert error_from_response(422, env("channel_checks_failed", "x", checks=checks), {}).details == {"checks": checks}


# ─── funding blocks ──────────────────────────────────────────────────────────


def funding(**over):
    block = {
        "payment_id": "pay-1", "currency": "ton", "chain": "ton", "pay_to_address": DEPOSIT, "memo": None,
        "address_kind": "one_time_deposit", "amount": "1.5", "amount_smallest_unit": "1500000000", "asset": "GRAM",
        "decimals": 9, "transfer": "native", "jetton_master": None, "amount_usd": "4.2", "expires_at": "2026-10-03T14:00:00.000Z",
    }
    block.update(over)
    return block


def test_payment_instruction_reads_a_funding_block():
    p = PaymentInstruction.from_dict(funding())
    assert p.memo is None and p.address_kind == "one_time_deposit" and p.amount_units == "ton" and p.fee is None


def test_payment_comment_coupling():
    assert payment_comment(PaymentInstruction.from_dict(funding())) is None
    assert payment_comment(PaymentInstruction.from_dict(funding(memo="gw", address_kind="shared_wallet"))) == "gw"
    with pytest.raises(MyStarsValidationError, match="memo is missing"):
        payment_comment(PaymentInstruction.from_dict(funding(address_kind="shared_wallet")))
    with pytest.raises(MyStarsValidationError):
        payment_comment(PaymentInstruction.from_dict(funding(memo="x")))


def test_deeplink_of_a_deposit_block_has_no_text():
    assert build_ton_deeplink(PaymentInstruction.from_dict(funding())) == f"ton://transfer/{DEPOSIT}?amount=1500000000"


def test_verify_funding_payment_refuses_expired_and_contradictory_blocks():
    assert verify_funding_payment(funding(), now=NOW) is None
    with pytest.raises(MyStarsValidationError, match="expired"):
        verify_funding_payment(funding(expires_at="2026-10-03T11:59:59.000Z"), now=NOW)
    with pytest.raises(MyStarsValidationError):
        verify_funding_payment(funding(expires_at="not-a-date"), now=NOW)
    with pytest.raises(MyStarsValidationError):
        verify_funding_payment(funding(asset="USDT"), now=NOW)
    with pytest.raises(MyStarsValidationError):
        verify_funding_payment({**funding(), "payment_id": None}, now=NOW)


def test_build_funding_payment_request():
    req = build_funding_payment_request(funding(), now=NOW)
    assert req.memo is None
    assert req.ton_deeplink == f"ton://transfer/{DEPOSIT}?amount=1500000000"
    assert req.tonkeeper_link == f"https://app.tonkeeper.com/transfer/{DEPOSIT}?amount=1500000000"
    assert req.ton_connect[0].payload is None
    with pytest.raises(MyStarsValidationError, match="expired"):
        build_funding_payment_request(funding(expires_at="2026-10-03T11:00:00.000Z"), now=NOW)


def test_comment_free_usdt_ton_connect_message():
    usdt = funding(currency="usdt_ton", asset="USDT", decimals=6, transfer="jetton", amount="2.5", amount_smallest_unit="2500000",
                   jetton_master="EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")
    sender = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
    req = build_funding_payment_request(usdt, now=NOW, sender_address=sender, jetton_wallet_address=sender)
    assert req.ton_connect[0].payload == build_jetton_transfer_payload("2500000", DEPOSIT, sender, None)
