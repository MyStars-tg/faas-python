from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import API_KEY, make_client

from mystars_faas import FeeBreakdown, MyStarsValidationError, RateLimitedError, ServiceUnavailableError
from mystars_faas._transport import RetryPolicy

QUOTE = {"type": "stars", "quantity": 100, "months": None, "amount": "1.2345", "currency": "ton", "fee": None, "usdt_per_ton": "5.5", "quoted_at": "2026-06-25T00:00:00Z", "valid_until": "2026-06-25T00:01:00Z"}
CREATED = {"order_id": "o-1", "status": "awaiting_payment", "type": "stars", "quantity": 100, "months": None, "payment": {"currency": "ton", "chain": "ton", "pay_to_address": "EQx", "memo": "o-1", "amount": "1.2345", "amount_units": "ton", "fee": None}, "expires_at": "2026-06-25T00:15:00Z"}
ORDER = {"order_id": "o-1", "status": "delivered", "type": "stars", "recipient_username": "durov", "quantity": 100, "months": None, "amount_ton": "1.2", "payment_tx": "a", "purchase_tx": "b", "failure_reason": None, "reversal_tx": None, "telegram_message": None, "created_at": "2026-06-25T00:00:00Z", "updated_at": "2026-06-25T00:05:00Z", "expires_at": None}


def test_auth_header_and_no_idempotency_on_reads():
    client, calls = make_client([{"json": {"currencies": []}}])
    client.list_currencies()
    assert calls[0].headers["x-api-key"] == API_KEY
    assert calls[0].headers["accept"] == "application/json"
    assert "idempotency-key" not in calls[0].headers


def test_get_pricing_builds_query():
    client, calls = make_client([{"json": QUOTE}])
    quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
    from decimal import Decimal
    assert quote.amount == Decimal("1.2345")
    q = parse_qs(urlparse(str(calls[0].url)).query)
    assert q["type"] == ["stars"] and q["quantity"] == ["100"] and q["payment_currency"] == ["ton"]


@pytest.mark.parametrize(
    ("fee", "kind"),
    [
        ({"subtotal": "5.00", "processing_fee": "0.56", "total": "5.56", "description": "1% swap + 0.5 GRAM gas", "kind": "swap", "currency": "usdt"}, "swap"),
        ({"subtotal": "5.75", "processing_fee": "0.04", "total": "5.79", "description": "TON network gas", "kind": "network", "currency": "usdt"}, "network"),
        # A server older than contract 1.13.0 sends no `kind`; its fees are all swap-backed.
        ({"subtotal": "5.00", "processing_fee": "0.56", "total": "5.56", "description": "1% swap + 0.5 GRAM gas", "currency": "usdt"}, "swap"),
    ],
)
def test_fee_breakdown_parses_kind(fee, kind):
    assert FeeBreakdown.from_dict(fee).kind == kind


def test_get_pricing_validates_quantity():
    client, calls = make_client([{"json": QUOTE}])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing(type="stars", quantity=10, payment_currency="ton")
    assert calls == []


def test_get_pricing_batch_builds_query_and_parses_entries():
    batch = {
        "type": "stars",
        "currency": "ton",
        "quotes": [
            {"quantity": 50, "amount": "0.5000", "fee": None},
            {"quantity": 500, "amount": "5.0000", "fee": None},
        ],
        "usdt_per_ton": "5.5",
        "quoted_at": "2026-07-10T00:00:00.000Z",
        "valid_until": "2026-07-10T00:01:00.000Z",
    }
    client, calls = make_client([{"json": batch}])
    res = client.get_pricing_batch(quantities=[50, 500], payment_currency="ton")
    from decimal import Decimal
    assert [e.quantity for e in res.quotes] == [50, 500]
    assert res.quotes[1].amount == Decimal("5.0000")
    q = parse_qs(urlparse(str(calls[0].url)).query)
    assert q["type"] == ["stars"] and q["quantities"] == ["50,500"] and q["payment_currency"] == ["ton"]


def test_get_pricing_batch_validates_before_any_request():
    client, calls = make_client([])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=[], payment_currency="ton")
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=[10], payment_currency="ton")
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=list(range(50, 251)), payment_currency="ton")
    assert calls == []


def test_check_recipient_canonicalizes_username():
    client, calls = make_client([{"json": {"resolved": True, "eligible": True, "recipient_name": "Pavel", "reason": None, "telegram_message": None}}])
    import json
    client.check_recipient("@Durov", type="stars")
    body = json.loads(calls[0].content)
    assert body == {"type": "stars", "recipient": {"username": "durov"}}


