from __future__ import annotations

import json
from decimal import Decimal

import pytest

from mystars_faas import (
    MyStarsValidationError,
    build_payment_request,
    build_ton_connect_messages,
    build_ton_deeplink,
    parse_ton_address,
    to_micro,
    to_nano,
)
from mystars_faas.cli import build_parser, dispatch
from mystars_faas.models import PaymentInstruction

PAY_TO = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


def _ton_payment(**over):
    base = dict(currency="ton", chain="ton", pay_to_address=PAY_TO, memo="m", amount=Decimal("1.5"), amount_units="ton", fee=None)
    base.update(over)
    return PaymentInstruction(**base)


# ─── B6: to_nano / to_micro decimal-regex parity with TS DECIMAL_RE ──────────

def test_to_units_accepts_plain_decimals():
    assert to_nano("1") == 1_000_000_000
    assert to_nano("1.5") == 1_500_000_000
    assert to_micro("4.99") == 4_990_000
    assert to_nano(Decimal("1.5")) == 1_500_000_000
    assert to_nano(2) == 2_000_000_000


@pytest.mark.parametrize("bad", ["-1.5", "1e3", "+1.5", "1.", ".5", " 1", "1 ", "0x10", "nan", "inf", ""])
def test_to_units_rejects_non_decimal_forms(bad):
    # TS DECIMAL_RE = /^\d+(\.\d+)?$/ rejects a sign, scientific notation, etc. A payment amount
    # is never negative, so "-1.5" must fail like any other non-amount.
    # NOTE: a *string* "1e3" stays rejected — only Decimal/int inputs are normalised.
    with pytest.raises(MyStarsValidationError):
        to_nano(bad)


def test_to_units_accepts_decimal_in_scientific_notation():
    # Regression: str(Decimal('1E-9')) == "1E-9" (scientific notation) used to be rejected
    # by the plain-decimal grammar even though the Decimal value is valid. A Decimal/int is
    # now normalised to fixed-point first (format(d, 'f')), so these convert correctly.
    assert to_nano(Decimal("1E-9")) == 1
    assert to_nano(Decimal("0.000000001")) == 1
    assert to_nano(Decimal("1E3")) == 1_000_000_000_000  # 1000 TON × 1e9
    assert to_micro(Decimal("1E-6")) == 1
    # Non-finite Decimals still raise (format(d, 'f') -> "NaN"/"Infinity", regex rejects).
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(MyStarsValidationError):
            to_nano(bad)


# ─── payment ─────────────────────────────────────────────────────────────────

def test_parse_ton_address_friendly():
    wc, h = parse_ton_address(PAY_TO)
    assert wc == 0 and len(h) == 32


def test_parse_ton_address_bad_checksum():
    with pytest.raises(MyStarsValidationError):
        parse_ton_address("EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDX")


def test_build_ton_deeplink():
    assert build_ton_deeplink(_ton_payment()).startswith(f"ton://transfer/{PAY_TO}?amount=1500000000&text=")


def test_build_payment_request_ton_full_set():
    req = build_payment_request(_ton_payment())
    assert req.amount_smallest_unit == "1500000000"
    assert req.ton_deeplink.startswith(f"ton://transfer/{PAY_TO}?amount=1500000000")
    assert req.tonkeeper_link.startswith("https://app.tonkeeper.com/transfer/")
    assert req.qr_payload == req.ton_deeplink
    assert req.ton_connect[0].address == PAY_TO
    assert req.ton_connect[0].payload  # op-0 comment BoC


def test_build_payment_request_usdt_without_wallet_has_note():
    req = build_payment_request(_ton_payment(currency="usdt_ton", amount_units="usdt", amount=Decimal("4.99")))
    assert req.amount_smallest_unit == "4990000"
    assert req.ton_connect == []
    assert req.note


def test_build_ton_connect_messages_usdt_with_wallet():
    jw = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"
    msgs = build_ton_connect_messages(
        _ton_payment(currency="usdt_ton", amount_units="usdt", amount=Decimal("4.99")),
        sender_address=jw, jetton_wallet_address=jw,
    )
    assert msgs[0].address == jw
    assert msgs[0].amount == "50000000"  # 0.05 TON gas
    assert msgs[0].payload


def test_build_ton_connect_messages_usdt_requires_jetton_wallet():
    with pytest.raises(MyStarsValidationError):
        build_ton_connect_messages(_ton_payment(currency="usdt_ton", amount_units="usdt", amount=Decimal("4.99")))


# ─── payment-instruction guard ───────────────────────────────────────────────

@pytest.mark.parametrize("builder", [build_payment_request, build_ton_deeplink, build_ton_connect_messages])
def test_builders_reject_a_zero_amount(builder):
    with pytest.raises(MyStarsValidationError, match="positive"):
        builder(_ton_payment(amount=Decimal("0")))



@pytest.mark.parametrize("builder", [build_payment_request, build_ton_deeplink, build_ton_connect_messages])
def test_builders_reject_an_unknown_currency_instead_of_treating_it_as_usdt(builder):
    payment = _ton_payment(currency="usdt_eth", amount_units="usdt")
    with pytest.raises(MyStarsValidationError, match="unknown payment.currency"):
        builder(payment, sender_address=PAY_TO, jetton_wallet_address=PAY_TO) if builder is build_ton_connect_messages else builder(payment)



