# mystars-faas

[![PyPI](https://img.shields.io/pypi/v/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![Python](https://img.shields.io/pypi/pyversions/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![license](https://img.shields.io/pypi/l/mystars-faas.svg)](LICENSE)

Official Python SDK for the **MyStars FaaS** API — buy Telegram **Stars** & **Premium** for any
`@username`, paid in **GRAM (ex TON)** or **USDT (TON)**.

Sync + async clients, exact-`Decimal` money, typed errors, automatic retries + idempotency, webhook
verification, a retail-markup calculator, and dependency-free on-chain payload builders.

> Compatible with FaaS API **v2.0.0**. Requires Python ≥ 3.9. Only runtime dependency: `httpx`.

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
    raise SystemExit(check.telegram_message)
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

`order.payment` (a `PaymentInstruction`) is on the `create_order` result. From contract v1.15.0 an
`Order` from `get_order` / `iter_orders` / `wait_for_order` carries it too, but only while the order
is `awaiting_payment` — it is `None` otherwise, since a closed order offers no pay-to details — and
always carries `payment_currency`. Pay `payment.amount` in `payment.currency`: `Order.amount_ton` is
the order's GRAM price, which equals the amount due only for a `ton` order.

```python
from mystars_faas import build_payment_request

req = build_payment_request(order.payment)   # a create_order(...) result, or an awaiting_payment Order
if req.ton_deeplink:           # a `ton` (GRAM) order: deeplink, QR payload, one TON Connect message
    print(req.ton_deeplink)
    print(req.ton_connect[0])
else:                          # a `usdt_ton` order: pass sender_address + jetton_wallet_address
    print(req.note)            # to get a signable TON Connect message; req.ton_connect is empty
```

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
| `RecipientIneligibleError` | 422 | — |
| `RateLimitedError` | 429 | — |
| `InternalServerError` / `ServiceUnavailableError` | 500 / 503 | — |
| `MyStarsTransportError` / `TimeoutError_` | — (no response) | — |

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
