"""``mystars-faas`` command-line tool.

Auth via ``--api-key`` or ``MYSTARS_API_KEY``. Every command prints JSON.
Holds no keys, moves no funds.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from decimal import Decimal
from typing import Any, Callable

from ._version import __version__
from .client import MyStarsClient
from .models import Order
from .payment import build_payment_request
from .webhook import verify_webhook_signature


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _print(out: Callable[[str], None], value: Any) -> None:
    out(json.dumps(_jsonable(value), indent=2))


def build_parser() -> argparse.ArgumentParser:
    """Build the ``mystars-faas`` argument parser (global flags + every subcommand).

    Returns:
        An :class:`argparse.ArgumentParser` with the ``pricing``, ``products``, ``currencies``,
        ``recipient-check``, ``orders-create``, ``orders-get``, ``orders-ls``, ``orders-cancel``,
        ``watch``, and ``webhook-verify`` subcommands.
    """
    p = argparse.ArgumentParser(prog="mystars-faas", description="CLI for the MyStars FaaS API.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--api-key", help="tenant API key (or set MYSTARS_API_KEY)")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("pricing", help="quote a price")
    pr.add_argument("--type", required=True, choices=["stars", "premium"])
    pr.add_argument("--quantity", type=int)
    pr.add_argument("--months", type=int)
    pr.add_argument("--currency", choices=["ton", "usdt_ton"])

    sub.add_parser("products", help="list the product catalog")
    sub.add_parser("currencies", help="list payment currencies")

    rc = sub.add_parser("recipient-check", help="resolve a @username and check eligibility")
    rc.add_argument("username")
    rc.add_argument("--type", required=True, choices=["stars", "premium"])
    rc.add_argument("--months", type=int)

    oc = sub.add_parser("orders-create", help="create an order")
    oc.add_argument("--type", required=True, choices=["stars", "premium"])
    oc.add_argument("--recipient", required=True)
    oc.add_argument("--quantity", type=int)
    oc.add_argument("--months", type=int)
    oc.add_argument("--currency", choices=["ton", "usdt_ton"])
    oc.add_argument("--callback")
    oc.add_argument("--pay", action="store_true", help="also print a payable request")

    og = sub.add_parser("orders-get", help="get one order")
    og.add_argument("id")

    ol = sub.add_parser("orders-ls", help="list orders")
    ol.add_argument("--status")
    ol.add_argument("--limit", type=int)

    ocl = sub.add_parser("orders-cancel", help="cancel an order")
    ocl.add_argument("id")

    w = sub.add_parser("watch", help="poll an order until it is terminal")
    w.add_argument("id")

    wv = sub.add_parser("webhook-verify", help="verify an X-Faas-Signature over a raw body")
    wv.add_argument(
        "--secret",
        help=(
            "tenant webhook secret (or set MYSTARS_WEBHOOK_SECRET, which is preferred). "
            "WARNING: a --secret on the command line is visible in the process list "
            "(`ps`) and shell history — prefer the env var."
        ),
    )
    wv.add_argument("--body", required=True)
    wv.add_argument("--signature", required=True)
    return p


def dispatch(ns: argparse.Namespace, *, client_factory: Callable[[], MyStarsClient], out: Callable[[str], None]) -> int:
    """Run a parsed command, printing its JSON result.

    ``webhook-verify`` runs offline (no client). Every other command lazily builds a client via
    ``client_factory``. ``client_factory`` and ``out`` are injected so the test suite can drive a
    mocked client and capture output.

    Args:
        ns: The parsed argparse namespace.
        client_factory: Zero-arg factory that returns a :class:`MyStarsClient`.
        out: Sink for JSON output lines (e.g. ``print``).

    Returns:
        A process exit code (``0`` on success, non-zero on a usage/validation problem).
    """
    cmd = ns.command
    if cmd == "webhook-verify":  # offline, no client
        # Prefer the env var: a --secret on argv leaks via the process list.
        secret = os.environ.get("MYSTARS_WEBHOOK_SECRET") or ns.secret
        if not secret:
            sys.stderr.write("error: a webhook secret is required (--secret or MYSTARS_WEBHOOK_SECRET)\n")
            return 1
        _print(out, {"valid": verify_webhook_signature(ns.body, ns.signature, secret)})
        return 0

    client = client_factory()
    if cmd == "pricing":
        _print(out, client.get_pricing(type=ns.type, quantity=ns.quantity, months=ns.months, payment_currency=ns.currency))
    elif cmd == "products":
        _print(out, client.list_products())
    elif cmd == "currencies":
        _print(out, client.list_currencies())
    elif cmd == "recipient-check":
        _print(out, client.check_recipient(ns.username, type=ns.type, months=ns.months))
    elif cmd == "orders-create":
        order = client.create_order(type=ns.type, recipient=ns.recipient, quantity=ns.quantity, months=ns.months, payment_currency=ns.currency, callback_url=ns.callback)
        if ns.pay:
            _print(out, {"order": order, "payment_request": build_payment_request(order.payment)})
        else:
            _print(out, order)
    elif cmd == "orders-get":
        _print(out, client.get_order(ns.id))
    elif cmd == "orders-ls":
        _print(out, client.list_orders(status=ns.status, limit=ns.limit))
    elif cmd == "orders-cancel":
        _print(out, client.cancel_order(ns.id))
    elif cmd == "watch":
        def _emit(o: Order) -> None:
            sys.stderr.write(f"status: {o.status}\n")

        _print(out, client.wait_for_order(ns.id, on_update=_emit))
    else:  # pragma: no cover
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — parse args, resolve the API key, and dispatch.

    The API key comes from ``--api-key`` or ``MYSTARS_API_KEY``. Any raised error is printed
    to stderr and turned into exit code 1.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The process exit code.
    """
    ns = build_parser().parse_args(argv)

    def make_client() -> MyStarsClient:
        api_key = ns.api_key or os.environ.get("MYSTARS_API_KEY")
        if not api_key:
            sys.stderr.write("error: an API key is required (--api-key or MYSTARS_API_KEY)\n")
            raise SystemExit(1)
        return MyStarsClient.production(api_key)

    try:
        return dispatch(ns, client_factory=make_client, out=print)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
