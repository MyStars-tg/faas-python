"""Campaigns, gifts, giveaways and series (contract 2.1.0) — request shapes, keys, validation."""

from __future__ import annotations

import json
from itertools import count
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from conftest import API_KEY, _mock_transport

from mystars_faas import (
    AsyncMyStarsClient,
    ConflictError,
    FeatureUnavailableError,
    IdempotencyInFlightError,
    MyStarsClient,
    MyStarsValidationError,
    ServiceUnavailableError,
    UnprocessableError,
)
from mystars_faas._transport import RetryPolicy

CID = "c0ffee00-1111-4222-8333-444455556666"
GID = "5b1f7c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
CH = "0e8a9b7c-6d5e-4f30-a2b1-c4d5e6f7a8b9"
SID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
BASE = "https://api.mystars.tg/v1"
CAMPAIGN = {"campaign_id": CID, "status": "draft", "product": "stars", "payment": None}
BATCH = {"submitted": 2, "accepted": 2, "rejected": 0}
TEMPLATE = {"channel_id": CH, "prize_type": "stars", "prize_quantity_per_winner": 500, "winner_count": 3, "duration_sec": 86400}


def client_for(script, *, retries: int = 0) -> tuple[MyStarsClient, list[httpx.Request]]:
    transport, calls = _mock_transport(script)
    n = count(1)
    client = MyStarsClient(
        API_KEY,
        transport=transport,
        retry=RetryPolicy(max_retries=retries, base_delay=0.0, jitter=False),
        sleep=lambda _s: None,
        rand=lambda: 0.0,
        idempotency_key_factory=lambda: f"generated-{next(n)}",
    )
    return client, calls


def body(req: httpx.Request) -> dict:
    return json.loads(req.content)


def query(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(str(req.url)).query).items()}


# ─── campaigns ────────────────────────────────────────────────────────────────


def test_campaign_create_sends_body_and_key_and_flags_a_replay():
    client, calls = client_for([{"status": 201, "json": {**CAMPAIGN, "batch": BATCH}}, {"status": 200, "json": {**CAMPAIGN, "batch": BATCH}}])
    first = client.campaigns.create(product="stars", quantity=100, payment_currency="ton", recipients=["durov", "@x_user"], idempotency_key="c-1")
    again = client.campaigns.create(product="stars", quantity=100, payment_currency="ton", recipients=["durov", "@x_user"], idempotency_key="c-1")
    assert str(calls[0].url) == f"{BASE}/campaigns"
    assert calls[0].headers["idempotency-key"] == "c-1"
    assert body(calls[0]) == {"product": "stars", "quantity": 100, "payment_currency": "ton", "recipients": ["durov", "@x_user"]}
    assert first["replayed"] is False and again["replayed"] is True
    assert first["batch"] == BATCH


def test_campaign_create_reuses_one_generated_key_across_retries():
    client, calls = client_for(
        [{"status": 503, "json": {"error": {"code": "unavailable", "message": "x"}}}, {"status": 201, "json": {**CAMPAIGN, "batch": BATCH}}],
        retries=2,
    )
    client.campaigns.create(product="stars", quantity=100, payment_currency="ton", recipients=["durov"])
    assert [c.headers["idempotency-key"] for c in calls] == ["generated-1", "generated-1"]


def test_star_gift_campaign_body():
    client, calls = client_for([{"status": 201, "json": {**CAMPAIGN, "batch": BATCH}}])
    client.campaigns.create(product="star_gift", gift_id="5170145012310081615", comment="hi", hide_name=True, payment_currency="usdt_ton", recipients=["durov"], idempotency_key="g")
    assert body(calls[0]) == {
        "product": "star_gift", "gift_id": "5170145012310081615", "comment": "hi", "hide_name": True,
        "payment_currency": "usdt_ton", "recipients": ["durov"],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"product": "stars", "quantity": 10, "payment_currency": "ton", "recipients": ["a"]},
        {"product": "premium", "months": 4, "payment_currency": "ton", "recipients": ["a"]},
        {"product": "star_gift", "gift_id": "12ab", "payment_currency": "ton", "recipients": ["a"]},
        {"product": "stars", "quantity": 100, "payment_currency": "ton", "recipients": []},
        {"product": "stars", "quantity": 100, "payment_currency": "ton", "recipients": ["a"] * 5001},
        {"product": "stars", "quantity": 100, "payment_currency": "btc", "recipients": ["a"]},
        {"product": "nft", "payment_currency": "ton", "recipients": ["a"]},
    ],
)
def test_campaign_create_validates_before_any_request(kwargs):
    client, calls = client_for([])
    with pytest.raises(MyStarsValidationError):
        client.campaigns.create(**kwargs, idempotency_key="x")
    assert calls == []


