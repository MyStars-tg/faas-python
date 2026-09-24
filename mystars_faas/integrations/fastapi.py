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
from ..models import WebhookEvent
from ..webhook import WebhookVerifier

EventHandler = Callable[[WebhookEvent], Union[None, Awaitable[None]]]


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
