# Changelog

All notable changes to the MyStars FaaS Python SDK (`mystars-faas`) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The `CONTRACT_VERSION` each
release is built + verified against (the FaaS API `info.version`) is noted per entry — see
[docs/sdk/versioning.md](../../docs/sdk/versioning.md).

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