def test_campaign_422_is_unprocessable_with_details():
    client, _ = client_for([{"status": 422, "json": {"error": {"code": "product_not_available", "message": "not yet"}}}])
    with pytest.raises(UnprocessableError) as exc:
        client.campaigns.create(product="star_gift", gift_id="1", payment_currency="ton", recipients=["a"], idempotency_key="k")
    assert exc.value.code == "product_not_available"


@pytest.mark.parametrize("action", ["validate", "confirm", "cancel", "pause", "resume"])
def test_campaign_actions(action):
    client, calls = client_for([{"json": CAMPAIGN}])
    getattr(client.campaigns, action)(CID)
    assert calls[0].method == "POST" and str(calls[0].url) == f"{BASE}/campaigns/{CID}/{action}"


def test_confirm_is_retried_but_resume_is_not():
    transient = {"status": 503, "json": {"error": {"code": "unavailable", "message": "x"}}}
    a, a_calls = client_for([transient, {"json": {"campaign_id": CID}}], retries=2)
    a.campaigns.confirm(CID)
    assert len(a_calls) == 2
    b, b_calls = client_for([transient, {"json": CAMPAIGN}], retries=2)
    with pytest.raises(ServiceUnavailableError):
        b.campaigns.resume(CID)
    assert len(b_calls) == 1


def test_campaign_conflict_is_not_order_specific():
    client, _ = client_for([{"status": 409, "json": {"error": {"code": "conflict", "message": "campaign is completed, cannot cancel"}}}])
    with pytest.raises(ConflictError) as exc:
        client.campaigns.cancel(CID)
    assert type(exc.value) is ConflictError


def test_campaign_reads_and_pagination():
    client, calls = client_for([
        {"json": {"campaigns": [CAMPAIGN], "next_cursor": "c2"}},
        {"json": {"campaigns": [{**CAMPAIGN, "campaign_id": "x"}], "next_cursor": None}},
        {"json": {"campaign_id": CID, "recipients": [{"position": 1}], "next_cursor": None}},
        {"json": {"campaign_id": CID}},
        {"json": {"type": "stars", "eta_seconds": 60}},
        {"json": {**CAMPAIGN, "recipients": {"total": 1}}},
    ])
    assert [c["campaign_id"] for c in client.campaigns.iter_all(status="draft", page_size=1)] == [CID, "x"]
    assert query(calls[1]) == {"status": "draft", "limit": "1", "cursor": "c2"}
    assert list(client.campaigns.iter_recipients(CID, verdict="rejected", reason="not_found")) == [{"position": 1}]
    assert query(calls[2]) == {"verdict": "rejected", "reason": "not_found"}
    client.campaigns.stats(CID)
    assert str(calls[3].url) == f"{BASE}/campaigns/{CID}/stats"
    assert client.campaigns.capacity(type="stars", recipients=500)["eta_seconds"] == 60
    assert query(calls[4]) == {"type": "stars", "recipients": "500"}
    assert client.campaigns.get(CID)["recipients"] == {"total": 1}


def test_add_recipients():
    client, calls = client_for([{"status": 201, "json": {"campaign_id": CID, "batch": BATCH}}])
    out = client.campaigns.add_recipients(CID, ["a", "b"], idempotency_key="chunk-2")
    assert out == {"campaign_id": CID, "batch": BATCH, "replayed": False}
    assert calls[0].headers["idempotency-key"] == "chunk-2" and body(calls[0]) == {"recipients": ["a", "b"]}


def test_gifts_list():
    catalog = {"currency": "usdt_ton", "comment_max_length": 128, "catalog_refreshed_at": None, "gifts": []}
    client, calls = client_for([{"json": catalog}])
    assert client.gifts.list(currency="usdt_ton") == catalog
    assert query(calls[0]) == {"currency": "usdt_ton"}


