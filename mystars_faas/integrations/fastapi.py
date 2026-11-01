"""FastAPI webhook route factory. Requires the ``[fastapi]`` extra.

Verifies the ``X-Faas-Signature`` over the RAW body, parses the event, hands it to
``on_event``, and replies 200 fast. Dedup on ``event.order_id`` is your job.

    from fastapi import FastAPI
    from mystars_faas.integrations.fastapi import faas_webhook_route

    app = FastAPI()
    app.add_api_route("/webhooks/mystars", faas_webhook_route(secret, on_event), methods=["POST"])
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Callable, Union

from ..errors import WebhookVerificationError
from ..models import TenantEvent, WebhookEvent
from ..webhook import SIGNATURE_V2_TOLERANCE_SEC, WebhookVerifier

EventHandler = Callable[[WebhookEvent], Union[None, Awaitable[None]]]
TenantEventHandler = Callable[[TenantEvent], Union[None, Awaitable[None]]]


def faas_webhook_route(secret: str, on_event: EventHandler) -> Callable[..., Awaitable[object]]:
    """Build a FastAPI POST handler that verifies and dispatches FaaS webhooks.

    The returned coroutine reads the raw body, verifies ``X-Faas-Signature`` (rotation-aware),
    parses the event, calls ``on_event`` (awaiting it if it returns a coroutine), and replies
    ``200 ok`` — or ``400`` on a bad/missing signature. Register it with
    ``app.add_api_route(path, faas_webhook_route(secret, on_event), methods=["POST"])``.

    Args:
        secret: The tenant webhook secret.
        on_event: Callback invoked with the verified :class:`~mystars_faas.WebhookEvent`; may be
            sync or async. Dedup on ``event.order_id`` (delivery is at-least-once).

    Returns:
        An async FastAPI route handler taking the ``Request``.

    Raises:
        ImportError: If FastAPI is not installed (``pip install 'mystars-faas[fastapi]'``).
    """
    try:
        from fastapi import Request, Response  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError("FastAPI is required: pip install 'mystars-faas[fastapi]'") from exc

    verifier = WebhookVerifier(secret)

    async def handler(request: Request) -> Response:  # type: ignore[name-defined]
        from fastapi import Response  # local import keeps the module import-safe without the extra

        raw = await request.body()
        sig = request.headers.get("x-faas-signature")
        try:
            event = verifier.verify(raw, sig)
        except WebhookVerificationError:
            return Response(status_code=400, content="invalid signature")
        result = on_event(event)
        if result is not None and hasattr(result, "__await__"):
            await result  # type: ignore[misc]
        return Response(status_code=200, content="ok")

    return handler


def faas_tenant_webhook_route(
    secret: str,
    on_event: TenantEventHandler,
    *,
    previous_secret: str | None = None,
    tolerance_sec: int = SIGNATURE_V2_TOLERANCE_SEC,
) -> Callable[..., Awaitable[object]]:
    """Build a FastAPI POST handler for your TENANT webhook endpoint (campaign, giveaway, series events).

    Reads the raw body, verifies ``X-Faas-Signature-V2`` (5-minute tolerance by default), parses the
    envelope into a :class:`~mystars_faas.TenantEvent`, calls ``on_event`` (awaiting it if needed) and
    replies ``200 ok`` — or ``400`` on a bad / stale / missing signature.

    Args:
        secret: Your webhook secret.
        on_event: Callback invoked with the verified event; dedupe on ``event.id``.
        previous_secret: Your previous secret during your own rotation.
        tolerance_sec: Accepted clock distance in seconds.

    Raises:
        ImportError: If FastAPI is not installed (``pip install 'mystars-faas[fastapi]'``).
    """
    try:
        from fastapi import Request, Response  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError("FastAPI is required: pip install 'mystars-faas[fastapi]'") from exc

    verifier = WebhookVerifier(secret, previous_secret=previous_secret, tolerance_sec=tolerance_sec)

    async def handler(request: Request) -> Response:  # type: ignore[name-defined]
        from fastapi import Response

        raw = await request.body()
        try:
            event = verifier.verify_tenant_event(raw, request.headers.get("x-faas-signature-v2"))
        except WebhookVerificationError:
            return Response(status_code=400, content="invalid signature")
        result = on_event(event)
        if result is not None and hasattr(result, "__await__"):
            await result  # type: ignore[misc]
        return Response(status_code=200, content="ok")

    return handler
