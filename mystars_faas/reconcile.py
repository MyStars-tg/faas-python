"""Reconciliation — catch terminal transitions a dropped webhook missed."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Callable, Protocol

from .models import Order, is_terminal


def _parse_iso(value: str) -> datetime:
    # Python 3.9/3.10 fromisoformat doesn't accept a trailing 'Z'.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class _ReconcileClient(Protocol):
    def iter_orders(self, *, status: str | None = ..., page_size: int | None = ...) -> Iterator[Order]: ...


def reconcile(
    client: _ReconcileClient,
    *,
    is_known: Callable[[Order], bool],
    status: str | None = None,
    since: str | None = None,
    page_size: int | None = None,
    on_missed: Callable[[Order], None] | None = None,
) -> list[Order]:
    """Walk orders newest-first and return TERMINAL ones your store hasn't recorded.

    A safety net for dropped webhooks. Drives the sync iterator
    :meth:`MyStarsClient.iter_orders <mystars_faas.MyStarsClient.iter_orders>`; the sync client
    exposes this as :meth:`MyStarsClient.reconcile <mystars_faas.MyStarsClient.reconcile>`. There
    is no async variant — from async code, iterate ``aiter_orders`` and apply ``is_known`` yourself.

    Args:
        client: Any object with an ``iter_orders(status=, page_size=)`` iterator (a
            :class:`~mystars_faas.MyStarsClient`).
        is_known: Predicate; return ``True`` if you've already recorded this order's terminal
            state. Orders it returns ``False`` for are collected as missed.
        status: Optional status filter to narrow the scan.
        since: Optional ISO-8601 cutoff; stop once orders older than this are reached
            (newest-first short-circuit on ``created_at``).
        page_size: Optional per-page size passed through to ``iter_orders``.
        on_missed: Optional callback invoked for each missed order as it is found.

    Returns:
        The list of terminal :class:`~mystars_faas.Order` objects not yet known to you.

    Raises:
        ValueError: If ``since`` is not a parseable ISO-8601 timestamp.
        MyStarsAPIError: On any non-2xx response while scanning pages.
    """
    since_dt = _parse_iso(since) if since else None
    missed: list[Order] = []
    for order in client.iter_orders(status=status, page_size=page_size):
        if since_dt is not None and _parse_iso(order.created_at) < since_dt:
            break
        if not is_terminal(order.status):
            continue
        if not is_known(order):
            missed.append(order)
            if on_missed:
                on_missed(order)
    return missed
