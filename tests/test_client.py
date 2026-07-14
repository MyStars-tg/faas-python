from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import API_KEY, make_client

from mystars_faas import MyStarsValidationError, RateLimitedError, ServiceUnavailableError
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


def test_get_pricing_validates_quantity():
    client, calls = make_client([{"json": QUOTE}])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing(type="stars", quantity=10)
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
        client.get_pricing_batch(quantities=[])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=[10])
    with pytest.raises(MyStarsValidationError):
        client.get_pricing_batch(quantities=list(range(50, 251)))
    assert calls == []


def test_check_recipient_canonicalizes_username():
    client, calls = make_client([{"json": {"resolved": True, "eligible": True, "recipient_name": "Pavel", "reason": None, "telegram_message": None}}])
    import json
    client.check_recipient("@Durov", type="stars")
    body = json.loads(calls[0].content)
    assert body == {"type": "stars", "recipient": {"username": "durov"}}


def test_create_order_sends_idempotency_key_and_replayed_flag():
    client, calls = make_client([{"status": 201, "json": CREATED}])
    res = client.create_order(type="stars", recipient="durov", quantity=100)
    assert res.order_id == "o-1"
    assert res.replayed is False
    assert res.payment.memo == "o-1"
    assert len(calls[0].headers["idempotency-key"]) == 36

    client2, _ = make_client([{"status": 200, "json": CREATED}])
    assert client2.create_order(type="stars", recipient="durov", quantity=100).replayed is True


def test_create_order_reuses_idempotency_key_across_retries():
    client, calls = make_client([
        {"status": 503, "json": {"error": {"code": "unavailable", "message": "down"}}},
        {"status": 201, "json": CREATED},
    ])
    client.create_order(type="stars", recipient="durov", quantity=100)
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
        {"json": {"currencies": [{"code": "ton", "chain": "ton", "name": "GRAM (TON)"}]}},
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
        client.create_order(type="stars", recipient="durov", quantity=100)
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
