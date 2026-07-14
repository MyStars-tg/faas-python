# mystars-faas

[![PyPI](https://img.shields.io/pypi/v/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![Python](https://img.shields.io/pypi/pyversions/mystars-faas.svg)](https://pypi.org/project/mystars-faas/) [![license](https://img.shields.io/pypi/l/mystars-faas.svg)](LICENSE)

Official Python SDK for the **MyStars FaaS** API — buy Telegram **Stars** & **Premium** for any
`@username`, paid in **TON** or **USDT (TON)**.

Sync + async clients, exact-`Decimal` money, typed errors, automatic retries + idempotency, webhook
verification, a retail-markup calculator, and dependency-free on-chain payload builders.

> Compatible with FaaS API **v1.10.0**. Requires Python ≥ 3.9. Only runtime dependency: `httpx`.

📖 Full interactive API reference: **[mystars.tg/docs](https://mystars.tg/docs)**. SDK method/function
reference: [api-python.md](../../docs/sdk/api-python.md). Changelog: [CHANGELOG.md](CHANGELOG.md).

## Install

```bash
pip install mystars-faas
```

Keys are issued in the MyStars Telegram bot — open [@my_stars_tg_bot](https://telegram.me/my_stars_tg_bot),
tap **API access**, copy your `X-Api-Key`.

Runnable examples live in [`examples/`](examples/) (quickstart + webhook receiver).

## Quick start

> The client reads your key from the **environment**. Set it before running —
> `export MYSTARS_API_KEY=faas_...`. If you keep keys in a `.env` file, load it yourself
> (e.g. with [`python-dotenv`](https://pypi.org/project/python-dotenv/) — `load_dotenv()`);
> it is **not** a dependency of this SDK, so `os.environ["MYSTARS_API_KEY"]` alone won't read a
> `.env`.

```python
import os
from mystars_faas import MyStarsClient

client = MyStarsClient.production(os.environ["MYSTARS_API_KEY"])

quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
print("pay", quote.amount, quote.currency)

check = client.check_recipient("durov", type="stars")
if not check.eligible:
    raise SystemExit(check.telegram_message)

order = client.create_order(            # an Idempotency-Key is generated + reused on retry
    type="stars", recipient="durov", quantity=100,
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

`order.payment` (a `PaymentInstruction`) is on the **`create_order` result** (`CreateOrderResult`).
An `Order` from `get_order` / `wait_for_order` has no `.payment` — read `amount_ton`, `payment_tx`,
and `purchase_tx` there instead.

```python
from mystars_faas import build_payment_request

req = build_payment_request(order.payment)   # order = the create_order(...) result
print(req.ton_deeplink)        # ton://transfer/... (TON only)
print(req.ton_connect[0])      # ton_connect is a list[TonConnectMessage] (one entry for TON)
```

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
mystars-faas orders-create --type stars --recipient durov --quantity 100 --pay

# Verify a webhook offline. Prefer the env var — a --secret on argv is visible in `ps`.
export MYSTARS_WEBHOOK_SECRET="…"
mystars-faas webhook-verify --body "$RAW_BODY" --signature "$X_FAAS_SIGNATURE"
```

`webhook-verify` reads the secret from `MYSTARS_WEBHOOK_SECRET` (preferred) or `--secret`; the env
var wins when both are set, because a command-line `--secret` leaks via the process list and shell
history.
