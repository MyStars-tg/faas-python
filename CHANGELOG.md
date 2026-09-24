# Changelog

All notable changes to the MyStars FaaS Python SDK (`mystars-faas`) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The `CONTRACT_VERSION` each
release is built + verified against (the FaaS API `info.version`) is noted per entry; the live
contract version is published at [mystars.tg/docs](https://mystars.tg/docs).

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