def test_builders_reject_amount_units_that_contradict_the_currency():
    with pytest.raises(MyStarsValidationError, match="amount_units"):
        build_payment_request(_ton_payment(amount_units="usdt"))
    with pytest.raises(MyStarsValidationError, match="amount_units"):
        build_payment_request(_ton_payment(currency="usdt_ton", amount_units="ton"))



@pytest.mark.parametrize(("field_name", "value"), [("asset", "USDT"), ("decimals", 6), ("transfer", "jetton")])
def test_builders_reject_a_v1_15_field_that_contradicts_the_currency(field_name, value):
    with pytest.raises(MyStarsValidationError, match=f"payment.{field_name}"):
        build_payment_request(_ton_payment(**{field_name: value}))


def test_builders_reject_an_amount_smallest_unit_that_disagrees_with_amount():
    with pytest.raises(MyStarsValidationError, match="payment.amount_smallest_unit"):
        build_payment_request(_ton_payment(amount=Decimal("1.0"), amount_smallest_unit="2000000000"))


def test_builders_accept_a_fully_consistent_v1_15_block():
    gram = _ton_payment(asset="GRAM", decimals=9, transfer="native", amount_smallest_unit="1500000000")
    assert build_payment_request(gram).amount_smallest_unit == "1500000000"
    usdt = _ton_payment(currency="usdt_ton", amount_units="usdt", amount=Decimal("4.99"), asset="USDT", decimals=6, transfer="jetton")
    assert build_payment_request(usdt).amount_smallest_unit == "4990000"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _capture():
    out = []
    return out, lambda s: out.append(s)


@pytest.mark.parametrize(
    "argv",
    [
        ["pricing", "--type", "stars", "--quantity", "100"],
        ["orders-create", "--type", "stars", "--recipient", "durov", "--quantity", "100"],
    ],
)
def test_cli_requires_currency_for_pricing_and_orders_create(argv, capsys):
    # API 2.0.0 has no currency default, so the CLI refuses to send a request without one.
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code == 2
    assert "--currency" in capsys.readouterr().err


def test_cli_webhook_verify_offline():
    out, sink = _capture()
    ns = build_parser().parse_args([
        "webhook-verify",
        "--secret", "tenant-webhook-secret-aaaaaaaaaaaaaaaaaaaa",
        "--body", '{"order_id":"order-123","status":"delivered"}',
        "--signature", "e56e9f643c8b3bc9b99253e4cee767528ec1cfc8866eec08a868638b0fbc8194",
    ])
    rc = dispatch(ns, client_factory=lambda: (_ for _ in ()).throw(AssertionError("no client expected")), out=sink)
    assert rc == 0
    assert json.loads(out[0]) == {"valid": True}


_WH_SECRET = "tenant-webhook-secret-aaaaaaaaaaaaaaaaaaaa"
_WH_BODY = '{"order_id":"order-123","status":"delivered"}'
_WH_SIG = "e56e9f643c8b3bc9b99253e4cee767528ec1cfc8866eec08a868638b0fbc8194"


def _NO_CLIENT():
    raise AssertionError("no client expected")


def test_cli_webhook_verify_secret_from_env(monkeypatch):
    # B6: --secret may be omitted; MYSTARS_WEBHOOK_SECRET is the (preferred) source.
    monkeypatch.setenv("MYSTARS_WEBHOOK_SECRET", _WH_SECRET)
    out, sink = _capture()
    ns = build_parser().parse_args(["webhook-verify", "--body", _WH_BODY, "--signature", _WH_SIG])
    assert dispatch(ns, client_factory=_NO_CLIENT, out=sink) == 0
    assert json.loads(out[0]) == {"valid": True}


def test_cli_webhook_verify_env_preferred_over_argv(monkeypatch):
    monkeypatch.setenv("MYSTARS_WEBHOOK_SECRET", _WH_SECRET)
    out, sink = _capture()
    ns = build_parser().parse_args(["webhook-verify", "--secret", "wrong-argv-secret", "--body", _WH_BODY, "--signature", _WH_SIG])
    assert dispatch(ns, client_factory=_NO_CLIENT, out=sink) == 0
    assert json.loads(out[0]) == {"valid": True}  # env secret won, so signature still matches


def test_cli_webhook_verify_missing_secret_errors(monkeypatch):
    monkeypatch.delenv("MYSTARS_WEBHOOK_SECRET", raising=False)
    out, sink = _capture()
    ns = build_parser().parse_args(["webhook-verify", "--body", _WH_BODY, "--signature", _WH_SIG])
    assert dispatch(ns, client_factory=_NO_CLIENT, out=sink) == 1
    assert out == []


def test_cli_pricing_with_fake_client():
    class FakeClient:
        def get_pricing(self, **kw):
            self.kw = kw
            return {"amount": "1.23", "currency": "ton"}

    fake = FakeClient()
    out, sink = _capture()
    ns = build_parser().parse_args(["pricing", "--type", "stars", "--quantity", "100", "--currency", "ton"])
    dispatch(ns, client_factory=lambda: fake, out=sink)
    assert fake.kw == {"type": "stars", "quantity": 100, "months": None, "payment_currency": "ton"}
    assert json.loads(out[0])["amount"] == "1.23"
