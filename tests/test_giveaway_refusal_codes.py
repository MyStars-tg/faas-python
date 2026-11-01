"""Giveaway refusals added in contract 2.2.0, and ``idempotency_in_flight`` on every keyed giveaway write."""

from __future__ import annotations

from collections.abc import Callable
from itertools import count
from typing import Any

import httpx
import pytest
from conftest import API_KEY, _mock_transport

from mystars_faas import (
    AsyncMyStarsClient,
    ConflictError,
    IdempotencyConflictError,
    IdempotencyInFlightError,
    MyStarsClient,
)
from mystars_faas._transport import RetryPolicy, should_retry
from mystars_faas.errors import error_from_response

GID = "5b1f7c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
SID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
BASE = "https://api.mystars.tg/v1/giveaways"

OTHER_CURRENCY = {
    "error": {
        "code": "funding_order_open_in_other_currency",
        "message": "this giveaway's funding order is open in ton; fund it with currency ton",
        "currency": "ton",
    }
}
LIMIT_REACHED = {
    "error": {
        "code": "attestation_limit_reached",
        "message": "a partner condition holds at most 100000 attested Telegram users",
        "limit": 100000,
    }
}
IN_FLIGHT = {
    "status": 409,
    "json": {"error": {"code": "idempotency_in_flight", "message": "a request with this Idempotency-Key is still in progress"}},
    "headers": {"retry-after": "1"},
}
OK = {"json": {"giveaway_id": GID, "status": "cancelled"}}


def retrying_client(
    script: list[dict[str, Any]], sleeps: list[float] | None = None
) -> tuple[MyStarsClient, list[httpx.Request]]:
    """Retries ON, so a test proves a refusal is not retried rather than that retries are off."""
    transport, calls = _mock_transport(script)
    n = count(1)
    record = sleeps if sleeps is not None else []
    client = MyStarsClient(
        API_KEY,
        transport=transport,
        retry=RetryPolicy(max_retries=2, base_delay=0.0, jitter=False),
        sleep=record.append,
        rand=lambda: 0.0,
        idempotency_key_factory=lambda: f"generated-{next(n)}",
    )
    return client, calls


# ─── mapping ──────────────────────────────────────────────────────────────────


def test_funding_order_open_in_other_currency_is_a_conflict_with_the_currency():
    e = error_from_response(409, OTHER_CURRENCY, {})
    assert isinstance(e, ConflictError)
    assert not isinstance(e, (IdempotencyConflictError, IdempotencyInFlightError))
    assert e.code == "funding_order_open_in_other_currency"
    assert e.details == {"currency": "ton"}
    assert e.retryable is False
    assert should_retry(e, True) is False


def test_attestation_limit_reached_is_a_conflict_with_the_limit():
    e = error_from_response(409, LIMIT_REACHED, {})
    assert isinstance(e, ConflictError)
    assert not isinstance(e, (IdempotencyConflictError, IdempotencyInFlightError))
    assert e.code == "attestation_limit_reached"
    assert e.details == {"limit": 100000}
    assert should_retry(e, True) is False


# ─── through the client ───────────────────────────────────────────────────────


def test_fund_in_the_other_currency_raises_once_with_the_open_orders_currency():
    client, calls = retrying_client([{"status": 409, "json": OTHER_CURRENCY}])
    with pytest.raises(ConflictError) as exc:
        client.giveaways.fund(GID, currency="usdt_ton")
    assert exc.value.code == "funding_order_open_in_other_currency"
    assert exc.value.details == {"currency": "ton"}
    assert len(calls) == 1


def test_attest_past_the_cap_raises_once_with_the_limit():
    client, calls = retrying_client([{"status": 409, "json": LIMIT_REACHED}])
    with pytest.raises(ConflictError) as exc:
        client.giveaways.attest(GID, condition_key="made_deposit", telegram_user_ids=[123456789], satisfied=True)
    assert exc.value.code == "attestation_limit_reached"
    assert exc.value.details == {"limit": 100000}
    assert len(calls) == 1


CID = "3c2b1a0f-9e8d-4c7b-8a69-584736251403"

# Every keyed giveaway and series write the engine answers idempotently (API 2.2.0).
WRITES: list[tuple[str, Callable[[Any], Any], str]] = [
    ("channels.register", lambda g: g.channels.register("@mychannel"), f"{BASE}/channels"),
    ("channels.check", lambda g: g.channels.check(CID), f"{BASE}/channels/{CID}/check"),
    ("fund", lambda g: g.fund(GID, currency="ton"), f"{BASE}/{GID}/fund"),
    ("cancel", lambda g: g.cancel(GID), f"{BASE}/{GID}/cancel"),
    ("close", lambda g: g.close(GID), f"{BASE}/{GID}/close"),
    ("enable_autopost", lambda g: g.enable_autopost(GID), f"{BASE}/{GID}/autopost"),
    (
        "attest",
        lambda g: g.attest(GID, condition_key="made_deposit", telegram_user_ids=[1], satisfied=True),
        f"{BASE}/{GID}/attestations",
    ),
    ("series.pause", lambda g: g.series.pause(SID), f"{BASE}/series/{SID}/pause"),
    ("series.resume", lambda g: g.series.resume(SID), f"{BASE}/series/{SID}/resume"),
    ("series.cancel", lambda g: g.series.cancel(SID), f"{BASE}/series/{SID}/cancel"),
]


@pytest.mark.parametrize(("name", "call", "url"), WRITES, ids=[w[0] for w in WRITES])
def test_in_flight_on_a_giveaway_write_is_retried_after_retry_after_with_the_same_key(name, call, url):
    sleeps: list[float] = []
    client, calls = retrying_client([IN_FLIGHT, OK], sleeps)
    call(client.giveaways)
    assert [str(c.url) for c in calls] == [url, url]
    assert [c.headers["idempotency-key"] for c in calls] == ["generated-1", "generated-1"]
    # Retry-After: 1 is the floor of the one wait (the backoff alone is 0 here).
    assert sleeps == [1.0]


@pytest.mark.parametrize(("name", "call", "url"), WRITES, ids=[w[0] for w in WRITES])
async def test_async_in_flight_on_a_giveaway_write_is_retried_after_retry_after_with_the_same_key(name, call, url):
    transport, calls = _mock_transport([IN_FLIGHT, OK])
    n = count(1)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with AsyncMyStarsClient(
        API_KEY,
        transport=transport,
        retry=RetryPolicy(max_retries=2, base_delay=0.0, jitter=False),
        sleep=sleep,
        rand=lambda: 0.0,
        idempotency_key_factory=lambda: f"generated-{next(n)}",
    ) as client:
        await call(client.giveaways)
    assert [str(c.url) for c in calls] == [url, url]
    assert [c.headers["idempotency-key"] for c in calls] == ["generated-1", "generated-1"]
    assert sleeps == [1.0]


async def _noop_sleep(_s: float) -> None:
    return None


async def test_async_fund_in_the_other_currency_raises_once():
    transport, calls = _mock_transport([{"status": 409, "json": OTHER_CURRENCY}])
    async with AsyncMyStarsClient(
        API_KEY, transport=transport, retry=RetryPolicy(max_retries=2, base_delay=0.0, jitter=False),
        sleep=_noop_sleep, rand=lambda: 0.0,
    ) as client:
        with pytest.raises(ConflictError) as exc:
            await client.giveaways.fund(GID, currency="usdt_ton")
    assert exc.value.details == {"currency": "ton"}
    assert len(calls) == 1