def test_gifts_list_requires_a_currency_before_any_request():
    client, calls = client_for([])
    with pytest.raises(TypeError, match="currency"):
        client.gifts.list()  # type: ignore[call-arg]
    with pytest.raises(MyStarsValidationError, match="currency"):
        client.gifts.list(currency=None)  # type: ignore[arg-type]
    with pytest.raises(MyStarsValidationError):
        client.gifts.list(currency="btc")
    assert calls == []


@pytest.mark.asyncio
async def test_async_gifts_list_requires_a_currency_before_any_request():
    transport, calls = _mock_transport([])
    async with AsyncMyStarsClient(API_KEY, transport=transport) as client:
        with pytest.raises(TypeError, match="currency"):
            await client.gifts.list()  # type: ignore[call-arg]
        with pytest.raises(MyStarsValidationError, match="currency"):
            await client.gifts.list(currency=None)  # type: ignore[arg-type]
    assert calls == []


# ─── giveaways ────────────────────────────────────────────────────────────────


def test_channels():
    client, calls = client_for([
        {"json": {"channels": [], "bot_username": "bot", "max_winners": 100}},
        {"json": {"channel": {"id": CH}, "checks": {}}},
        {"json": {"channel": {"id": CH}, "checks": {}}},
        {"status": 204},
    ])
    assert client.giveaways.channels.list()["bot_username"] == "bot"
    client.giveaways.channels.register("@my_channel")
    client.giveaways.channels.check(CH, idempotency_key="chk")
    client.giveaways.channels.remove(CH)
    assert body(calls[1]) == {"chat": "@my_channel"} and calls[1].headers["idempotency-key"] == "generated-1"
    assert str(calls[2].url) == f"{BASE}/giveaways/channels/{CH}/check" and calls[2].headers["idempotency-key"] == "chk"
    assert calls[3].method == "DELETE" and str(calls[3].url) == f"{BASE}/giveaways/channels/{CH}"


def test_giveaway_create_and_replay_header():
    client, calls = client_for([
        {"status": 201, "json": {"id": GID}},
        {"status": 201, "json": {"id": GID}, "headers": {"idempotent-replayed": "true"}},
    ])
    assert client.giveaways.create(**TEMPLATE, idempotency_key="gw-1")["replayed"] is False
    assert client.giveaways.create(**TEMPLATE, idempotency_key="gw-1")["replayed"] is True
    assert body(calls[0]) == TEMPLATE and str(calls[0].url) == f"{BASE}/giveaways"


@pytest.mark.parametrize(
    ("override", "key"),
    [({}, "series:1:2"), ({"duration_sec": 59}, "k"), ({"winner_count": 0}, "k"), ({"prize_type": "nft"}, "k")],
)
def test_giveaway_create_validates_before_any_request(override, key):
    client, calls = client_for([])
    with pytest.raises(MyStarsValidationError):
        client.giveaways.create(**{**TEMPLATE, **override}, idempotency_key=key)
    assert calls == []


def test_in_flight_key_is_retried_with_the_same_key():
    client, calls = client_for(
        [
            {"status": 409, "json": {"error": {"code": "idempotency_in_flight", "message": "still running"}}, "headers": {"retry-after": "1"}},
            {"status": 201, "json": {"id": GID}},
        ],
        retries=2,
    )
    client.giveaways.create(**TEMPLATE, idempotency_key="gw-2")
    assert [c.headers["idempotency-key"] for c in calls] == ["gw-2", "gw-2"]


def test_in_flight_without_retries_is_typed():
    client, _ = client_for([{"status": 409, "json": {"error": {"code": "idempotency_in_flight", "message": "x"}}, "headers": {"retry-after": "1"}}])
    with pytest.raises(IdempotencyInFlightError) as exc:
        client.giveaways.create(**TEMPLATE, idempotency_key="gw-3")
    assert exc.value.retry_after_ms == 1000 and exc.value.retryable


def test_fund_mints_a_new_key_each_call_and_returns_the_deposit_block():
    funding = {"giveaway_id": GID, "status": "awaiting_funding", "payment": {"memo": None, "address_kind": "one_time_deposit"}}
    client, calls = client_for([{"status": 201, "json": funding}, {"json": funding}])
    out = client.giveaways.fund(GID, currency="ton")
    client.giveaways.fund(GID)
    assert out["payment"]["memo"] is None
    assert body(calls[0]) == {"currency": "ton"}
    assert calls[0].headers["idempotency-key"] != calls[1].headers["idempotency-key"]


