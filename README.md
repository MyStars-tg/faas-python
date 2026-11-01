# mystars-faas

[![PyPI](https://img.shields.io/pypi/v/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![Python](https://img.shields.io/pypi/pyversions/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![license](https://img.shields.io/pypi/l/mystars-faas.svg)](LICENSE)

Official Python SDK for the **MyStars FaaS** API — buy Telegram **Stars** & **Premium** for any
`@username`, paid in **GRAM (ex TON)** or **USDT (TON)**.

Sync + async clients, exact-`Decimal` money, typed errors, automatic retries + idempotency, webhook
verification, a retail-markup calculator, and dependency-free on-chain payload builders.

> Compatible with FaaS API **v2.3.0**. Requires Python ≥ 3.9. Only runtime dependency: `httpx`.

📖 HTTP API reference — the REST endpoints this package wraps: **[mystars.tg/docs](https://mystars.tg/docs)**
(interactive OpenAPI portal). Install + quickstart for every language:
[mystars.tg/docs/sdks](https://mystars.tg/docs/sdks). Every public function is documented below.
Changelog: [CHANGELOG.md](CHANGELOG.md).

🌐 What the API does and how to get started: **[Telegram Stars API for developers](https://mystars.tg/developers)**. Our consumer store: [MyStars.tg — buy Telegram Stars & Premium with crypto](https://mystars.tg).

## Install

```bash
pip install mystars-faas
```

Keys are issued in the MyStars Telegram bot — open [@my_stars_tg_bot](https://t.me/my_stars_tg_bot),
tap **API access**, copy your `X-Api-Key`.

Runnable examples live in [`examples/`](examples/) (quickstart + webhook receiver).

## Quick start

> The client reads your key from the **environment**. Set it before running —
> `export MYSTARS_API_KEY=faas_...`. If you keep keys in a `.env` file, load it yourself
> (e.g. with [`python-dotenv`](https://pypi.org/project/python-dotenv/) — `load_dotenv()`);
> it is **not** a dependency of this SDK, so `os.environ["MYSTARS_API_KEY"]` alone won't read a
> `.env`.

> **`payment_currency` is required.** `ton` is the native **GRAM** coin — not USDT; `usdt_ton` is
> USDT (TON). There is no default: a call without it raises `TypeError`, and the SDK rejects any
> other value before a request is sent.

```python
import os
from mystars_faas import MyStarsClient

client = MyStarsClient.production(os.environ["MYSTARS_API_KEY"])

quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
print("pay", quote.amount, quote.currency)

check = client.check_recipient("durov", type="stars")
if not check.eligible:
    raise SystemExit(check.telegram_message or check.reason)
# check.indeterminate is True when the check couldn't decide and failed open, so
# `eligible` is a default, not a measurement. Treat it as "unknown", never as "yes":
# ordering is still safe (the order re-checks authoritatively), but don't tell the
# buyer the recipient is confirmed.

order = client.create_order(            # an Idempotency-Key is generated + reused on retry
    type="stars", recipient="durov", quantity=100, payment_currency="ton",
    callback_url="https://your-app.example.com/webhooks/mystars",
)
# Pay order.payment.amount to order.payment.pay_to_address with the comment order.payment.memo.
print(order.payment)

final = client.wait_for_order(order.order_id, on_update=lambda o: print("status:", o.status))
print("done:", final.status, final.purchase_tx)
```

### Async

```python
from mystars_faas import AsyncMyStarsClient

async with AsyncMyStarsClient.production(key) as client:
    quote = await client.get_pricing(type="premium", months=3, payment_currency="usdt_ton")
    async for order in client.aiter_orders(status="delivered"):
        ...
```

## Webhooks

```python
from mystars_faas import WebhookVerifier

verifier = WebhookVerifier(WEBHOOK_SECRET)
event = verifier.verify(raw_body, request.headers["X-Faas-Signature"])  # raises on bad signature
# event.order_id, event.status — dedup on order_id (delivery is at-least-once)
```

Handles the 24h `"current,previous"` rotation header automatically. FastAPI / Flask route factories
live in `mystars_faas.integrations.fastapi` / `.flask` (install `mystars-faas[fastapi]` / `[flask]`).
`verify()` is unchanged in 2.1.0: it checks `X-Faas-Signature` and requires `order_id`.

### Signature V2 and tenant events (API 2.1.0)

Every webhook also carries `X-Faas-Signature-V2: t=<unix>,v1=<hex>` — the HMAC of `"<t>.<raw body>"`,
so a captured request cannot be replayed later — plus `X-Faas-Event-Id` and `X-Faas-Event-Type`.
Campaign, giveaway and series events go to your **tenant webhook endpoint** (configured by MyStars on
request) as an envelope `{id, type, created_at, api_version, sequence?, data}` — no `order_id`.

```python
from mystars_faas import TenantEvent, WebhookVerifier

verifier = WebhookVerifier(WEBHOOK_SECRET, previous_secret=None)   # 5-minute tolerance by default
event = verifier.verify_tenant_event(raw_body, request.headers["X-Faas-Signature-V2"])
if event.type == "campaign.paid":
    print(event.data["campaign_id"], event.data["max_deliverable"])
# dedupe on event.id; newer event types pass through unchanged

# One endpoint for both kinds: an order (WebhookEvent) or a tenant event (TenantEvent)
any_event = verifier.verify_event(raw_body, request.headers)
```

`verify_event` verifies V2 when present (a valid legacy header never rescues a bad V2) and accepts
an order on `X-Faas-Signature` only when V2 is absent (`require_signature_v2=True` refuses that). A
tenant event always needs V2. `faas_tenant_webhook_route` (FastAPI) and `faas_tenant_webhook_view`
(Flask) wrap `verify_tenant_event`.

## Campaigns, gifts and giveaways (API 2.1.0)

Enabled per tenant on request — ask [support](https://t.me/Mystars_support_bot); until then the calls
raise `PermissionDeniedError` (403). Responses are the server's JSON as `TypedDict`s (plain dicts;
money stays a decimal string). Every list has a `list(...)` page and an `iter_...(...)` generator.

```python
from mystars_faas import PaymentInstruction, build_funding_payment_request, build_payment_request

# Campaign: create → confirm → pay ONE transfer (memo = campaign id) → follow
campaign = client.campaigns.create(
    product="stars", quantity=100, payment_currency="ton", recipients=["durov", "example_user"],
    idempotency_key=f"campaign-{my_campaign_id}",
)
for r in client.campaigns.iter_recipients(campaign["campaign_id"], verdict="rejected"):
    print(r["username"], r["validation_reason"])          # who will NOT be delivered, and why
confirmation = client.campaigns.confirm(campaign["campaign_id"])
req = build_payment_request(PaymentInstruction.from_dict(confirmation["payment"]))

# Giveaway: create on a registered chat → fund (one-time deposit address, memo None) → results
giveaway = client.giveaways.create(
    channel_id=channel_id, prize_type="stars", prize_quantity_per_winner=500, winner_count=3,
    duration_sec=86400, idempotency_key=f"giveaway-{my_promo_id}",
)
funding = client.giveaways.fund(giveaway["id"], currency="ton")
funding_req = build_funding_payment_request(funding["payment"])  # no comment; refuses an expired instruction
client.giveaways.attest(giveaway["id"], condition_key="made_deposit", telegram_user_ids=[123456789], satisfied=True)
```

Also: `client.campaigns.add_recipients / validate / cancel / pause / resume / get / stats / capacity`,
`client.gifts.list(currency=…)`, `client.giveaways.channels.list / register / check / remove`,
`client.giveaways.quote / get / cancel / close / enable_autopost / disable_autopost / entrants /
results / stats / attestations`, and `client.giveaways.series.create / list / get / pause / resume /
cancel` — the same on `AsyncMyStarsClient` (awaitable; `iter_...` are async generators). Every
giveaway `POST` sends an `Idempotency-Key` (yours, or one minted per call and reused across its
retries). New errors: `UnprocessableError` (422), `FeatureUnavailableError` (503 for an option not
enabled yet — never retried), `IdempotencyInFlightError` (409, retried after `Retry-After` with the
same key; every keyed giveaway and series write can answer it while the first call with that key
still runs); every API error carries the envelope's extra fields in `err.details`. A giveaway
refusal keeps its own `code` on a `ConflictError`, for example
`funding_order_open_in_other_currency` (fund again in `err.details["currency"]`, under a new key)
or `attestation_limit_reached` (the batch would pass the condition's cap of
`err.details["limit"]` Telegram users; revoked users count toward it).

## Your own retail markup

```python
from mystars_faas import apply_retail_markup

quote = client.get_pricing(type="stars", quantity=100, payment_currency="usdt_ton")
retail = apply_retail_markup(quote, margin_pct=15, pass_through_processing_fee=True)
print(retail.total)   # decimal string — exact (computed in Decimal), two-stage cent-ceil
print(retail.profit)  # decimal string — your gross margin
```

All `RetailQuote` money fields (`total`, `profit`, `subtotal`, …) are returned as **decimal
strings**, not `Decimal`. For a `usdt_ton` quote, the markup needs the `fee` breakdown — if the
quote came back with `fee=None` (a cold-FX `/v1/pricing` row), `apply_retail_markup` raises
`MyStarsValidationError`; re-quote `get_pricing(...)` to obtain the `fee` block first.

## Pay an order (non-custodial)

`order.payment` (a `PaymentInstruction`) is on the `create_order` result: always on a fresh create
(201). A 200 idempotent replay of an order that is no longer `awaiting_payment` (paid, cancelled,
expired, failed, delivered…) carries `payment=None` and `expires_at=None`, because there is nothing
left to pay — read `status` before you pay. From contract v1.15.0 an
`Order` from `get_order` / `iter_orders` / `wait_for_order` carries it too, but only while the order
is `awaiting_payment` — it is `None` otherwise, since a closed order offers no pay-to details, and a
`usdt_ton` order's is `None` where USDT payments are not offered (quoting or ordering in `usdt_ton`
there raises `UnprocessableError` 422 `currency_not_available`) — and always carries
`payment_currency`. Pay `payment.amount` in `payment.currency`: `Order.amount_ton` is
the order's GRAM price, which equals the amount due only for a `ton` order.

```python
from mystars_faas import build_payment_request

if order.payment is not None:      # a create_order(...) result, or an awaiting_payment Order
    req = build_payment_request(order.payment)
    if req.ton_deeplink:           # a `ton` (GRAM) order: deeplink, QR payload, one TON Connect message
        print(req.ton_deeplink)
        print(req.ton_connect[0])
    else:                          # a `usdt_ton` order: pass sender_address + jetton_wallet_address
        print(req.note)            # to get a signable TON Connect message; req.ton_connect is empty
```

A giveaway funding block (`client.giveaways.fund`) pays its own one-time deposit address: `memo` is
`None` and `address_kind` is `"one_time_deposit"`. Use `build_funding_payment_request(funding["payment"])`
— it leaves the comment out and refuses an instruction past its `expires_at`.

The builders refuse to guess: an unknown `currency`, a payment block whose `amount_units` /
`asset` / `decimals` / `transfer` contradict its `currency`, or a zero or negative amount raises
`MyStarsValidationError` instead of producing a payable message.

Holds no keys. Errors are typed subclasses of `MyStarsAPIError` (`RecipientIneligibleError`,
`RateLimitedError`, …); the client retries transient failures (network, timeout, 502/503/504, 500,
general 429 — honoring `Retry-After`, including the HTTP-date form) automatically and
idempotency-safely. A response body larger than 4 MB is rejected (`response_too_large`) instead of
being buffered whole.

## Errors

| Class | HTTP | TS-SDK alias |
|-------|------|--------------|
| `MyStarsValidationError` | — (client-side) | — |
| `BadRequestError` | 400 | — |
| `AuthenticationError` | 401 | `UnauthorizedError` |
| `PermissionDeniedError` | 403 | `ForbiddenError` |
| `NotFoundError` | 404 | — |
| `ConflictError` / `IdempotencyConflictError` / `OrderNotCancellableError` | 409 | — |
| `IdempotencyInFlightError` | 409 (retried automatically) | — |
| `RecipientIneligibleError` | 422 | — |
| `UnprocessableError` | 422 | — |
| `RateLimitedError` | 429 (`kind` `"general"` retried; `"order_cap"`, a daily cap such as the ineligible-recipient refusal budget, never retried) | — |
| `InternalServerError` / `ServiceUnavailableError` | 500 / 503 | — |
| `FeatureUnavailableError` | 503 (never retried) | — |
| `MyStarsAPIError` | any other status (502, 504, …) | — |
| `MyStarsTransportError` / `TimeoutError_` | — (no response) | — |
| `WebhookVerificationError` | — (client-side) | — |
| `OrderWaitTimeout` | — (client-side) | — |

Every API error above subclasses `MyStarsAPIError`, and every class in the table subclasses
`MyStarsError`. A subclass is caught by its parent's `except`; nothing else is:

- `IdempotencyInFlightError` is a `ConflictError`: the first request with that `Idempotency-Key`
  is still running. The client retries it with the same key, after `Retry-After`; you see it only
  once the retries run out.
- `UnprocessableError` and `RecipientIneligibleError` are siblings, not parent and child: an
  `except RecipientIneligibleError` does not catch an `UnprocessableError`. An order's ineligible
  recipient raises `RecipientIneligibleError`; any other 422 (`currency_not_available`,
  `product_not_available`, `channel_checks_failed`, `schedule_out_of_bounds`) raises
  `UnprocessableError`.
- `FeatureUnavailableError` is a `ServiceUnavailableError` for an option not enabled for your
  account yet. It is not transient, so it is never retried: ask MyStars support to enable it.
- `WebhookVerificationError` comes from the webhook verifiers, and `OrderWaitTimeout` from
  `wait_for_order` (its `last_order` holds the last order it saw).

`UnauthorizedError` and `ForbiddenError` are exported aliases of `AuthenticationError` /
`PermissionDeniedError` so code written against the TypeScript SDK's names catches the same error.

## CLI

```bash
mystars-faas --api-key "$MYSTARS_API_KEY" pricing --type stars --quantity 100 --currency ton
mystars-faas orders-create --type stars --recipient durov --quantity 100 --currency ton --pay

# Verify a webhook offline. Prefer the env var — a --secret on argv is visible in `ps`.
export MYSTARS_WEBHOOK_SECRET="…"
mystars-faas webhook-verify --body "$RAW_BODY" --signature "$X_FAAS_SIGNATURE"
```

`webhook-verify` reads the secret from `MYSTARS_WEBHOOK_SECRET` (preferred) or `--secret`; the env
var wins when both are set, because a command-line `--secret` leaks via the process list and shell
history.
