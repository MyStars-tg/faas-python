"""Synchronous :class:`MyStarsClient`."""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from typing import Any, Callable

import httpx

from . import _transport as T
from ._transport import PRODUCTION_BASE_URL, RetryPolicy, _Request
from ._validate import assert_order_type, assert_premium_months, assert_stars_quantity, canonical_username
from .errors import MyStarsError, MyStarsValidationError
from .models import (
    CreateOrderResult,
    CurrencyInfo,
    Order,
    OrdersPage,
    PricingQuote,
    PricingQuoteBatch,
    Product,
    RecipientCheck,
    is_terminal,
)
from .reconcile import reconcile as _reconcile

__all__ = ["MyStarsClient", "PRODUCTION_BASE_URL"]


class MyStarsClient:
    """Synchronous client for the MyStars FaaS ``/v1`` API.

    Wraps every public endpoint (pricing, recipient check, order create/get/cancel/list,
    catalog) with typed models, ``Decimal``-exact money, a typed error taxonomy, automatic
    idempotency-key generation, and idempotency-safe retries (network/timeout, 5xx, and the
    general 429 — honouring ``Retry-After``). Use :meth:`production` to
    construct one, and use it as a context manager (``with MyStarsClient.production(key) as c``)
    so the underlying ``httpx`` connection pool is closed.

    For the asyncio equivalent see :class:`~mystars_faas.AsyncMyStarsClient`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = PRODUCTION_BASE_URL,
        timeout: float = 15.0,
        retry: RetryPolicy | None = None,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
        idempotency_key_factory: Callable[[], str] = T.new_idempotency_key,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        """Construct a client.

        Args:
            api_key: Tenant API key, sent as the ``X-Api-Key`` header. Required (non-empty).
            base_url: API base URL including the ``/v1`` suffix. Defaults to production;
                prefer the :meth:`production` constructor.
            timeout: Per-request timeout in seconds (passed to ``httpx``).
            retry: Retry/backoff policy. Defaults to :class:`~mystars_faas.RetryPolicy`
                (3 retries, exponential backoff with jitter, respects ``Retry-After``).
            user_agent: Override the ``User-Agent`` header. Defaults to
                ``mystars-faas-python/<version>``.
            transport: An ``httpx.BaseTransport`` to inject (used by the test suite to mock
                the network); normally left ``None``.
            idempotency_key_factory: Callable that mints the ``Idempotency-Key`` for
                :meth:`create_order` when the caller doesn't pass one. Defaults to a UUID4.
            sleep: Injectable blocking sleep used between retries and polls (test seam).
            rand: Injectable ``[0, 1)`` random source for jitter (test seam).

        Raises:
            ValueError: If ``api_key`` is empty.
        """
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url
        self._retry = retry or RetryPolicy()
        self._user_agent = user_agent or T.default_user_agent()
        self._idem = idempotency_key_factory
        self._sleep = sleep
        self._rand = rand
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @classmethod
    def production(cls, api_key: str, **kw: Any) -> MyStarsClient:
        """Construct a client pointed at the production edge (``https://api.mystars.tg/v1``).

        Args:
            api_key: Tenant API key.
            **kw: Any other :meth:`__init__` keyword argument.

        Returns:
            A configured :class:`MyStarsClient`.
        """
        return cls(api_key, base_url=PRODUCTION_BASE_URL, **kw)

    def close(self) -> None:
        """Close the underlying ``httpx`` client and its connection pool."""
        self._client.close()

    def __enter__(self) -> MyStarsClient:
        """Enter the context manager, returning ``self``."""
        return self

    def __exit__(self, *exc: Any) -> None:
        """Exit the context manager, calling :meth:`close`."""
        self.close()

    # ─── transport ────────────────────────────────────────────────────────────

    def _request(self, req: _Request) -> tuple[Any, int]:
        idempotent = T.is_idempotent(req)
        attempt = 0
        while True:
            err: MyStarsError | None = None
            status: int | None = None
            headers: httpx.Headers | None = None
            body: bytes | None = None
            try:
                with self._client.stream(
                    req.method,
                    T.build_url(self._base_url, req.path),
                    params=T.clean_params(req.params),
                    json=req.json_body,
                    headers=T.headers_for(self._api_key, req.idempotency_key, req.json_body is not None, self._user_agent),
                ) as resp:
                    status = resp.status_code
                    headers = resp.headers
                    body = T.read_bounded_bytes(resp.iter_bytes(), status)
            except httpx.HTTPError as exc:
                err = T.map_httpx_error(exc)
            except MyStarsError as e:  # response_too_large from the bounded reader
                err = e
            if err is None:
                assert status is not None and headers is not None and body is not None
                try:
                    data, _ = T.parse_response(status, headers, body)
                    return data, status
                except MyStarsError as e:
                    err = e
            assert err is not None
            if attempt >= self._retry.max_retries or not T.should_retry(err, idempotent):
                raise err
            self._sleep(T.backoff_delay(attempt, err, self._retry, self._rand()))
            attempt += 1

    # ─── catalog ──────────────────────────────────────────────────────────────

    def list_currencies(self) -> list[CurrencyInfo]:
        """List the accepted payment currencies (``GET /v1/currencies``).

        Returns:
            A list of :class:`~mystars_faas.CurrencyInfo` (e.g. ``ton``, ``usdt_ton``).

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = self._request(_Request("GET", "/currencies"))
        return [CurrencyInfo.from_dict(c) for c in data["currencies"]]

    def list_products(self) -> list[Product]:
        """List the product catalog (``GET /v1/products``) as price-free metadata.

        Returns:
            A list of :class:`~mystars_faas.Product` describing each buyable type and its
            allowed shape (``stars`` is a continuous range; ``premium`` is a fixed set).

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = self._request(_Request("GET", "/products"))
        return [Product.from_dict(p) for p in data["products"]]

    # ─── pricing / recipients ───────────────────────────────────────────────────

    def get_pricing(self, *, type: str, quantity: int | None = None, months: int | None = None, payment_currency: str | None = None) -> PricingQuote:
        """Quote a wholesale price (``GET /v1/pricing``).

        Args:
            type: ``"stars"`` or ``"premium"``.
            quantity: Star count when ``type="stars"``; must be in
                ``[STARS_MIN_QUANTITY, STARS_MAX_QUANTITY]`` (50–1,000,000). Ignored for premium.
            months: Premium duration when ``type="premium"``; one of ``PREMIUM_MONTHS``
                (3, 6, or 12). Ignored for stars.
            payment_currency: ``"ton"`` or ``"usdt_ton"``. ``None`` lets the server default.

        Returns:
            A :class:`~mystars_faas.PricingQuote` with the ``Decimal`` ``amount``, currency,
            optional itemised ``fee`` (``usdt_ton`` only), and validity window.

        Raises:
            MyStarsValidationError: If ``type`` is invalid, or the required ``quantity`` /
                ``months`` for the type is missing or out of range (checked client-side).
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        assert_order_type(type)
        params: dict[str, Any] = {"type": type, "payment_currency": payment_currency}
        if type == "stars":
            assert_stars_quantity(quantity)  # type: ignore[arg-type]
            params["quantity"] = quantity
        else:
            assert_premium_months(months)  # type: ignore[arg-type]
            params["months"] = months
        data, _ = self._request(_Request("GET", "/pricing", params=params))
        return PricingQuote.from_dict(data)

    def get_pricing_batch(self, *, quantities: list[int], payment_currency: str | None = None) -> PricingQuoteBatch:
        """Quote up to 200 Stars quantities in ONE request (``GET /v1/pricing/batch``).

        Built for storefronts refreshing preview prices for a whole pack catalog:
        one batch call consumes a single unit of the request/probe budget however
        many quantities it quotes. Entries carry the same ``amount`` + ``fee`` as
        :meth:`get_pricing` for that quantity; the server dedupes and sorts the
        quantities ascending.

        Args:
            quantities: Star counts to quote — each in ``[STARS_MIN_QUANTITY,
                STARS_MAX_QUANTITY]`` (50–1,000,000), at most 200 values.
            payment_currency: ``"ton"`` or ``"usdt_ton"``. ``None`` lets the server default.

        Returns:
            A :class:`~mystars_faas.PricingQuoteBatch` with one entry per quantity.

        Raises:
            MyStarsValidationError: If the list is empty/oversized or a quantity is
                out of range (checked client-side, before any request).
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        if not quantities:
            raise MyStarsValidationError("quantities must be a non-empty list")
        if len(quantities) > 200:
            raise MyStarsValidationError(f"quantities accepts at most 200 values, got {len(quantities)}")
        for quantity in quantities:
            assert_stars_quantity(quantity)
        params: dict[str, Any] = {
            "type": "stars",
            "quantities": ",".join(str(q) for q in quantities),
            "payment_currency": payment_currency,
        }
        data, _ = self._request(_Request("GET", "/pricing/batch", params=params))
        return PricingQuoteBatch.from_dict(data)

    def check_recipient(self, username: str, *, type: str, months: int | None = None) -> RecipientCheck:
        """Resolve a Telegram ``@username`` and check it can receive the item
        (``POST /v1/recipients/check``).

        Call this BEFORE :meth:`create_order` to surface a structured ``reason`` (e.g.
        ``"already_subscribed"`` for an active-Premium recipient) — the 422 raised by
        :meth:`create_order` only carries the buyer-facing message, not the structured reason.

        Args:
            username: Recipient handle; a leading ``@`` is allowed and is stripped/lowercased
                client-side.
            type: ``"stars"`` or ``"premium"`` — Premium eligibility differs from Stars.
            months: Optional Premium duration (only sent for ``type="premium"``); validated
                against ``PREMIUM_MONTHS`` when provided.

        Returns:
            A :class:`~mystars_faas.RecipientCheck` (``resolved``, ``eligible``,
            ``recipient_name``, ``reason``, ``telegram_message``).

        Raises:
            MyStarsValidationError: If ``type`` or the username is invalid (client-side).
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        assert_order_type(type)
        body: dict[str, Any] = {"type": type, "recipient": {"username": canonical_username(username)}}
        if type == "premium" and months is not None:
            assert_premium_months(months)
            body["months"] = months
        data, _ = self._request(_Request("POST", "/recipients/check", json_body=body, idempotent=True))
        return RecipientCheck.from_dict(data)

    # ─── orders ──────────────────────────────────────────────────────────────

    def create_order(
        self,
        *,
        type: str,
        recipient: str,
        quantity: int | None = None,
        months: int | None = None,
        payment_currency: str | None = None,
        callback_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> CreateOrderResult:
        """Create an order (``POST /v1/orders``) and get back payment instructions.

        An ``Idempotency-Key`` is always sent: if you don't pass one, a UUID4 is minted and
        reused across this call's transport-level retries. To make a *fresh* call idempotent
        against a previous failed attempt, pass the SAME ``idempotency_key`` again — otherwise
        a new key is minted and the server treats it as a new order. The key is NOT surfaced on
        the returned result or on raised errors; track it yourself if you need cross-call replay.

        Args:
            type: ``"stars"`` or ``"premium"``.
            recipient: Recipient ``@username`` (leading ``@`` allowed; canonicalised client-side).
            quantity: Star count when ``type="stars"`` (50–1,000,000). Ignored for premium.
            months: Premium duration when ``type="premium"`` (3, 6, or 12). Ignored for stars.
            payment_currency: ``"ton"`` or ``"usdt_ton"``; omitted from the body when ``None``.
            callback_url: Optional HTTPS URL the FaaS POSTs the terminal webhook to. Verify it
                with :class:`~mystars_faas.WebhookVerifier`.
            idempotency_key: Optional explicit key; defaults to a freshly minted UUID4.

        Returns:
            A :class:`~mystars_faas.CreateOrderResult` carrying the order id, status, the
            :class:`~mystars_faas.PaymentInstruction` to pay, ``expires_at``, and
            ``replayed`` (``True`` when the server replayed a prior identical create — HTTP 200
            rather than 201).

        Raises:
            MyStarsValidationError: If ``type`` / ``recipient`` / the type's amount is invalid
                (client-side).
            RecipientIneligibleError: 422 — the recipient cannot receive the item; no order
                was created (call :meth:`check_recipient` for the structured reason).
            IdempotencyConflictError: 409 — the same key was reused with a different body.
            MyStarsAPIError: On any other non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        assert_order_type(type)
        body: dict[str, Any] = {"type": type, "recipient": {"username": canonical_username(recipient)}}
        if type == "stars":
            assert_stars_quantity(quantity)  # type: ignore[arg-type]
            body["quantity"] = quantity
        else:
            assert_premium_months(months)  # type: ignore[arg-type]
            body["months"] = months
        if payment_currency is not None:
            body["payment_currency"] = payment_currency
        if callback_url is not None:
            body["callback_url"] = callback_url
        key = idempotency_key or self._idem()
        data, status = self._request(_Request("POST", "/orders", json_body=body, idempotency_key=key))
        return CreateOrderResult.from_dict(data, replayed=status == 200)

    def get_order(self, order_id: str) -> Order:
        """Fetch one order's current state (``GET /v1/orders/{id}``).

        On an ``awaiting_payment``, in-window order the server may run an on-demand payment
        detection before replying, so polling this is a reliable way to observe progress.

        Args:
            order_id: The order UUID (also the on-chain payment memo).

        Returns:
            The :class:`~mystars_faas.Order`.

        Raises:
            NotFoundError: 404 — no such order for this tenant.
            MyStarsAPIError: On any other non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = self._request(_Request("GET", f"/orders/{order_id}"))
        return Order.from_dict(data)

    def cancel_order(self, order_id: str) -> dict[str, str]:
        """Cancel an ``awaiting_payment`` order (``POST /v1/orders/{id}/cancel``).

        Args:
            order_id: The order UUID.

        Returns:
            A ``{"order_id", "status"}`` dict; tolerates an empty-body 2xx by falling back to
            the requested id and ``"cancelled"``.

        Raises:
            OrderNotCancellableError: 409 — the order is past ``awaiting_payment``.
            NotFoundError: 404 — no such order for this tenant.
            MyStarsAPIError: On any other non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = self._request(_Request("POST", f"/orders/{order_id}/cancel", idempotent=True))
        return T.cancel_result(order_id, data)

    def list_orders(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> OrdersPage:
        """List orders newest-first, one keyset page (``GET /v1/orders``).

        Args:
            status: Optional status filter (one of ``ORDER_STATUSES``).
            limit: Optional page size (server-clamped).
            cursor: Opaque keyset cursor from a prior page's ``next_cursor``.

        Returns:
            An :class:`~mystars_faas.OrdersPage` (the page's ``orders`` + ``next_cursor``;
            ``next_cursor`` is ``None`` on the last page). Prefer :meth:`iter_orders` to walk
            every page automatically.

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = self._request(_Request("GET", "/orders", params={"status": status, "limit": limit, "cursor": cursor}))
        return OrdersPage.from_dict(data)

    def iter_orders(self, *, status: str | None = None, page_size: int | None = None) -> Iterator[Order]:
        """Iterate every order across all pages, newest-first (auto keyset pagination).

        Args:
            status: Optional status filter (one of ``ORDER_STATUSES``).
            page_size: Optional per-page size passed as ``limit``.

        Yields:
            Each :class:`~mystars_faas.Order` in turn, transparently following ``next_cursor``.

        Raises:
            MyStarsAPIError: On any non-2xx response while fetching a page.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        cursor: str | None = None
        while True:
            page = self.list_orders(status=status, limit=page_size, cursor=cursor)
            yield from page.orders
            if not page.next_cursor:
                break
            cursor = page.next_cursor

    # ─── tracking ──────────────────────────────────────────────────────────────

    def wait_for_order(
        self,
        order_id: str,
        *,
        until: Callable[[Order], bool] | None = None,
        timeout: float = 1800.0,
        poll_interval: float = 2.0,
        max_poll_interval: float = 15.0,
        backoff: float = 1.5,
        on_update: Callable[[Order], None] | None = None,
    ) -> Order:
        """Poll an order until it reaches a terminal state (or ``until`` is satisfied).

        Uses decorrelated-jitter backoff between polls (``poll_interval`` growing by ``backoff``
        up to ``max_poll_interval``), so it is gentle on the API and safe to leave running.
        Prefer the webhook for production; this is the fallback when you can't receive callbacks.

        Args:
            order_id: The order UUID.
            until: Optional predicate; stop when it returns ``True``. Defaults to
                :func:`~mystars_faas.is_terminal` (``delivered``/``failed``/``reversed``/
                ``expired``/``cancelled``).
            timeout: Overall budget in seconds before giving up (default 1800 = 30 min).
            poll_interval: Initial seconds between polls (default 2.0).
            max_poll_interval: Cap on the polling interval (default 15.0).
            backoff: Multiplier applied to the interval each poll (default 1.5).
            on_update: Optional callback invoked once per *observed status change* with the
                latest :class:`~mystars_faas.Order`.

        Returns:
            The :class:`~mystars_faas.Order` once ``until``/terminal is satisfied.

        Raises:
            OrderWaitTimeout: If ``timeout`` elapses first (``.last_order`` holds the last poll).
            MyStarsAPIError: On any non-2xx response while polling.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        from .errors import OrderWaitTimeout

        done = until or (lambda o: is_terminal(o.status))
        deadline = time.monotonic() + timeout
        interval = poll_interval
        last_status: str | None = None
        while True:
            order = self.get_order(order_id)
            if order.status != last_status:
                last_status = order.status
                if on_update:
                    on_update(order)
            if done(order):
                return order
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OrderWaitTimeout(order)
            wait = min(interval, max_poll_interval)
            self._sleep(min(wait * (0.5 + 0.5 * self._rand()), remaining))
            interval = min(interval * backoff, max_poll_interval)

    def reconcile(
        self,
        *,
        is_known: Callable[[Order], bool],
        status: str | None = None,
        since: str | None = None,
        page_size: int | None = None,
        on_missed: Callable[[Order], None] | None = None,
    ) -> list[Order]:
        """Find terminal orders your store missed (a safety net for dropped webhooks).

        Walks orders newest-first and returns the TERMINAL ones for which ``is_known`` returns
        ``False`` — i.e. transitions your system never recorded. Run it periodically.

        Args:
            is_known: Predicate; return ``True`` if you've already recorded this order's
                terminal state. Orders it returns ``False`` for are reported as missed.
            status: Optional status filter to narrow the scan.
            since: Optional ISO-8601 timestamp; stop walking once orders older than this are
                reached (newest-first short-circuit).
            page_size: Optional per-page size.
            on_missed: Optional callback invoked for each missed order as it is found.

        Returns:
            The list of terminal :class:`~mystars_faas.Order` objects not yet known to you.

        Raises:
            ValueError: If ``since`` is not a parseable ISO-8601 timestamp.
            MyStarsAPIError: On any non-2xx response while scanning.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        return _reconcile(self, is_known=is_known, status=status, since=since, page_size=page_size, on_missed=on_missed)
