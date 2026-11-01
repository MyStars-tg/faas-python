"""The 429s added in contract 2.2.0: the daily refusal budget on order create, and the quote ceiling's Retry-After."""

from __future__ import annotations

import pytest
from conftest import API_KEY, _mock_transport, make_client

from mystars_faas import AsyncMyStarsClient, RateLimitedError
from mystars_faas._transport import RetryPolicy, should_retry
from mystars_faas.errors import error_from_response

SECONDS_TO_MIDNIGHT = 5400

BUDGET_USED = {
    "status": 429,
    "json": {
        "error": {
            "code": "rate_limited",
            "message": "today's budget of ineligible-recipient refusals is used up; new orders are accepted again after 00:00 UTC",
            "retry_after": SECONDS_TO_MIDNIGHT,
        }
    },
    # ...plus the RateLimit-* headers of the order bucket it passed (the API contract's 429 response).
    "headers": {
        "retry-after": str(SECONDS_TO_MIDNIGHT),
        "ratelimit-limit": "60",
        "ratelimit-remaining": "41",
        "ratelimit-reset": "30",
    },
}
# The same budget while its slots are held only by checks still in flight: a short Retry-After, no retry_after field.
BUDGET_IN_FLIGHT = {
    "status": 429,
    "json": {"error": {"code": "rate_limited", "message": "ineligible-recipient refusal checks are in progress; retry shortly"}},
    "headers": {"retry-after": "3", "ratelimit-limit": "60", "ratelimit-remaining": "40", "ratelimit-reset": "30"},
}
# The shared giveaway-quote ceiling: Retry-After and the RateLimit-* of the tenant's own quote bucket, no retry_after field.
QUOTE_CEILING = {
    "status": 429,
    "json": {"error": {"code": "rate_limited", "message": "rate limit exceeded"}},
    "headers": {"retry-after": "12", "ratelimit-limit": "30", "ratelimit-remaining": "17", "ratelimit-reset": "40"},
}
CREATED = {
    "status": 201,
    "json": {
        "order_id": "id-1",
        "status": "awaiting_payment",
        "type": "stars",
        "quantity": 100,
        "months": None,
        "payment": {"currency": "ton", "chain": "ton", "pay_to_address": "EQx", "memo": "id-1", "amount": "1.0", "amount_units": "ton", "fee": None},
        "expires_at": "2026-06-25T00:15:00.000Z",
    },
}
QUOTE = {"json": {"prize_type": "stars", "prize_quantity_per_winner": 1000, "winner_count": 1}}


def test_refusal_budget_429_is_an_order_cap_that_is_not_retried():
    e = error_from_response(429, BUDGET_USED["json"], BUDGET_USED["headers"])
    assert isinstance(e, RateLimitedError)
    assert e.kind == "order_cap"
    assert e.retryable is False
    assert e.retry_after_ms == SECONDS_TO_MIDNIGHT * 1000
    assert e.details == {"retry_after": SECONDS_TO_MIDNIGHT}
    assert should_retry(e, True) is False


def test_create_order_raises_once_without_sleeping_when_the_refusal_budget_is_used():
    sleeps: list[float] = []
    client, calls = make_client([BUDGET_USED], sleeps=sleeps)
    with pytest.raises(RateLimitedError) as exc:
        client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert exc.value.kind == "order_cap"
    assert len(calls) == 1
    assert sleeps == []


async def test_async_create_order_raises_once_without_sleeping_when_the_refusal_budget_is_used():
    transport, calls = _mock_transport([BUDGET_USED])
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with AsyncMyStarsClient(
        API_KEY, transport=transport, retry=RetryPolicy(max_retries=2, base_delay=0.0, jitter=False), sleep=sleep, rand=lambda: 0.0
    ) as client:
        with pytest.raises(RateLimitedError):
            await client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert len(calls) == 1
    assert sleeps == []


def test_refusal_budget_held_only_by_in_flight_checks_is_general_and_retried_after_its_short_retry_after():
    e = error_from_response(429, BUDGET_IN_FLIGHT["json"], BUDGET_IN_FLIGHT["headers"])
    assert isinstance(e, RateLimitedError)
    assert e.kind == "general"
    assert e.retryable is True
    sleeps: list[float] = []
    client, calls = make_client([BUDGET_IN_FLIGHT, CREATED], retry=RetryPolicy(base_delay=0.001, jitter=False), sleeps=sleeps)
    client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    assert len(calls) == 2
    assert sleeps == [3.0]


def test_quote_ceiling_429_is_general_and_retried_after_retry_after():
    e = error_from_response(429, QUOTE_CEILING["json"], QUOTE_CEILING["headers"])
    assert isinstance(e, RateLimitedError)
    assert e.kind == "general"
    assert e.retry_after_ms == 12_000
    sleeps: list[float] = []
    client, calls = make_client([QUOTE_CEILING, QUOTE], retry=RetryPolicy(base_delay=0.001, jitter=False), sleeps=sleeps)
    client.giveaways.quote(prize_type="stars", prize_quantity_per_winner=1000, winner_count=1)
    assert len(calls) == 2
    assert sleeps == [12.0]
