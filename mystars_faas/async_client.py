"""Asynchronous :class:`AsyncMyStarsClient` (httpx.AsyncClient)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable
from typing import Any, Callable

import httpx

from . import _transport as T
from ._transport import PRODUCTION_BASE_URL, RetryPolicy, _Request
from ._validate import assert_order_type, assert_premium_months, assert_stars_quantity, canonical_username
from .errors import MyStarsError, MyStarsValidationError, OrderWaitTimeout
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

__all__ = ["AsyncMyStarsClient"]


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class AsyncMyStarsClient:
    """Asyncio client for the MyStars FaaS ``/v1`` API (backed by ``httpx.AsyncClient``).

    Method-for-method the async twin of :class:`~mystars_faas.MyStarsClient` — same typed
    models, ``Decimal`` money, error taxonomy, idempotency, and retry semantics — with
    ``await``\\ able calls, an :meth:`aiter_orders` async iterator, and :meth:`await_order`
    (the async ``wait_for_order``). Use as an async context manager
    (``async with AsyncMyStarsClient.production(key) as c``) so the pool is closed.

    Note: there is no async ``reconcile`` method — the top-level
    :func:`~mystars_faas.reconcile` helper drives the *sync* client. To reconcile from async
    code, iterate :meth:`aiter_orders` and apply your own ``is_known`` filter.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = PRODUCTION_BASE_URL,
        timeout: float = 15.0,
        retry: RetryPolicy | None = None,
        user_agent: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        idempotency_key_factory: Callable[[], str] = T.new_idempotency_key,
        sleep: Callable[[float], Awaitable[None]] = _async_sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        """Construct an async client.

        Args:
            api_key: Tenant API key, sent as ``X-Api-Key``. Required (non-empty).
            base_url: API base URL including ``/v1``. Prefer :meth:`production`.
            timeout: Per-request timeout in seconds.
            retry: Retry/backoff policy; defaults to :class:`~mystars_faas.RetryPolicy`.
            user_agent: Override the ``User-Agent``; defaults to ``mystars-faas-python/<version>``.
            transport: An ``httpx.AsyncBaseTransport`` to inject (test seam); normally ``None``.
            idempotency_key_factory: Mints the ``Idempotency-Key`` for :meth:`create_order`
                when the caller doesn't pass one. Defaults to a UUID4.
            sleep: Injectable awaitable sleep used between retries/polls (test seam).
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
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    @classmethod
    def production(cls, api_key: str, **kw: Any) -> AsyncMyStarsClient:
        """Construct an async client pointed at production (``https://api.mystars.tg/v1``).

        Args:
            api_key: Tenant API key.
            **kw: Any other :meth:`__init__` keyword argument.

        Returns:
            A configured :class:`AsyncMyStarsClient`.
        """
        return cls(api_key, base_url=PRODUCTION_BASE_URL, **kw)

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` and its connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncMyStarsClient:
        """Enter the async context manager, returning ``self``."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit the async context manager, calling :meth:`aclose`."""
        await self.aclose()

    async def _request(self, req: _Request) -> tuple[Any, int]:
        idempotent = T.is_idempotent(req)
        attempt = 0
        while True:
            err: MyStarsError | None = None
            status: int | None = None
            headers: httpx.Headers | None = None
            body: bytes | None = None
            try:
                async with self._client.stream(
                    req.method,
                    T.build_url(self._base_url, req.path),
                    params=T.clean_params(req.params),
                    json=req.json_body,
                    headers=T.headers_for(self._api_key, req.idempotency_key, req.json_body is not None, self._user_agent),
                ) as resp:
                    status = resp.status_code
                    headers = resp.headers
                    body = await T.aread_bounded_bytes(resp.aiter_bytes(), status)
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
            await self._sleep(T.backoff_delay(attempt, err, self._retry, self._rand()))
            attempt += 1

    async def list_currencies(self) -> list[CurrencyInfo]:
        """List the accepted payment currencies (``GET /v1/currencies``). Async; see
        :meth:`MyStarsClient.list_currencies <mystars_faas.MyStarsClient.list_currencies>`.

        Returns:
            A list of :class:`~mystars_faas.CurrencyInfo`.

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = await self._request(_Request("GET", "/currencies"))
        return [CurrencyInfo.from_dict(c) for c in data["currencies"]]

    async def list_products(self) -> list[Product]:
        """List the product catalog (``GET /v1/products``). Async; see
        :meth:`MyStarsClient.list_products <mystars_faas.MyStarsClient.list_products>`.

        Returns:
            A list of :class:`~mystars_faas.Product`.

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = await self._request(_Request("GET", "/products"))
        return [Product.from_dict(p) for p in data["products"]]

    async def get_pricing(self, *, type: str, quantity: int | None = None, months: int | None = None, payment_currency: str | None = None) -> PricingQuote:
        """Quote a wholesale price (``GET /v1/pricing``). Async; see
        :meth:`MyStarsClient.get_pricing <mystars_faas.MyStarsClient.get_pricing>` for the
        full argument contract.

        Args:
            type: ``"stars"`` or ``"premium"``.
            quantity: Star count (50–1,000,000) when ``type="stars"``.
            months: Premium duration (3/6/12) when ``type="premium"``.
            payment_currency: ``"ton"`` or ``"usdt_ton"`` (or ``None`` for the server default).

        Returns:
            A :class:`~mystars_faas.PricingQuote`.

        Raises:
            MyStarsValidationError: If the type or its required amount is invalid (client-side).
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
        data, _ = await self._request(_Request("GET", "/pricing", params=params))
        return PricingQuote.from_dict(data)

    async def get_pricing_batch(self, *, quantities: list[int], payment_currency: str | None = None) -> PricingQuoteBatch:
        """Quote up to 200 Stars quantities in ONE request (``GET /v1/pricing/batch``).
        Async; see :meth:`MyStarsClient.get_pricing_batch
        <mystars_faas.MyStarsClient.get_pricing_batch>` for the full contract.

        Args:
            quantities: Star counts to quote — each 50–1,000,000, at most 200 values.
            payment_currency: ``"ton"`` or ``"usdt_ton"`` (or ``None`` for the server default).

        Returns:
            A :class:`~mystars_faas.PricingQuoteBatch`.

        Raises:
            MyStarsValidationError: If the list is empty/oversized or a quantity is out of range.
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
        data, _ = await self._request(_Request("GET", "/pricing/batch", params=params))
        return PricingQuoteBatch.from_dict(data)

    async def check_recipient(self, username: str, *, type: str, months: int | None = None) -> RecipientCheck:
        """Resolve a ``@username`` and check eligibility (``POST /v1/recipients/check``). Async;
        see :meth:`MyStarsClient.check_recipient <mystars_faas.MyStarsClient.check_recipient>`.

        Args:
            username: Recipient handle (leading ``@`` allowed; canonicalised client-side).
            type: ``"stars"`` or ``"premium"``.
            months: Optional Premium duration (only sent for ``type="premium"``).

        Returns:
            A :class:`~mystars_faas.RecipientCheck`.

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
        data, _ = await self._request(_Request("POST", "/recipients/check", json_body=body, idempotent=True))
        return RecipientCheck.from_dict(data)

    async def create_order(
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
        """Create an order (``POST /v1/orders``). Async; see
        :meth:`MyStarsClient.create_order <mystars_faas.MyStarsClient.create_order>` for the
        idempotency-key contract (a key is always sent; reused across this call's retries; pass
        the same key explicitly to make a fresh call idempotent against a prior attempt).

        Args:
            type: ``"stars"`` or ``"premium"``.
            recipient: Recipient ``@username`` (canonicalised client-side).
            quantity: Star count (50–1,000,000) when ``type="stars"``.
            months: Premium duration (3/6/12) when ``type="premium"``.
            payment_currency: ``"ton"`` or ``"usdt_ton"``; omitted when ``None``.
            callback_url: Optional HTTPS terminal-webhook URL.
            idempotency_key: Optional explicit key; defaults to a fresh UUID4.

        Returns:
            A :class:`~mystars_faas.CreateOrderResult` (``replayed`` is ``True`` on an
            idempotent replay — HTTP 200 vs 201).

        Raises:
            MyStarsValidationError: If the type/recipient/amount is invalid (client-side).
            RecipientIneligibleError: 422 — recipient cannot receive the item; no order created.
            IdempotencyConflictError: 409 — key reused with a different body.
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
        data, status = await self._request(_Request("POST", "/orders", json_body=body, idempotency_key=key))
        return CreateOrderResult.from_dict(data, replayed=status == 200)

    async def get_order(self, order_id: str) -> Order:
        """Fetch one order (``GET /v1/orders/{id}``). Async; see
        :meth:`MyStarsClient.get_order <mystars_faas.MyStarsClient.get_order>`.

        Args:
            order_id: The order UUID.

        Returns:
            The :class:`~mystars_faas.Order`.

        Raises:
            NotFoundError: 404 — no such order for this tenant.
            MyStarsAPIError: On any other non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = await self._request(_Request("GET", f"/orders/{order_id}"))
        return Order.from_dict(data)

    async def cancel_order(self, order_id: str) -> dict[str, str]:
        """Cancel an ``awaiting_payment`` order (``POST /v1/orders/{id}/cancel``). Async; see
        :meth:`MyStarsClient.cancel_order <mystars_faas.MyStarsClient.cancel_order>`.

        Args:
            order_id: The order UUID.

        Returns:
            A ``{"order_id", "status"}`` dict (tolerates an empty-body 2xx).

        Raises:
            OrderNotCancellableError: 409 — the order is past ``awaiting_payment``.
            NotFoundError: 404 — no such order for this tenant.
            MyStarsAPIError: On any other non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = await self._request(_Request("POST", f"/orders/{order_id}/cancel", idempotent=True))
        return T.cancel_result(order_id, data)

    async def list_orders(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> OrdersPage:
        """List one keyset page of orders (``GET /v1/orders``). Async; see
        :meth:`MyStarsClient.list_orders <mystars_faas.MyStarsClient.list_orders>`. Prefer
        :meth:`aiter_orders` to walk all pages.

        Args:
            status: Optional status filter (one of ``ORDER_STATUSES``).
            limit: Optional page size.
            cursor: Opaque keyset cursor from a prior ``next_cursor``.

        Returns:
            An :class:`~mystars_faas.OrdersPage`.

        Raises:
            MyStarsAPIError: On any non-2xx response.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        data, _ = await self._request(_Request("GET", "/orders", params={"status": status, "limit": limit, "cursor": cursor}))
        return OrdersPage.from_dict(data)

    async def aiter_orders(self, *, status: str | None = None, page_size: int | None = None) -> AsyncIterator[Order]:
        """Async-iterate every order across all pages, newest-first (auto keyset pagination).

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
            page = await self.list_orders(status=status, limit=page_size, cursor=cursor)
            for order in page.orders:
                yield order
            if not page.next_cursor:
                break
            cursor = page.next_cursor

    async def await_order(
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
        """Await an order until terminal (or ``until`` is satisfied). The async twin of
        :meth:`MyStarsClient.wait_for_order <mystars_faas.MyStarsClient.wait_for_order>` —
        same decorrelated-jitter backoff and ``on_update`` (fired once per status change).

        Args:
            order_id: The order UUID.
            until: Optional stop predicate; defaults to :func:`~mystars_faas.is_terminal`.
            timeout: Overall budget in seconds (default 1800 = 30 min).
            poll_interval: Initial seconds between polls (default 2.0).
            max_poll_interval: Cap on the polling interval (default 15.0).
            backoff: Multiplier applied to the interval each poll (default 1.5).
            on_update: Optional callback invoked once per observed status change. It is called
                synchronously (not awaited).

        Returns:
            The :class:`~mystars_faas.Order` once ``until``/terminal is satisfied.

        Raises:
            OrderWaitTimeout: If ``timeout`` elapses first (``.last_order`` holds the last poll).
            MyStarsAPIError: On any non-2xx response while polling.
            MyStarsTransportError: On a network/timeout failure with no response.
        """
        loop = asyncio.get_running_loop()
        done = until or (lambda o: is_terminal(o.status))
        deadline = loop.time() + timeout
        interval = poll_interval
        last_status: str | None = None
        while True:
            order = await self.get_order(order_id)
            if order.status != last_status:
                last_status = order.status
                if on_update:
                    on_update(order)
            if done(order):
                return order
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OrderWaitTimeout(order)
            wait = min(interval, max_poll_interval)
            await self._sleep(min(wait * (0.5 + 0.5 * self._rand()), remaining))
            interval = min(interval * backoff, max_poll_interval)