def test_lifecycle_reads_and_writes():
    client, calls = client_for([
        {"json": {"giveaway_id": GID, "status": "cancelled"}},
        {"json": {"giveaway_id": GID, "status": "closed", "closed_at": "2026-10-28T03:27:24.499Z"}},
        {"json": {"giveaway_id": GID, "status": "active", "checks": {}, "posts": []}},
        {"json": {"giveaway_id": GID, "status": "inactive"}},
        {"json": {"id": GID}},
        {"json": {"giveaways": [{"id": GID}], "next_cursor": None}},
        {"json": {"giveaway_id": GID, "entrants": [{"seq": "1"}], "next_cursor": None}},
        {"json": {"giveaway_id": GID, "winners": []}},
        {"json": {"giveaway_id": GID, "funnel": {}}},
        {"json": {"prize_type": "stars", "amount": "1"}},
    ])
    client.giveaways.cancel(GID, idempotency_key="c")
    # The close answers when it closed: the same value GET detail serves.
    assert client.giveaways.close(GID)["closed_at"] == "2026-10-28T03:27:24.499Z"
    client.giveaways.enable_autopost(GID, channel_id=CH)
    assert client.giveaways.disable_autopost(GID)["status"] == "inactive"
    client.giveaways.get(GID)
    assert list(client.giveaways.iter_all(status="open", series_id=SID)) == [{"id": GID}]
    assert list(client.giveaways.iter_entrants(GID, status="filtered")) == [{"seq": "1"}]
    client.giveaways.results(GID)
    client.giveaways.stats(GID)
    client.giveaways.quote(prize_type="stars", prize_quantity_per_winner=500, winner_count=3)
    assert [(c.method, urlparse(str(c.url)).path) for c in calls] == [
        ("POST", f"/v1/giveaways/{GID}/cancel"),
        ("POST", f"/v1/giveaways/{GID}/close"),
        ("POST", f"/v1/giveaways/{GID}/autopost"),
        ("DELETE", f"/v1/giveaways/{GID}/autopost"),
        ("GET", f"/v1/giveaways/{GID}"),
        ("GET", "/v1/giveaways"),
        ("GET", f"/v1/giveaways/{GID}/entrants"),
        ("GET", f"/v1/giveaways/{GID}/results"),
        ("GET", f"/v1/giveaways/{GID}/stats"),
        ("GET", "/v1/giveaways/quote"),
    ]
    assert calls[0].headers["idempotency-key"] == "c"
    assert body(calls[2]) == {"channel_id": CH}
    assert query(calls[5]) == {"status": "open", "series_id": SID}


def test_feature_unavailable_is_not_retried():
    client, calls = client_for([{"status": 503, "json": {"error": {"code": "prize_type_unavailable", "message": "no"}}}], retries=3)
    with pytest.raises(FeatureUnavailableError):
        client.giveaways.quote(prize_type="gift", prize_quantity_per_winner=1, winner_count=1, gift_id="1")
    assert len(calls) == 1


def test_refusal_keeps_its_code_and_details():
    client, _ = client_for([{"status": 409, "json": {"error": {"code": "not_cancellable", "message": "no", "status": "drawn"}}}])
    with pytest.raises(ConflictError) as exc:
        client.giveaways.cancel(GID)
    assert exc.value.code == "not_cancellable" and exc.value.details == {"status": "drawn"}


