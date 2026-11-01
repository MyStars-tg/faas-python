# Changelog

All notable changes to the MyStars FaaS Python SDK (`mystars-faas`) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The `CONTRACT_VERSION` each
release is built + verified against (the FaaS API `info.version`) is noted per entry; the live
contract version is published at [mystars.tg/docs](https://mystars.tg/docs).

## [0.6.0] - 2026-10-31

_Built against FaaS API contract **v2.3.0**._ Released together with the TypeScript SDK 0.6.0.

### Added

- `check_recipient` (sync and async) takes the order you intend to place: `quantity` (Stars) and
  `payment_currency`, both keyword-only and defaulting to `None`. Each is sent only when given and
  is validated client-side as in `create_order` (`MyStarsValidationError`, no request);
  `quantity` is sent for `type="stars"` only. The API then also asks Fragment about that exact
  order, so a refusal that depends on the order rather than on the recipient, for example "You can
  buy a minimum of 12,500 stars", comes back as `eligible=False` with Fragment's text in
  `telegram_message`. A Stars `payment_currency` without `quantity` checks the recipient only. A
  call without the new arguments sends the same body as before.
- `WebhookEvent.telegram_message` (`str | None`, default `None`). The `order.failed` and
  `order.reversed` webhooks now carry Fragment's verbatim text of the last refusal it gave for this
  order, present only on `failed` or `reversed` orders; `None` when Fragment never refused it.
  `order.delivered` and `order.expired` carry none.

### Changed

- `CONTRACT_VERSION` is `2.3.0`. `Order.telegram_message` holds the same text; its docstring says
  when it is set.
- **API change:** `POST /v1/orders` now also asks Fragment about the order itself before it creates
  it, so an order Fragment refuses only at that point (for example "You can buy a minimum of 12,500
  stars") answers `422 recipient_ineligible` with Fragment's text, raised as
  `RecipientIneligibleError`, and no order exists. This is a server change: it reaches every SDK
  version once the API runs 2.3.0.
- **API change:** `telegram_message` on `POST /v1/recipients/check` and on the
  `422 recipient_ineligible` error carries Fragment's verbatim text only for a refusal the API
  recognises; other texts come back as `None` on the check and as no `telegram_message` on the 422,
  where `RecipientIneligibleError.telegram_message` then falls back to the error `message`.
  `reason` is unchanged (`details["reason"]` on the 422): branch on `eligible` / `reason`, not on the
  text. The README and quickstart fall back to `check.reason`, and the `RecipientCheck`,
  `RecipientIneligibleError` and `check_recipient` docs say where the refusal class is.
- The cross-language contract fixtures carry `contract_version` `2.3.0`. The two tenant-envelope V2
  signing vectors stamp `api_version: "2.3.0"` and are re-signed.

## [0.5.0] - 2026-10-26

_Built against FaaS API contract **v2.2.0**._ Released together with the TypeScript SDK 0.5.0.
API 2.2.0 changes the order replay in a way 0.4.3 and earlier cannot parse, and answers a 429 that
0.4.3 and earlier wait hours on: see the upgrade notes under Changed.

### Changed

- `CONTRACT_VERSION` is `2.2.0`. The cross-language contract fixtures carry `contract_version`
  `2.2.0`. The two tenant-envelope V2 signing vectors stamp `api_version: "2.2.0"` and are re-signed.
- `giveaways.close()` (sync and async) is typed `GiveawayClosed`: the `GiveawayStatusChange` keys
  plus `closed_at`, the same value as `closed_at` in `GET /v1/giveaways/{id}`. Additive.
- The type comments say what an entrant's `score` and `score_reasons` contain, what
  `funding.tx_hash` holds, and that `seq` is the entry's ID: one sequence shared by every giveaway,
  neither a count nor a position in this one.

The **API change** bullets below are server changes in API 2.2.0: they reach every SDK version,
0.4.x included, once the API runs 2.2.0. 0.5.0 documents them, parses the order replay and stops
retrying the refusal-budget 429.

- **API change:** a 200 idempotent replay of `POST /v1/orders` no longer repeats the payment
  instructions of an order that has moved on. A replay used to send the original `payment` block and
  `expires_at` again whatever the order's status. From this release both are `null` once the order is
  no longer `awaiting_payment` (paid, cancelled, expired, failed, delivered…), so a replay never hands
  out pay-to details that nothing will apply. `create_order` (sync and async) parses such a replay
  with `CreateOrderResult.payment` and `CreateOrderResult.expires_at` set to `None`; they are typed
  `PaymentInstruction | None` and `str | None`. A type checker now flags an unguarded
  `order.payment` access: check it (or `order.status`) before you pay. `mystars-faas orders-create
  --pay` prints `"payment_request": null` for such a replay.

  **Upgrade note:** on 0.4.3 and earlier, `create_order` raises `AttributeError` on such a replay.
  That is not a `MyStarsError`, so `except MyStarsError` does not catch it. Upgrade to 0.5.0 before
  you re-send a create with a key whose order may have moved on.

- **API change:** `giveaways.fund` (sync and async) with a `currency` other than that of the
  giveaway's open funding order is refused with 409 `funding_order_open_in_other_currency`, a
  `ConflictError` whose `details["currency"]` names the open order's currency. Before, the call
  answered 200 with the open order's instruction in its own asset. Fund again with
  `details["currency"]`; the refused call kept no answer, so its idempotency key may be reused. A
  call with no `currency` asks for `ton`, so it now gets this 409
  while a `usdt_ton` order is open: pass `currency="usdt_ton"` to have that order served again.
  While USDT funding is switched off, a `usdt_ton` call still serves an open USDT order again; only
  a new USDT order is refused (422 `currency_not_available`).
- **API change:** `giveaways.attest` (sync and async) refuses a batch that would take a condition
  past its cap of Telegram users (every user it has asserted or revoked counts; a revocation does
  not free a place) with 409 `attestation_limit_reached`, a `ConflictError` whose
  `details["limit"]` is the cap. The whole batch is refused and nothing is written. Users the
  condition already holds do not count again, so they can still be revoked or asserted again at the
  cap, and also when the condition holds more than the cap. A batch whose locks wait more than about
  2 s is refused with 409 `busy`, a `ConflictError` that the default policy does not retry: nothing
  was written, so send it again with the same key.
- **API change:** a same-key retry of a giveaway or series write (channel register and check, fund,
  cancel, close, autopost, attestations, series pause, resume and cancel) that timed out at the API
  (its 503 after the write may already have run) now gets the first call's 2xx answer instead of
  running the write again. Only a 2xx is kept: after a refusal (4xx) or a 5xx a same-key retry runs
  the write again, so a corrected request may reuse the key. While the first call is still
  running the retry gets 409 `idempotency_in_flight` with `Retry-After`, which the default retry
  policy retries with the same key (`IdempotencyInFlightError`).
- **API change:** `create_order` answers 429 `rate_limited` once the tenant has collected the day's
  budget of 422 `recipient_ineligible` refusals (200 by default), with `Retry-After` and
  `details["retry_after"]` (seconds) running to 00:00 UTC; a replay of an existing key still
  answers 200. Check a recipient first with `check_recipient`, which does not count. The shared
  giveaway-quote ceiling's 429 now carries `Retry-After`, so the default policy waits it out before
  retrying.
- **API change:** `funding.tx_hash` in `GET /v1/giveaways/{id}` is the transaction hash as a TON
  explorer takes it (64 hex characters or the 44-character base64 form), no longer with a leading
  `0x` in front of a base64 hash. A recorded value that is not a hash is `null`.
- **API change:** `giveaway.delivery_updated` carries `purchase_tx` by the same rule as
  `winners[].delivery.purchase_tx` in the results, so a base64 Fragment hash is no longer `null` in
  the webhook. A state announced before its hash was known gets one more event for the same
  `delivery_id` and `status`, with `purchase_tx` set: handle a second `delivery_updated` for a
  delivery as an update, not a duplicate. A `null` `purchase_tx` never replaces one already
  received for the same `delivery_id`: the two events share `created_at` and can arrive in either
  order.
- **API change:** `giveaway.reversal_resolved` is sent once per reversal reaching a final status
  (`sent`, `skipped`, `cancelled`), whichever path got it there, the automatic refund sender
  included; approving a reversal alone sends nothing. `tx_hash` is set for `sent` when the payment's
  hash is known, the same value as `results.reversals[].tx_hash`, which is now `null` for a recorded
  value that is not a hash.
- A 429 whose body names `retry_after` (the refusal budget above) is a `RateLimitedError` of
  `kind == "order_cap"` with `retryable` `False`, and the default policy does not retry it;
  `retry_after_ms` says when it clears. The short 429 the API sends while the budget's last places
  are held by the tenant's own checks still running has a `Retry-After` of a few seconds and no body
  `retry_after`: it is `kind == "general"`, and the default policy retries it.

  **Upgrade note:** on 0.4.3 and earlier its `Retry-After` makes it `kind == "general"`, and the
  default policy sleeps for the whole `Retry-After` (up to the next 00:00 UTC) before each of its
  retries, so `create_order` blocks for hours. Upgrade to 0.5.0, or pass
  `RetryPolicy(respect_retry_after=False)`, before the API runs 2.2.0.

### Fixed

- A 429 without `Retry-After` is a `RateLimitedError` of `kind == "order_cap"` with `retryable`
  `False` even when it carries `RateLimit-*` headers. The daily order and intake caps, the
  per-recipient flood guard and the live-campaign cap answer after a per-minute bucket let the
  request through, so they carry that bucket's `RateLimit-*` headers; earlier versions read those
  as `kind == "general"` and the default policy retried a cap that cannot clear. `kind` now
  follows `Retry-After` alone.
- The quickstart example prints the order's status instead of failing when a re-run with the same
  key replays an order that has moved on.
- `verify_webhook_signature_v2` and `WebhookVerifier.is_valid_v2` return `False` for a
  `X-Faas-Signature-V2` whose `t=` has more than 4300 digits, and `verify_tenant_event` /
  `verify_event` raise `WebhookVerificationError` for it. Python 3.11+ refuses to convert such a
  string to `int`, so they raised `ValueError`, and the FastAPI and Flask integrations answered an
  unauthenticated request with 500 instead of 400.
- `parse_ton_address` (and the payment builders that call it) raises `MyStarsValidationError` for a
  raw address whose workchain has over 4300 digits or uses non-ASCII digits such as `²`, instead
  of `ValueError`; a workchain written in non-ASCII digits (`-١`) is no longer read as `-1`.

### Documentation

- The `giveaways.fund` docstrings (sync and async) no longer suggest that a new idempotency key gets
  a new instruction. While a funding order is open, every call in that order's currency serves it
  again with the same `expires_at` (another currency is refused, see Changed); an expired one cannot
  be paid or replaced (409 `funding_order_not_payable`, then 409 `not_fundable` once the giveaway is
  cancelled).
- The `ConflictError` and `IdempotencyInFlightError` docstrings and the README name the new giveaway
  409 codes and their `details`, and that every keyed giveaway and series write can answer
  `idempotency_in_flight`. The `giveaways.attest` docstrings (sync and async) name 409
  `attestation_limit_reached`, and the `giveaways.attestations` docstrings say a cancelled
  giveaway's attestations are deleted 7 days after the cancellation by default. The
  `RateLimitedError` docstring and the README Errors table say which 429s are `"order_cap"`.
- The README's Errors table lists every error class: `IdempotencyInFlightError` (409, retried
  automatically), `UnprocessableError` (422, a sibling of `RecipientIneligibleError`, not a
  subclass), `FeatureUnavailableError` (503, never retried), `MyStarsAPIError` for any other
  status, and the client-side `WebhookVerificationError` and `OrderWaitTimeout`.

## [0.4.3] - 2026-10-24

_Built against FaaS API contract **v2.1.4**._

### Added

- `WebhookEvent.reversal_tx` (`str | None`, default `None`). The `order.failed` and `order.reversed`
  webhooks now carry the reference of the reversal that returned the payment, or `None` while none
  has gone out (a reversal sent later fires no webhook: read it from the order). `order.delivered`
  and `order.expired` carry none.

### Changed

- `CONTRACT_VERSION` is `2.1.4`. A payment returned after its order expired or was cancelled now
  also shows in that order's `reversal_tx` when it was returned outside the automatic flow.
- The cross-language contract fixtures carry `contract_version` `2.1.4`. The two tenant-envelope V2
  signing vectors stamp `api_version: "2.1.4"` and are re-signed.

## [0.4.2] - 2026-10-24

_Built against FaaS API contract **v2.1.3**._ Documentation only: no SDK behaviour changed.

### Changed

- `CONTRACT_VERSION` is `2.1.3`. A payment that names an order you already cancelled is reversed to
  its sender as before, and the `cancelled` order now shows the reference of that reversal in
  `reversal_tx`, as an `expired` order already does for a late payment. The status stays
  `cancelled` and no webhook is sent for it.
- `reversal_tx` is only ever a transaction reference or `null`: an order or campaign whose reversal
  is still in flight, or was confirmed without a reference that can be shown, reads `null` there (in
  `campaign.*` webhooks too) instead of an internal placeholder. `Order.reversal_tx` and the campaign `reversal_tx` documentation say so.
- The cross-language contract fixtures carry `contract_version` `2.1.3`. The two tenant-envelope V2
  signing vectors stamp `api_version: "2.1.3"` and are re-signed.

## [0.4.1] - 2026-10-23

_Built against FaaS API contract **v2.1.2**._ Documentation only: no SDK behaviour changed.

### Changed

- `CONTRACT_VERSION` is `2.1.2`. A payment without a usable memo is returned to its sender and no
  longer changes an order: `failure_reason` `no_memo` / `wrong_memo` are no longer set, so the order
  it was meant for stays `awaiting_payment` and expires unless paid. Orders failed earlier may still
  carry those values. The `Order.failure_reason` documentation says so.
- The cross-language contract fixtures carry `contract_version` `2.1.2`. The two tenant-envelope V2
  signing vectors stamp `api_version: "2.1.2"` and are re-signed.

## [0.4.0] - 2026-10-23

_Built against FaaS API contract **v2.1.1**._

### Changed

- **Set change:** `TERMINAL_STATUSES` gains `"completed"`, so `is_terminal("completed")` is now
  `True`. Code that matches every terminal status by hand needs a `"completed"` branch. The
  version is a minor bump in step with the TypeScript packages, whose `TerminalStatus` union widened.

### Fixed

- `completed` is a terminal order status, as it is on the server: `TERMINAL_STATUSES` and
  `is_terminal` include it, so `wait_for_order` and the reconcile helper stop at a completed order
  instead of polling it until the timeout. The `status-machine.json` contract fixture lists it under
  `terminal`.

## [0.3.1] - 2026-10-23

_Built against FaaS API contract **v2.1.1**._ Documentation only: no SDK behaviour changed.

### Changed

- `CONTRACT_VERSION` is `2.1.1`. The contract now declares the `422 currency_not_available` that a
  service without USDT payments answers for `usdt_ton`; the SDK already mapped it to
  `UnprocessableError`.
- `get_pricing`, `get_pricing_batch`, `create_order` (sync and async) and `gifts.list` document that
  `UnprocessableError`.
- `Order.payment` and the campaign `payment` document that a `usdt_ton` order or campaign reads
  `None` where USDT payments are not offered, not only once it stops awaiting payment.
- The cross-language contract fixtures carry `contract_version` `2.1.1`. The two tenant-envelope V2
  signing vectors stamp `api_version: "2.1.1"` and are re-signed.

## [0.3.0] - 2026-10-03

_Built against FaaS API contract **v2.1.0**._ Additive: nothing existing was removed or renamed, and
order webhooks verify exactly as before.

### Added

- **Partner products** (enabled per tenant on request), sync and async: `client.campaigns`
  (create, add_recipients, validate, confirm, cancel / pause / resume, get, list / iter_all,
  recipients / iter_recipients, stats, capacity), `client.gifts.list(currency=…)` (required),
  `client.giveaways` (quote,
  create, list / iter_all, get, fund, cancel, close, enable_autopost / disable_autopost, entrants /
  iter_entrants, results, stats, attest, attestations / iter_attestations) with
  `client.giveaways.channels` and `client.giveaways.series`. Responses are `TypedDict`s
  (`mystars_faas.partner_types`); every giveaway `POST` sends an `Idempotency-Key`.
- **Signature V2 + tenant events**: `verify_webhook_signature_v2` (5-minute tolerance,
  constant-time, current + previous secrets), `WebhookVerifier(previous_secret=…, tolerance_sec=…)`
  with `is_valid_v2`, `verify_tenant_event` (the envelope, no `order_id` required) and
  `verify_event` (one endpoint for both kinds; its legacy fallback also tries `previous_secret`);
  `TenantEvent`, `TENANT_EVENT_TYPES`; FastAPI `faas_tenant_webhook_route` and Flask
  `faas_tenant_webhook_view`. A `tolerance_sec` or `now` that is not a finite number >= 0 raises
  `MyStarsValidationError` (`WebhookVerifier` and the adapters check `tolerance_sec` when built)
  instead of silently disabling the replay check.
- **Giveaway funding**: `build_funding_payment_request`, `verify_funding_payment` (expired or
  contradictory blocks are refused), `payment_comment`; `PaymentInstruction` reads `address_kind`
  and a block without `amount_units`; `build_ton_deeplink` / `build_ton_connect_messages` send no
  comment for a one-time deposit address; `build_jetton_transfer_payload` accepts `memo=None`.
- Errors: `UnprocessableError`, `FeatureUnavailableError` (never retried — including
  `autopost_unavailable` and `series_unavailable`; `gift_catalog_unavailable` stays retried), `IdempotencyInFlightError`
  (retried after `Retry-After` with the same key), and `details` on every API error.
- Contract fixtures: `webhook-v2-vectors.json`, the campaign / giveaway / series state machines, and a
  memo-less jetton vector.

### Changed

- A 422 whose code is not `recipient_ineligible` is now `UnprocessableError` instead of
  `RecipientIneligibleError` (order routes only ever answer `recipient_ineligible`), and a 409 maps to
  `OrderNotCancellableError` only for an order's "cannot cancel".

## [0.2.0] - 2026-09-24

_Built against FaaS API contract **v2.0.0**._ Contract 2.0.0 makes `payment_currency` required, so
this is a breaking release. It also carries everything that was prepared as 0.1.13, which was never
published.

### Migration

- Pass `payment_currency` (`"ton"` — the native GRAM coin, not USDT — or `"usdt_ton"`) on every
  `create_order`, `get_pricing` and `get_pricing_batch` call, sync and async; a call without it now
  raises `TypeError`.
- The CLI's `pricing` and `orders-create` need `--currency`.

### Added

- `PaymentInstruction` gains the contract v1.15.0 fields `asset` (`"GRAM"` / `"USDT"`), `decimals`
  (`9` / `6`), `amount_smallest_unit`, `transfer` (`"native"` / `"jetton"`) and `jetton_master`. Each
  defaults to `None`, so a v1.14.0 server still parses.
- `Order.payment_currency` and `Order.payment` on `get_order`, `list_orders`, `iter_orders` and
  `wait_for_order`. `payment_currency` (`"ton"` / `"usdt_ton"`) is always sent. `payment` is the
  order's `PaymentInstruction` only while the order is `awaiting_payment`, and `None` otherwise — a
  closed order offers no pay-to details. Both default to `None` for a v1.14.0 server. Pay
  `payment.amount` in `payment.currency`: `amount_ton` is the order's GRAM price, which equals the
  amount due only for a `ton` order.
- `failure_reason` `wrong_currency`: the payment arrived in a different asset than the order's
  `payment.currency`; it was returned in the asset received, via `reversal_tx`. Added to
  `contract/status-machine.json` as a terminal reason with funds returned.
- `PaymentCurrency` (`Literal["ton", "usdt_ton"]`) types `payment_currency` on both clients;
  `PAYMENT_CURRENCIES` is exported.

### Changed

- **Breaking:** `payment_currency` is a required keyword argument of `create_order`, `get_pricing`
  and `get_pricing_batch` (sync and async). A value other than `"ton"` or `"usdt_ton"` raises
  `MyStarsValidationError` before any request.
- **Breaking:** the CLI's `--currency` is required for `pricing` and `orders-create`.
- The payment builders (`build_payment_request`, `build_ton_connect_messages`, `build_ton_deeplink`)
  run one shared guard: an unknown `currency` now raises instead of being treated as USDT, and so does
  a payment block whose `amount_units`, `asset`, `decimals` or `transfer` contradict its `currency`,
  whose `amount_smallest_unit` is not exactly `amount` in the asset's smallest unit, or whose amount
  is zero or negative.

### Fixed

- `to_nano` / `to_micro` accepted a leading `-`: `to_nano("-1.5")` returned
  `-1500000000`. A signed amount now raises `MyStarsValidationError`, matching the TypeScript SDK.
- README: the payment example indexed `req.ton_connect[0]`, which raises `IndexError` for a USDT order
  built without the payer's wallet addresses; it now branches on the currency.

## [0.1.12] - 2026-09-23

_Built against FaaS API contract **v1.14.0**. No API change._

### Changed

- The PyPI `Homepage` link now points at the API overview,
  [mystars.tg/developers](https://mystars.tg/developers), with the [MyStars.tg](https://mystars.tg)
  store added to the project links and the README. The API reference stays at
  [mystars.tg/docs](https://mystars.tg/docs).

## [0.1.11] - 2026-09-20

_Built against FaaS API contract **v1.14.0**._

### Added

- `failure_reason` now has a documented value for an order that is `held` rather than finished.
  `reversal_pending` means the goods could not be delivered and your funds are still being
  returned; the order reaches `reversed` when that lands. `reversal_unsettled` means the return
  itself could not be delivered to your address, so you do **not** have your money back and a
  person is settling it by hand.
- `contract/status-machine.json` gains a `failure_reasons` block — the terminal and held values,
  and which of them mean your funds were returned. Both SDKs load it in their tests, so the
  vocabulary cannot drift between languages.

### Notes

- Read `reversal_unsettled` carefully against `undeliverable`: they share a word and point in
  opposite directions. `undeliverable` is about the GOODS and ends with you made whole;
  `reversal_unsettled` is about the RETURN and does not.

## [0.1.10] - 2026-09-15

_Built against FaaS API contract **v1.13.0**._

### Changed

- For `usdt_ton`, the `fee` breakdown now comes in one of two forms. A swap-backed order keeps the
  fee it has today (the 1% swap fee plus GRAM swap gas, labelled "1% swap + <gas> GRAM gas"); an
  order settled without a swap is charged network gas alone, labelled "TON network gas", so its
  `processing_fee` is a few cents. No existing field changed, and
  `subtotal + processing_fee == total == amount` still holds.

### Added

- `FeeBreakdown.kind` — `"swap"` or `"network"`. Branch on it to choose your own wording for the
  fee, never on `description`. A response without it (a server older than contract v1.13.0, whose
  fees are all swap-backed) parses as `"swap"`, and the new field defaults to `"swap"` when a
  `FeeBreakdown` is constructed directly, so existing code keeps working.
- `apply_retail_markup` reads neither `description` nor `kind`, so retail pricing needs no change.
  The contract vectors now carry `kind`, with a network-gas case.

## [0.1.9] - 2026-08-04

_Built against FaaS API contract **v1.12.0**._

### Changed

- The order payment window is now **2 hours** (was 1 hour). No request or response field changed
  shape: `expires_at` on the order is still the authoritative deadline, it simply lands further
  out. Code that reads `expires_at` needs no change; code that hardcodes a duration was already
  wrong and is now wrong by more.
- The API description no longer quotes the window's length anywhere — it points at `expires_at`
  instead, so a future change to the window cannot make the published contract stale.

### Note

- `wait_for_order` still defaults to a **1800 s** budget, which is now a quarter of the payment
  window rather than half of it. Raise `timeout` if you rely on the default to cover a payer
  taking the full window.

## [0.1.8] - 2026-07-31

_Built against FaaS API contract **v1.11.0** (unchanged)._

### Changed

- The payment token is named **GRAM** in every published string — the ``[project]`` description,
  ``README.md``, ``SECURITY.md``, the runnable examples, and the docstrings that ship inside the
  wheel. A parenthetical after **GRAM** never states the chain — after that ticker it can only mean
  the former name. ``USDT (TON)`` is unaffected: USDT was never renamed, so its parenthetical says
  which USDT, symmetric with ``USDT (ERC20)`` / ``USDT (TRC20)``. The network and its protocol
  structures keep their own name throughout — "TON wallet", "TON Connect", "TON address",
  "TON cell", "TON BoC" — and ``nanoTON`` is unchanged everywhere, it being the chain's own
  smallest-unit name.
- Because a bare ticker reads as an unknown new coin to anyone meeting it cold on the PyPI page,
  the FIRST mention in each published document — the ``[project] description`` PyPI lists, and the
  opening line of ``README.md`` — now spells out where it came from: **GRAM (ex TON)**. That is the
  ONE meaning a parenthetical after ``GRAM`` ever carries. Every later mention in that document
  stays bare ``GRAM``, and the docstrings keep the bare form throughout: a
  reader who has reached the wheel is already integrating and does not need it repeated on every
  symbol. Transitional — it will be dropped once the name has settled.
- **No API surface changed, and no behavioural change.** The ``ton`` / ``usdt_ton`` currency codes,
  every public name (``to_nano``, ``ton_deeplink``, ``ton_connect``, ``TonConnectMessage``,
  ``amount_ton``, ``usdt_per_ton``, ``JETTON_TRANSFER_GAS_NANO``), every wire value, and every
  raised message are byte-identical to 0.1.7 — upgrading is a no-op for code, and this release
  exists only because a published README or docstring can be corrected no other way. (The
  TypeScript SDK's 0.1.8 reworded two ``InsufficientBalanceError`` messages; this package ships no
  wallet/payer module, so it has no equivalent string.)
- Documentation links in ``README.md`` and ``CHANGELOG.md`` now point at public URLs — the HTTP API
  portal ([mystars.tg/docs](https://mystars.tg/docs)) and the SDK landing page
  ([mystars.tg/docs/sdks](https://mystars.tg/docs/sdks)). The previous links were
  repository-relative and resolved to nothing for anyone reading the published package or the
  GitHub mirror.

## [0.1.7] - 2026-07-28

_Built against FaaS API contract **v1.11.0** (was v1.10.0)._

### Added

- ``RecipientCheck.indeterminate`` — ``True`` when the eligibility probe behind
  ``check_recipient()`` could not reach a verdict and the endpoint failed open, so ``eligible`` is a
  permissive default rather than a measurement and the recipient has NOT been checked; ``False`` on
  every real verdict (eligible or not). Treat it as "unknown", never as "yes": going on to
  ``create_order()`` is safe (the order runs its own authoritative check), but don't present the
  recipient to a buyer as confirmed-deliverable.

### Changed

- ``RecipientCheck.from_dict`` defaults a missing ``indeterminate`` to ``False``, so the field is
  always a real bool — including against a server older than contract v1.11.0, which omits it
  (absent and ``False`` mean the same thing). Strictly additive; no existing field changed.

## [0.1.6] - 2026-07-26

_Built against FaaS API contract **v1.10.0** (unchanged). Docs-only — no API surface change._

### Changed

- Documentation: the API-key link in the README/SECURITY/examples points at
  `https://t.me/my_stars_tg_bot` again. Both `t.me` and `telegram.me` serve the identical route and
  Telegram's client accepts either, but `t.me` is the canonical short domain and the only host some
  third-party integrations recognise, so the platform standardised back on it (this reverses the
  0.1.5 change below). Also updated: `SECURITY.md`, the runnable examples and the
  `.github/ISSUE_TEMPLATE/*` support links. No API-surface change — only the version constants
  move — and the bump is published so the rendered PyPI README carries the canonical link.

## [0.1.5] - 2026-07-14

_Built against FaaS API contract **v1.10.0** (unchanged). Docs-only — no API surface change._

### Changed

- Documentation: the API-key link in the README/SECURITY/examples now points at
  `https://telegram.me/my_stars_tg_bot` instead of the retired `t.me` short domain (Telegram lost
  the `t.me` domain; `telegram.me` serves the identical route). No code change — bump published so
  the rendered PyPI README carries a live link.

## [0.1.4] - 2026-07-11

_Built against FaaS API contract **v1.10.0** (was v1.9.0)._

### Added

- `MyStarsClient.get_pricing_batch(quantities=[...], payment_currency=None)` (sync + async) —
  quote up to 200 Stars quantities in ONE ``GET /v1/pricing/batch`` request (contract 1.10.0).
  Entries carry the same ``amount`` + ``fee`` as ``get_pricing``; new ``PricingQuoteBatch`` /
  ``PricingBatchEntry`` models exported.

## [0.1.3] - 2026-06-29

_Built against FaaS API contract **v1.9.0** (unchanged). Bug-fix + docs patch._

### Fixed
- `to_nano` / `to_micro` now accept a `Decimal` in scientific notation (e.g. `Decimal('1E-9')`,
  or a large `Decimal('1E3')`). A `Decimal`/`int` is normalised to plain fixed-point
  (`format(d, 'f')`) before validation, so a value whose `str()` is exponential no longer
  raises a spurious `MyStarsValidationError`. Plain-decimal **string** validation is unchanged —
  a scientific-notation *string* like `"1e3"` stays rejected (cross-SDK grammar parity), and a
  non-finite `Decimal` (`NaN`/`Infinity`) is still rejected.

### Docs
- README: Quick start documents that the key is read from the **environment** (export it, or load
  a `.env` yourself with `python-dotenv` — not a dependency of this SDK). Clarified that
  `apply_retail_markup` returns money fields as **decimal strings** (not `Decimal`) and needs the
  `fee` block for `usdt_ton`; that `order.payment` is on the `create_order` result
  (`CreateOrderResult`), not on an `Order`; and that `ton_connect` is a `list[TonConnectMessage]`.
- `to_nano`/`to_micro` docstrings now describe the per-type (string vs `Decimal`/int) handling.

_The first published release. Built against FaaS API contract **v1.9.0**._

### Added
- `UnauthorizedError` / `ForbiddenError` — exported aliases of `AuthenticationError` (401) /
  `PermissionDeniedError` (403), so code written against the TypeScript SDK's names catches the same
  error.
- `parse_retry_after_ms` now also parses the **HTTP-date** form of `Retry-After` (not just
  delta-seconds), matching the TypeScript SDK; the instant is clamped to 0 for a past date.
- CLI `webhook-verify` reads the secret from `MYSTARS_WEBHOOK_SECRET` (preferred over `--secret`,
  which leaks via the process list / shell history).
- Cross-language status-machine parity assertions (`WEBHOOK_TERMINAL_STATUSES`,
  `CANCELLABLE_STATUSES`, `INITIAL_STATUS`) pinned against `contract/status-machine.json`.
- MIT `LICENSE` shipped in the sdist + wheel.

### Changed
- `to_nano` / `to_micro` validate amounts against the same decimal grammar as the TypeScript SDK
  (`^-?\d+(\.\d+)?$`) — scientific notation, a leading `+`, and bare dots are rejected, so both SDKs
  accept/reject identical strings.
- `_to_int` accepts a finite float-form numeric header (e.g. `"60.0"`), matching the TypeScript SDK.
- Re-verified + re-pinned against FaaS API contract **v1.9.0** (was v1.8.2): the order payment window
  is now **1 hour** (was 15 min). `expires_at` is unchanged in shape and remains the authoritative
  deadline — no SDK code change; if you read `expires_at` (rather than assuming 15 min) nothing in
  your integration changes.

### Fixed
- A response body larger than **4 MB** is rejected (`response_too_large`) by streaming with a bounded
  reader instead of being buffered whole — matches the TypeScript SDK's `MAX_RESPONSE_BYTES` and
  prevents a hostile/buggy upstream from OOM-ing the client (sync + async).
- `cancel_order` tolerates an empty-body / 204 success response instead of raising on a missing field.
- `await_order` uses `asyncio.get_running_loop()` (was `get_event_loop()`).

### Security
- Tests assert the API key never appears in any exception message / `repr` / `raw`.