def test_check_recipient_exposes_indeterminate_true():
    """A failed-open check: `eligible` is only a permissive default, and says so."""
    client, _ = make_client([{"json": {"resolved": True, "eligible": True, "recipient_name": None, "reason": None, "telegram_message": None, "indeterminate": True}}])
    check = client.check_recipient("durov", type="stars")
    assert check.indeterminate is True
    # The two cases must stay distinguishable — `eligible` alone cannot tell them apart.
    assert check.eligible is True


def test_check_recipient_exposes_indeterminate_false_on_a_real_verdict():
    client, _ = make_client([{"json": {"resolved": True, "eligible": False, "recipient_name": "Pavel", "reason": "already_subscribed", "telegram_message": "already has Premium", "indeterminate": False}}])
    check = client.check_recipient("durov", type="premium", months=3)
    assert check.indeterminate is False
    assert check.reason == "already_subscribed"


def test_check_recipient_defaults_indeterminate_when_field_absent():
    """Back-compat: a server older than contract 1.11.0 omits the field; absent == False."""
    client, _ = make_client([{"json": {"resolved": True, "eligible": True, "recipient_name": "Pavel", "reason": None, "telegram_message": None}}])
    check = client.check_recipient("durov", type="stars")
    assert check.indeterminate is False
    assert check.eligible is True


def test_create_order_sends_idempotency_key_and_replayed_flag():
    client, calls = make_client([{"status": 201, "json": CREATED}])
    res = client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert res.order_id == "o-1"
    assert res.replayed is False
    assert res.payment.memo == "o-1"
    assert len(calls[0].headers["idempotency-key"]) == 36

    client2, _ = make_client([{"status": 200, "json": CREATED}])
    assert client2.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton").replayed is True


def test_create_order_reuses_idempotency_key_across_retries():
    client, calls = make_client([
        {"status": 503, "json": {"error": {"code": "unavailable", "message": "down"}}},
        {"status": 201, "json": CREATED},
    ])
    client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert len(calls) == 2
    assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]


def test_iter_orders_paginates():
    page1 = {"orders": [dict(ORDER, order_id="a")], "next_cursor": "c1"}
    page2 = {"orders": [dict(ORDER, order_id="b")], "next_cursor": None}

    def script(request, idx):
        cursor = parse_qs(urlparse(str(request.url)).query).get("cursor", [None])[0]
        return {"json": page2 if cursor == "c1" else page1}

    client, calls = make_client(script)
    ids = [o.order_id for o in client.iter_orders(status="delivered")]
    assert ids == ["a", "b"]
    assert len(calls) == 2


def test_retry_503_then_succeeds():
    client, calls = make_client([
        {"status": 503, "json": {"error": {"code": "unavailable", "message": "down"}}},
        {"json": {"currencies": [{"code": "ton", "chain": "ton", "name": "GRAM"}]}},
    ])
    assert len(client.list_currencies()) == 1
    assert len(calls) == 2


def test_retry_honors_retry_after_on_general_429():
    sleeps = []
    client, _ = make_client(
        [
            {"status": 429, "json": {"error": {"code": "rate_limited", "message": "slow"}}, "headers": {"ratelimit-limit": "60", "retry-after": "2"}},
            {"json": {"currencies": []}},
        ],
        retry=RetryPolicy(base_delay=0.001, jitter=False),
        sleeps=sleeps,
    )
    client.list_currencies()
    assert sleeps == [2.0]


def test_order_cap_429_not_retried():
    client, calls = make_client([{"status": 429, "json": {"error": {"code": "rate_limited", "message": "daily order cap reached"}}}])
    with pytest.raises(RateLimitedError) as exc:
        client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert exc.value.kind == "order_cap"
    assert len(calls) == 1


def test_exhausts_retries_then_raises():
    client, calls = make_client([{"status": 503, "json": {"error": {"code": "unavailable", "message": "down"}}}])
    with pytest.raises(ServiceUnavailableError):
        client.list_currencies()
    assert len(calls) == 4  # 1 + 3 retries


def test_cancel_order_with_body():
    client, _ = make_client([{"status": 200, "json": {"order_id": "o-9", "status": "cancelled"}}])
    assert client.cancel_order("o-9") == {"order_id": "o-9", "status": "cancelled"}


