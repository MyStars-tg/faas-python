"""Wire models — dataclasses mirroring the FaaS ``/v1`` JSON, with money as ``Decimal``.

Every amount is parsed from the API's decimal strings into :class:`decimal.Decimal`
and stays exact end to end (never a float).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# ─── status machine ──────────────────────────────────────────────────────────

ORDER_STATUSES = (
    "received", "awaiting_payment", "paid", "reserved", "swapping", "funding",
    "purchasing", "fulfilling", "completed", "delivered", "failed", "reversed",
    "expired", "held", "cancelled",
)
TERMINAL_STATUSES = frozenset({"delivered", "failed", "reversed", "expired", "cancelled"})
# Statuses a webhook is delivered for (no "cancelled" — cancels are client-initiated).
WEBHOOK_TERMINAL_STATUSES = frozenset({"delivered", "failed", "reversed", "expired"})
# Statuses from which an order can still be cancelled.
CANCELLABLE_STATUSES = frozenset({"awaiting_payment"})
# The status a newly-created order starts in.
INITIAL_STATUS = "awaiting_payment"


def is_terminal(status: str) -> bool:
    """True when an order has reached a final state."""
    return status in TERMINAL_STATUSES


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _req_dec(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass
class CurrencyInfo:
    """An accepted payment currency.

    Attributes:
        code: The currency code (e.g. ``"ton"``, ``"usdt_ton"``).
        chain: The settlement chain (e.g. ``"ton"``).
        name: Human-readable display name.
    """

    code: str
    chain: str
    name: str

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CurrencyInfo:
        """Build a :class:`CurrencyInfo` from a ``/v1/currencies`` JSON entry."""
        return cls(code=d["code"], chain=d["chain"], name=d["name"])


@dataclass
class Product:
    """A buyable product type and its allowed shape (price-free catalog metadata).

    Attributes:
        type: ``"stars"`` or ``"premium"``.
        name: Human-readable display name.
        parameter: The order field that carries the amount (``"quantity"`` or ``"months"``).
        min: Minimum allowed value of ``parameter``.
        max: Maximum allowed value of ``parameter``.
        values: The fixed allowed set (e.g. ``[3, 6, 12]`` for premium), or ``None`` for a
            continuous range (stars).
    """

    type: str
    name: str
    parameter: str
    min: int
    max: int
    values: list[int] | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Product:
        """Build a :class:`Product` from a ``/v1/products`` JSON entry."""
        return cls(type=d["type"], name=d["name"], parameter=d["parameter"], min=d["min"], max=d["max"], values=d.get("values"))


@dataclass
class FeeBreakdown:
    """The itemised ``usdt_ton`` processing-fee split (an itemisation of ``amount``, not extra).

    Invariant: ``subtotal + processing_fee == total == amount``. All amounts are ``Decimal``.

    Attributes:
        subtotal: The goods value (before the processing fee).
        processing_fee: The pass-through processing fee already included in ``amount`` — a swap
            fee plus swap gas, or network gas alone (``description`` names which).
        total: ``subtotal + processing_fee`` (equals the binding ``amount``).
        description: Human-readable fee description.
        currency: The fee currency (``"usdt"``).
        kind: The machine-readable fee form — ``"swap"`` (swap fee plus swap gas) or ``"network"``
            (network gas alone). Branch on this, never on ``description``.
    """

    subtotal: Decimal
    processing_fee: Decimal
    total: Decimal
    description: str
    currency: str
    kind: str = "swap"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FeeBreakdown:
        """Build a :class:`FeeBreakdown` from a JSON ``fee`` object (amounts parsed to ``Decimal``)."""
        return cls(
            subtotal=_req_dec(d["subtotal"]),
            processing_fee=_req_dec(d["processing_fee"]),
            total=_req_dec(d["total"]),
            description=d["description"],
            currency=d["currency"],
            # A server older than contract 1.13.0 sends no `kind`; every fee it issues is swap-backed.
            kind=d.get("kind", "swap"),
        )


@dataclass
class PricingQuote:
    """A wholesale price quote from ``GET /v1/pricing``.

    Attributes:
        type: ``"stars"`` or ``"premium"`` (echoed).
        quantity: Star count (``stars``), else ``None``.
        months: Premium duration (``premium``), else ``None``.
        amount: The binding price as a ``Decimal``, in ``currency`` units.
        currency: ``"ton"`` or ``"usdt_ton"``.
        fee: The itemised :class:`FeeBreakdown` for ``usdt_ton`` (``None`` for ``ton`` and for a
            ``usdt_ton`` quote with an incomplete cost snapshot).
        usdt_per_ton: The GRAM→USDT rate used, when available (``Decimal``), else ``None``.
        quoted_at: ISO-8601 timestamp the quote was produced.
        valid_until: ISO-8601 timestamp after which the quote may have drifted.
    """

    type: str
    quantity: int | None
    months: int | None
    amount: Decimal
    currency: str
    fee: FeeBreakdown | None
    usdt_per_ton: Decimal | None
    quoted_at: str
    valid_until: str

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PricingQuote:
        """Build a :class:`PricingQuote` from the ``/v1/pricing`` JSON (money → ``Decimal``)."""
        return cls(
            type=d["type"], quantity=d.get("quantity"), months=d.get("months"),
            amount=_req_dec(d["amount"]), currency=d["currency"],
            fee=FeeBreakdown.from_dict(d["fee"]) if d.get("fee") else None,
            usdt_per_ton=_dec(d.get("usdt_per_ton")), quoted_at=d["quoted_at"], valid_until=d["valid_until"],
        )


@dataclass
class PricingBatchEntry:
    """One entry of ``GET /v1/pricing/batch`` — the same ``amount`` + ``fee`` a single quote returns.

    Attributes:
        quantity: The star count this entry priced.
        amount: The binding price as a ``Decimal``, in the batch's top-level currency.
        fee: The itemised :class:`FeeBreakdown` for ``usdt_ton`` (``None`` for ``ton``).
    """

    quantity: int
    amount: Decimal
    fee: FeeBreakdown | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PricingBatchEntry:
        """Build a :class:`PricingBatchEntry` from one ``quotes[]`` element."""
        return cls(
            quantity=d["quantity"],
            amount=_req_dec(d["amount"]),
            fee=FeeBreakdown.from_dict(d["fee"]) if d.get("fee") else None,
        )


@dataclass
class PricingQuoteBatch:
    """The result of ``GET /v1/pricing/batch`` (stars-only, quantities deduped + sorted).

    Attributes:
        type: Always ``"stars"``.
        currency: ``"ton"`` or ``"usdt_ton"``.
        quotes: One :class:`PricingBatchEntry` per (deduped) requested quantity.
        usdt_per_ton: The GRAM→USDT rate used, when available (``Decimal``), else ``None``.
        quoted_at: ISO-8601 timestamp the quotes were produced.
        valid_until: ISO-8601 timestamp after which the quotes may have drifted.
    """

    type: str
    currency: str
    quotes: list[PricingBatchEntry]
    usdt_per_ton: Decimal | None
    quoted_at: str
    valid_until: str

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PricingQuoteBatch:
        """Build a :class:`PricingQuoteBatch` from the ``/v1/pricing/batch`` JSON."""
        return cls(
            type=d["type"],
            currency=d["currency"],
            quotes=[PricingBatchEntry.from_dict(e) for e in d.get("quotes", [])],
            usdt_per_ton=_dec(d.get("usdt_per_ton")),
            quoted_at=d["quoted_at"],
            valid_until=d["valid_until"],
        )


@dataclass
class RecipientCheck:
    """The result of ``POST /v1/recipients/check``.

    Attributes:
        resolved: ``True`` if the ``@username`` was found on Telegram.
        eligible: ``True`` if the recipient can receive the requested item.
        recipient_name: The resolved display name, if any.
        reason: A structured ineligibility reason (e.g. ``"already_subscribed"``), if any.
        telegram_message: A buyer-facing message describing the outcome, if any.
        indeterminate: ``True`` when the eligibility probe could not reach a verdict and the
            endpoint FAILED OPEN — ``eligible`` is then a permissive default, not a
            measurement, so the recipient has NOT been checked. ``False`` on every real
            verdict (eligible or not). Treat it as "unknown", never as "yes": it is safe to
            go on to :meth:`~mystars_faas.MyStarsClient.create_order` (which runs its own
            authoritative check), but do not present the recipient to a buyer as
            confirmed-deliverable. Sent from contract v1.11.0 on; an older server omits the
            field, which means the same as ``False``.
    """

    resolved: bool
    eligible: bool
    recipient_name: str | None
    reason: str | None
    telegram_message: str | None
    indeterminate: bool = False

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RecipientCheck:
        """Build a :class:`RecipientCheck` from the ``/v1/recipients/check`` JSON."""
        return cls(
            resolved=d["resolved"], eligible=d["eligible"], recipient_name=d.get("recipient_name"),
            reason=d.get("reason"), telegram_message=d.get("telegram_message"),
            # Absent on a server older than contract v1.11.0 — same meaning as False.
            indeterminate=d.get("indeterminate", False),
        )


@dataclass
class PaymentInstruction:
    """How to pay for an order — the ``payment`` block of a create response and, from contract
    v1.15.0, of an order read (``GET /v1/orders/{id}`` or a ``GET /v1/orders`` item) while that
    order is still ``awaiting_payment``.

    Feed this to :func:`~mystars_faas.build_payment_request` to get a signable deeplink /
    TON Connect message.

    ``ton`` is the native GRAM coin; ``usdt_ton`` is the USDT jetton on the TON network. The
    v1.15.0 fields restate that choice explicitly and are ``None`` on an older server.

    Attributes:
        currency: ``"ton"`` or ``"usdt_ton"``.
        chain: Settlement chain (defaults to ``"ton"``).
        pay_to_address: Destination address; the buyer sends here (may be ``None`` briefly).
        memo: The required transfer comment (the order id); identifies the payment on-chain.
        amount: The exact amount to send, as a ``Decimal``, in ``amount_units``.
        amount_units: The unit of ``amount`` (``"ton"`` or ``"usdt"``).
        fee: The itemised :class:`FeeBreakdown` (``usdt_ton`` only), else ``None``.
        asset: v1.15.0 — the asset to send: ``"GRAM"`` for ``ton``, ``"USDT"`` for ``usdt_ton``.
        decimals: v1.15.0 — the asset's decimals: ``9`` (nanoTON) or ``6`` (micro-USDT).
        amount_smallest_unit: v1.15.0 — ``amount`` in the asset's smallest unit, as an integer string.
        transfer: v1.15.0 — ``"native"`` (a plain GRAM transfer) or ``"jetton"`` (a TEP-74 transfer).
        jetton_master: v1.15.0 — the USDT jetton master for ``usdt_ton``; ``None`` for ``ton``.
    """

    currency: str
    chain: str
    pay_to_address: str | None
    memo: str | None
    amount: Decimal
    amount_units: str
    fee: FeeBreakdown | None
    asset: str | None = None
    decimals: int | None = None
    amount_smallest_unit: str | None = None
    transfer: str | None = None
    jetton_master: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PaymentInstruction:
        """Build a :class:`PaymentInstruction` from a JSON ``payment`` object (money → ``Decimal``)."""
        return cls(
            currency=d["currency"], chain=d.get("chain", "ton"), pay_to_address=d.get("pay_to_address"),
            memo=d.get("memo"), amount=_req_dec(d["amount"]), amount_units=d["amount_units"],
            fee=FeeBreakdown.from_dict(d["fee"]) if d.get("fee") else None,
            asset=d.get("asset"), decimals=d.get("decimals"), amount_smallest_unit=d.get("amount_smallest_unit"),
            transfer=d.get("transfer"), jetton_master=d.get("jetton_master"),
        )


@dataclass
class Order:
    """A full order record from ``GET /v1/orders/{id}`` (or a list page).

    Attributes:
        order_id: The order UUID (also the on-chain payment memo).
        status: Current lifecycle status; one of ``ORDER_STATUSES`` (see
            :func:`is_terminal`).
        type: ``"stars"`` or ``"premium"``.
        recipient_username: The recipient handle, if present.
        quantity: Star count (``stars``), else ``None``.
        months: Premium duration (``premium``), else ``None``.
        amount_ton: The order's GRAM price as a ``Decimal``, when applicable, else ``None``. It
            equals the amount due only for a ``ton`` order — pay :attr:`payment` instead.
        payment_tx: The inbound payment tx hash, once detected.
        purchase_tx: The Fragment purchase / delivery tx hash, once delivered.
        failure_reason: A machine reason when ``status`` is
            ``failed``/``reversed``/``expired``, or while it is ``held``. The held
            values are ``fulfilment_retrying``, ``recipient_unreachable``,
            ``reversal_pending`` and ``reversal_unsettled`` — only the last means
            your funds have NOT been returned. ``wrong_currency`` (contract v1.15.0)
            means the payment arrived in a different asset than ``payment.currency``;
            it was returned in the asset received, via ``reversal_tx``.
        reversal_tx: The refund tx hash, when a reversal occurred.
        telegram_message: A buyer-facing status message, if any.
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
        expires_at: ISO-8601 payment-window expiry, if applicable.
        payment_currency: The currency the order is invoiced in (contract v1.15.0) — always sent,
            whatever the status: ``"ton"`` (the native GRAM coin) or ``"usdt_ton"`` (USDT).
            ``None`` on a server older than 1.15.0.
        payment: How to pay this order (contract v1.15.0) — a :class:`PaymentInstruction` present
            only while ``status`` is ``awaiting_payment``, ``None`` otherwise: a closed order offers
            no pay-to details. Also ``None`` on a server older than 1.15.0.
    """

    order_id: str
    status: str
    type: str
    recipient_username: str | None
    quantity: int | None
    months: int | None
    amount_ton: Decimal | None
    payment_tx: str | None
    purchase_tx: str | None
    failure_reason: str | None
    reversal_tx: str | None
    telegram_message: str | None
    created_at: str
    updated_at: str
    expires_at: str | None
    payment_currency: str | None = None
    payment: PaymentInstruction | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Order:
        """Build an :class:`Order` from an order JSON object (money → ``Decimal``)."""
        return cls(
            order_id=d["order_id"], status=d["status"], type=d["type"],
            recipient_username=d.get("recipient_username"), quantity=d.get("quantity"), months=d.get("months"),
            amount_ton=_dec(d.get("amount_ton")), payment_tx=d.get("payment_tx"), purchase_tx=d.get("purchase_tx"),
            failure_reason=d.get("failure_reason"), reversal_tx=d.get("reversal_tx"),
            telegram_message=d.get("telegram_message"), created_at=d["created_at"], updated_at=d["updated_at"],
            expires_at=d.get("expires_at"),
            payment_currency=d.get("payment_currency"),
            payment=PaymentInstruction.from_dict(d["payment"]) if d.get("payment") else None,
        )


@dataclass
class CreateOrderResult:
    """The result of ``POST /v1/orders`` — the new order plus how to pay it.

    Attributes:
        order_id: The order UUID.
        status: The initial status (typically ``awaiting_payment``).
        type: ``"stars"`` or ``"premium"`` (echoed).
        quantity: Star count (``stars``), else ``None``.
        months: Premium duration (``premium``), else ``None``.
        payment: The :class:`PaymentInstruction` to settle.
        expires_at: ISO-8601 payment-window expiry.
        replayed: ``True`` when this was an idempotent replay of a prior identical create
            (server returned HTTP 200 instead of 201).
    """

    order_id: str
    status: str
    type: str
    quantity: int | None
    months: int | None
    payment: PaymentInstruction
    expires_at: str
    replayed: bool

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], *, replayed: bool) -> CreateOrderResult:
        """Build a :class:`CreateOrderResult` from the create-order JSON.

        Args:
            d: The decoded create-order response body.
            replayed: Whether the response was an idempotent replay (HTTP 200 vs 201).
        """
        return cls(
            order_id=d["order_id"], status=d["status"], type=d["type"],
            quantity=d.get("quantity"), months=d.get("months"),
            payment=PaymentInstruction.from_dict(d["payment"]), expires_at=d["expires_at"], replayed=replayed,
        )


@dataclass
class OrdersPage:
    """One keyset page of orders from ``GET /v1/orders``.

    Attributes:
        orders: The :class:`Order` objects on this page, newest-first.
        next_cursor: The cursor for the next page, or ``None`` on the last page.
    """

    orders: list[Order] = field(default_factory=list)
    next_cursor: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OrdersPage:
        """Build an :class:`OrdersPage` from the ``/v1/orders`` list JSON."""
        return cls(orders=[Order.from_dict(o) for o in d.get("orders", [])], next_cursor=d.get("next_cursor"))


@dataclass
class WebhookEvent:
    """A parsed, signature-verified terminal webhook (minimal by design — fetch the order for detail).

    Attributes:
        order_id: The order UUID (dedup on this — delivery is at-least-once and unordered).
        status: A terminal status (``delivered``/``failed``/``reversed``/``expired``).
        failure_reason: A machine reason on a non-``delivered`` terminal status, if any.
        purchase_tx: The delivery tx hash on ``delivered``, if any.
    """

    order_id: str
    status: str
    failure_reason: str | None = None
    purchase_tx: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WebhookEvent:
        """Build a :class:`WebhookEvent` from a decoded webhook body."""
        return cls(
            order_id=d["order_id"], status=d["status"],
            failure_reason=d.get("failure_reason"), purchase_tx=d.get("purchase_tx"),
        )