def test_attest_and_attestations():
    client, calls = client_for([
        {"json": {"giveaway_id": GID, "condition_key": "made_deposit", "satisfied": True, "received": 2, "changed": 2}},
        {"json": {"giveaway_id": GID, "attestations": [{"telegram_user_id": "1"}], "next_cursor": None}},
    ])
    assert client.giveaways.attest(GID, condition_key="made_deposit", telegram_user_ids=[123456789, "987654321"], satisfied=True)["changed"] == 2
    assert body(calls[0]) == {"condition_key": "made_deposit", "telegram_user_ids": [123456789, "987654321"], "satisfied": True}
    assert list(client.giveaways.iter_attestations(GID, condition_key="made_deposit", satisfied=True)) == [{"telegram_user_id": "1"}]
    assert query(calls[1]) == {"condition_key": "made_deposit", "satisfied": "true"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"condition_key": "made_deposit", "telegram_user_ids": [], "satisfied": True},
        {"condition_key": "made_deposit", "telegram_user_ids": [1] * 1001, "satisfied": True},
        {"condition_key": "Made-Deposit", "telegram_user_ids": [1], "satisfied": True},
        {"condition_key": "made_deposit", "telegram_user_ids": [2**60], "satisfied": True},
        {"condition_key": "made_deposit", "telegram_user_ids": ["12a"], "satisfied": True},
        {"condition_key": "made_deposit", "telegram_user_ids": [True], "satisfied": True},
    ],
)
def test_attest_validates_before_any_request(kwargs):
    client, calls = client_for([])
    with pytest.raises(MyStarsValidationError):
        client.giveaways.attest(GID, **kwargs)
    assert calls == []


def test_series():
    client, calls = client_for([
        {"status": 201, "json": {"id": SID, "status": "active"}},
        {"json": {"series": [{"id": SID}], "next_cursor": None}},
        {"json": {"id": SID}},
        {"json": {"id": SID, "status": "paused"}},
        {"json": {"id": SID, "status": "active"}},
        {"json": {"id": SID, "status": "cancelled", "existing_occurrences": "unaffected"}},
    ])
    created = client.giveaways.series.create(template=TEMPLATE, interval="week", starts_at="2026-10-05T12:00:00Z", count=12, idempotency_key="weekly")
    assert created["replayed"] is False
    assert body(calls[0]) == {"template": TEMPLATE, "interval": "week", "starts_at": "2026-10-05T12:00:00Z", "count": 12}
    assert list(client.giveaways.series.iter_all(status="active")) == [{"id": SID}]
    client.giveaways.series.get(SID)
    client.giveaways.series.pause(SID)
    client.giveaways.series.resume(SID)
    client.giveaways.series.cancel(SID)
    assert [urlparse(str(c.url)).path for c in calls[3:]] == [f"/v1/giveaways/series/{SID}/{a}" for a in ("pause", "resume", "cancel")]
    assert all("idempotency-key" in c.headers for c in calls[3:])


def test_series_needs_exactly_one_of_count_and_until():
    client, calls = client_for([])
    with pytest.raises(MyStarsValidationError):
        client.giveaways.series.create(template=TEMPLATE, interval="day", starts_at="2026-10-05T12:00:00Z", count=2, until="2026-11-01T00:00:00Z")
    with pytest.raises(MyStarsValidationError):
        client.giveaways.series.create(template=TEMPLATE, interval="day", starts_at="2026-10-05T12:00:00Z")
    assert calls == []


# ─── async parity ─────────────────────────────────────────────────────────────


async def _noop_sleep(_s: float) -> None:
    return None


@pytest.mark.asyncio
async def test_async_partner_resources():
    transport, calls = _mock_transport([
        {"status": 201, "json": {**CAMPAIGN, "batch": BATCH}},
        {"json": {"campaigns": [CAMPAIGN], "next_cursor": None}},
        {"status": 201, "json": {"giveaway_id": GID, "status": "awaiting_funding", "payment": {}}},
        {"status": 204},
        {"json": {"series": [{"id": SID}], "next_cursor": None}},
    ])
    n = count(1)
    async with AsyncMyStarsClient(
        API_KEY, transport=transport, retry=RetryPolicy(max_retries=0), sleep=_noop_sleep, rand=lambda: 0.0,
        idempotency_key_factory=lambda: f"generated-{next(n)}",
    ) as client:
        created = await client.campaigns.create(product="stars", quantity=100, payment_currency="ton", recipients=["durov"])
        assert created["replayed"] is False
        assert [c["campaign_id"] async for c in client.campaigns.iter_all()] == [CID]
        await client.giveaways.fund(GID)
        await client.giveaways.channels.remove(CH)
        assert [s["id"] async for s in client.giveaways.series.iter_all()] == [SID]
    assert calls[0].headers["idempotency-key"] == "generated-1"
    assert calls[2].headers["idempotency-key"] == "generated-2"
    assert calls[3].method == "DELETE"