def test_cancel_order_empty_2xx_body_does_not_crash():
    # A 204 / empty-body 2xx must not TypeError on data["order_id"].
    client, _ = make_client([{"status": 200}])
    result = client.cancel_order("o-1")
    assert result["order_id"] == "o-1"
    assert result["status"] == "cancelled"


def test_reconcile_returns_missed_terminal_orders():
    client, _ = make_client([{"json": {"orders": [dict(ORDER, order_id="miss", status="delivered")], "next_cursor": None}}])
    missed = client.reconcile(is_known=lambda o: False)
    assert [o.order_id for o in missed] == ["miss"]


def test_reconcile_stops_at_since_cutoff():
    orders = [
        dict(ORDER, order_id="new", status="delivered", created_at="2026-06-25T03:00:00Z"),
        dict(ORDER, order_id="old", status="delivered", created_at="2026-06-20T00:00:00Z"),
    ]
    client, _ = make_client([{"json": {"orders": orders, "next_cursor": None}}])
    missed = client.reconcile(is_known=lambda o: False, since="2026-06-24T00:00:00Z")
    assert [o.order_id for o in missed] == ["new"]


def test_create_order_rejects_an_unknown_payment_currency_before_any_request():
    client, calls = make_client([{"status": 201, "json": CREATED}])
    with pytest.raises(MyStarsValidationError):
        client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="usdt")  # type: ignore[arg-type]
    assert calls == []


def test_get_pricing_rejects_an_unknown_payment_currency_before_any_request():
    client, calls = make_client([{"json": QUOTE}])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing(type="premium", months=3, payment_currency="gram")  # type: ignore[arg-type]
    assert calls == []


def test_get_pricing_batch_rejects_an_unknown_payment_currency_before_any_request():
    client, calls = make_client([])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=[50], payment_currency="USDT")  # type: ignore[arg-type]
    assert calls == []


def test_payment_currency_is_a_required_argument():
    # API 2.0.0 rejects an omitted currency; the SDK refuses it at the call, before any request.
    client, calls = make_client([])
    with pytest.raises(TypeError, match="payment_currency"):
        client.get_pricing(type="stars", quantity=100)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="payment_currency"):
        client.get_pricing_batch(quantities=[50])  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="payment_currency"):
        client.create_order(type="stars", recipient="durov", quantity=100)  # type: ignore[call-arg]
    assert calls == []


def test_get_order_reads_payment_currency_always_and_payment_only_while_awaiting_payment():
    from decimal import Decimal

    payment = dict(CREATED["payment"], asset="GRAM", decimals=9, amount_smallest_unit="1234500000", transfer="native", jetton_master=None)
    client, _ = make_client([
        {"json": dict(ORDER, status="awaiting_payment", payment_currency="ton", payment=payment)},
        {"json": dict(ORDER, status="delivered", payment_currency="ton", payment=None)},
        {"json": ORDER},
    ])
    open_order = client.get_order("o-1")
    assert open_order.payment_currency == "ton"
    assert open_order.payment is not None
    assert open_order.payment.amount == Decimal("1.2345")
    closed = client.get_order("o-1")  # a closed order offers no pay-to details
    assert (closed.payment_currency, closed.payment) == ("ton", None)
    legacy = client.get_order("o-1")  # a server older than contract 1.15.0
    assert (legacy.payment_currency, legacy.payment) == (None, None)


def test_payment_instruction_reads_the_v1_15_asset_fields_and_tolerates_their_absence():
    from mystars_faas import PaymentInstruction

    usdt = {
        "currency": "usdt_ton", "chain": "ton", "pay_to_address": "EQx", "memo": "o-1", "amount": "4.99",
        "amount_units": "usdt", "fee": None, "asset": "USDT", "decimals": 6, "amount_smallest_unit": "4990000",
        "transfer": "jetton", "jetton_master": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
    }
    p = PaymentInstruction.from_dict(usdt)
    assert (p.asset, p.decimals, p.amount_smallest_unit, p.transfer) == ("USDT", 6, "4990000", "jetton")
    assert p.jetton_master == "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
    legacy = PaymentInstruction.from_dict(CREATED["payment"])  # a server older than contract 1.15.0
    assert (legacy.asset, legacy.decimals, legacy.amount_smallest_unit, legacy.transfer, legacy.jetton_master) == (None,) * 5


def test_the_currency_vocabulary_is_public():
    import mystars_faas

    assert mystars_faas.PAYMENT_CURRENCIES == ("ton", "usdt_ton")
    for name in ("PaymentCurrency", "PAYMENT_CURRENCIES"):
        assert name in mystars_faas.__all__
