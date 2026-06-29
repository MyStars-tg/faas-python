from __future__ import annotations

import json

import httpx
import pytest

from mystars_faas import AsyncMyStarsClient
from mystars_faas._transport import RetryPolicy

API_KEY = "faas_" + "b" * 64

CREATED = {"order_id": "o-1", "status": "awaiting_payment", "type": "stars", "quantity": 100, "months": None, "payment": {"currency": "ton", "chain": "ton", "pay_to_address": "EQx", "memo": "o-1", "amount": "1.0", "amount_units": "ton", "fee": None}, "expires_at": "2026-06-25T00:15:00Z"}


def _transport(script):
    calls = []

    def handler(request):
        idx = len(calls)
        calls.append(request)
        spec = script[min(idx, len(script) - 1)]
        body = spec.get("json")
        return httpx.Response(spec.get("status", 200), headers={"content-type": "application/json"}, content=b"" if body is None else json.dumps(body).encode())

    return httpx.MockTransport(handler), calls


async def _noop_sleep(_s):
    return None


@pytest.mark.asyncio
async def test_async_create_and_paginate():
    transport, calls = _transport([
        {"status": 503, "json": {"error": {"code": "unavailable", "message": "down"}}},
        {"status": 201, "json": CREATED},
    ])
    async with AsyncMyStarsClient(API_KEY, transport=transport, retry=RetryPolicy(base_delay=0.001, jitter=False), sleep=_noop_sleep, rand=lambda: 0.0) as client:
        res = await client.create_order(type="stars", recipient="durov", quantity=100)
        assert res.order_id == "o-1"
        # idempotency key reused across the retry
        assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]


@pytest.mark.asyncio
async def test_async_cancel_order_empty_2xx_body_does_not_crash():
    transport, _ = _transport([{"status": 200}])  # empty-body 2xx
    async with AsyncMyStarsClient(API_KEY, transport=transport) as client:
        result = await client.cancel_order("o-1")
    assert result == {"order_id": "o-1", "status": "cancelled"}


@pytest.mark.asyncio
async def test_async_await_order_returns_on_terminal():
    order = {"order_id": "o-1", "status": "delivered", "type": "stars", "recipient_username": "x", "quantity": 1, "months": None, "amount_ton": "1", "payment_tx": None, "purchase_tx": None, "failure_reason": None, "reversal_tx": None, "telegram_message": None, "created_at": "2026-06-25T00:00:00Z", "updated_at": "2026-06-25T00:00:00Z", "expires_at": None}
    transport, _ = _transport([{"json": order}])
    async with AsyncMyStarsClient(API_KEY, transport=transport, sleep=_noop_sleep, rand=lambda: 0.0) as client:
        final = await client.await_order("o-1")
    assert final.status == "delivered"


@pytest.mark.asyncio
async def test_async_aiter_orders():
    order = {"order_id": "a", "status": "delivered", "type": "stars", "recipient_username": "x", "quantity": 1, "months": None, "amount_ton": "1", "payment_tx": None, "purchase_tx": None, "failure_reason": None, "reversal_tx": None, "telegram_message": None, "created_at": "2026-06-25T00:00:00Z", "updated_at": "2026-06-25T00:00:00Z", "expires_at": None}
    transport, _ = _transport([{"json": {"orders": [order], "next_cursor": None}}])
    async with AsyncMyStarsClient(API_KEY, transport=transport) as client:
        ids = [o.order_id async for o in client.aiter_orders()]
    assert ids == ["a"]
