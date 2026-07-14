"""Retail-markup calculator — Decimal, exact, matching the server's two-stage cent-ceil.

Takes our WHOLESALE quote and computes the price to charge your end-customer after
adding YOUR retail margin (and, optionally, passing our processing fee through).
``ceil_usd_to_cents`` is a byte-for-byte port of the server's float cent-ceil; the
cross-language ``markup-vectors.json`` fixture pins this against the TypeScript SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from .errors import MyStarsValidationError
from .models import PaymentInstruction, PricingQuote

_ONE = Decimal(1)


def _to_decimal(value: Any, label: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise MyStarsValidationError(f"{label} must be a finite decimal, got {value!r}") from exc
    if not d.is_finite():
        raise MyStarsValidationError(f"{label} must be a finite decimal, got {value!r}")
    return d


def ceil_usd_to_cents(usd: Decimal | str | float | int) -> Decimal:
    """Ceil a USD(T) amount to whole cents without float drift (snap to micro, then ceil to cents)."""
    micro = (_to_decimal(usd, "usd") * 1_000_000).quantize(_ONE, rounding=ROUND_HALF_UP)
    cents = (micro / 10_000).quantize(_ONE, rounding=ROUND_CEILING)
    return cents / 100


def ceil_ton_to_4dp(ton: Decimal | str | float | int) -> Decimal:
    """Ceil a TON amount to the 0.0001-GRAM grid (snap to nanoTON, then ceil)."""
    nano = (_to_decimal(ton, "ton") * 1_000_000_000).quantize(_ONE, rounding=ROUND_HALF_UP)
    grid = (nano / 100_000).quantize(_ONE, rounding=ROUND_CEILING)
    return grid / 10_000


@dataclass
class RetailLineItem:
    """One labelled line of a retail breakdown.

    Attributes:
        label: Human-readable line label (e.g. ``"Goods"``, ``"Processing fee"``).
        amount: The line amount as a formatted decimal string.
    """

    label: str
    amount: str


@dataclass
class RetailQuote:
    """An itemised customer-facing quote produced by :func:`apply_retail_markup`.

    All money fields are formatted decimal strings (USD to 2 dp, TON trimmed to ≤4 dp).

    Attributes:
        currency: ``"ton"`` or ``"usdt_ton"`` (echoed from the wholesale quote).
        wholesale_amount: The original wholesale ``amount`` you pay MyStars.
        margin_pct: The retail margin percent you applied.
        goods: The goods value the margin is applied to (``fee.subtotal`` for ``usdt_ton``,
            else the full amount).
        markup: Your added margin (``subtotal - goods``).
        subtotal: The marked-up goods total (cent/grid-ceil'd).
        processing_fee: The passed-through processing fee (``usdt_ton`` only; ``"0"`` otherwise).
        total: What to charge your customer (``subtotal + processing_fee``).
        profit: Your gross margin (``total - wholesale_amount``).
        line_items: The itemised customer-facing lines.
    """

    currency: str
    wholesale_amount: str
    margin_pct: float
    goods: str
    markup: str
    subtotal: str
    processing_fee: str
    total: str
    profit: str
    line_items: list[RetailLineItem]


def _fmt_usd(n: Decimal) -> str:
    return str(n.quantize(Decimal("0.01")))


def _fmt_ton(n: Decimal) -> str:
    s = format(n.quantize(Decimal("0.0001")), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _extract(quote: Mapping[str, Any] | PricingQuote | PaymentInstruction) -> tuple[str, str, Mapping[str, Any] | None]:
    if isinstance(quote, Mapping):
        fee = quote.get("fee")
        return str(quote["amount"]), str(quote["currency"]), fee
    fee_obj = getattr(quote, "fee", None)
    fee = None
    if fee_obj is not None:
        fee = {"subtotal": fee_obj.subtotal, "processing_fee": fee_obj.processing_fee}
    return str(quote.amount), str(quote.currency), fee


def apply_retail_markup(
    quote: Mapping[str, Any] | PricingQuote | PaymentInstruction,
    *,
    margin_pct: float,
    pass_through_processing_fee: bool = True,
) -> RetailQuote:
    """Apply your retail margin to a wholesale quote and return an itemised breakdown.

    Uses the server's exact two-stage cent-ceil (USD) / 0.0001-grid-ceil (TON) so the price you
    show, the wallet amount, and our quote all land on the same unit. For ``usdt_ton`` the margin
    is applied to the *goods* (``fee.subtotal``) only; our processing fee is either passed through
    as a separate line the customer pays, or absorbed by you. Our wholesale markup is server-side
    and redacted — ``margin_pct`` is purely *your* retail margin.

    Args:
        quote: A wholesale quote — a :class:`~mystars_faas.PricingQuote`, a
            :class:`~mystars_faas.PaymentInstruction`, or a raw ``{"amount", "currency", "fee"?}``
            mapping.
        margin_pct: Your retail margin percent (e.g. ``15`` for +15%). Must be ≥ 0.
        pass_through_processing_fee: For ``usdt_ton``, ``True`` (default) adds our processing fee
            as a separate customer line; ``False`` makes you absorb it. Ignored for ``ton``.

    Returns:
        A :class:`RetailQuote` with the marked-up ``total``, your ``profit``, and ``line_items``.

    Raises:
        MyStarsValidationError: If ``margin_pct`` is negative/non-numeric, an amount/fee field isn't
            a finite decimal, or a ``usdt_ton`` quote has no ``fee`` breakdown (``fee`` is ``None`` —
            the fee-inclusive ``amount`` can't be safely marked up; re-quote ``GET /v1/pricing`` first).
    """
    if not isinstance(margin_pct, (int, float)) or margin_pct < 0:
        raise MyStarsValidationError(f"margin_pct must be a non-negative number, got {margin_pct}")
    amount_str, currency, fee = _extract(quote)
    amount = _to_decimal(amount_str, "amount")
    factor = _to_decimal(1, "factor") + _to_decimal(margin_pct, "margin_pct") / 100

    if currency == "usdt_ton":
        # `amount` for usdt_ton is fee-INCLUSIVE. Without the fee breakdown we cannot separate the
        # goods from the processing fee, so applying the margin to `amount` would mark up the fee too
        # AND mislabel the "Goods" line. Refuse — the caller must re-quote to get the `fee` block.
        # (Parity with the TS SDK's applyRetailMarkup; /v1/pricing returns fee:null on cold-FX rows.)
        if not fee:
            raise MyStarsValidationError(
                "usdt_ton amount has no fee breakdown; re-quote via GET /v1/pricing before applying markup"
            )
        goods = _to_decimal(fee["subtotal"], "fee.subtotal")
        our_fee = _to_decimal(fee["processing_fee"], "fee.processing_fee")
        retail_goods = ceil_usd_to_cents(goods * factor)
        customer_fee = ceil_usd_to_cents(our_fee) if pass_through_processing_fee else _to_decimal(0, "fee")
        markup = retail_goods - goods
        total = retail_goods + customer_fee
        profit = total - amount
        return RetailQuote(
            currency="usdt_ton",
            wholesale_amount=amount_str,
            margin_pct=margin_pct,
            goods=_fmt_usd(goods),
            markup=_fmt_usd(markup),
            subtotal=_fmt_usd(retail_goods),
            processing_fee=_fmt_usd(customer_fee),
            total=_fmt_usd(total),
            profit=_fmt_usd(profit),
            line_items=[
                RetailLineItem("Goods", _fmt_usd(goods)),
                RetailLineItem(f"Retail margin ({_pct(margin_pct)}%)", _fmt_usd(markup)),
                RetailLineItem("Processing fee", _fmt_usd(customer_fee)),
            ],
        )

    # ton — no processing fee.
    retail_goods = ceil_ton_to_4dp(amount * factor)
    markup = retail_goods - amount
    return RetailQuote(
        currency="ton",
        wholesale_amount=amount_str,
        margin_pct=margin_pct,
        goods=_fmt_ton(amount),
        markup=_fmt_ton(markup),
        subtotal=_fmt_ton(retail_goods),
        processing_fee="0",
        total=_fmt_ton(retail_goods),
        profit=_fmt_ton(markup),
        line_items=[
            RetailLineItem("Goods", _fmt_ton(amount)),
            RetailLineItem(f"Retail margin ({_pct(margin_pct)}%)", _fmt_ton(markup)),
        ],
    )


def _pct(margin_pct: float) -> str:
    # Render the percent like JS does (12.5 → "12.5", 20 → "20").
    return str(int(margin_pct)) if float(margin_pct).is_integer() else str(margin_pct)
