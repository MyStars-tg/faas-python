"""Flask webhook view factory. Requires the ``[flask]`` extra.

    from flask import Flask
    from mystars_faas.integrations.flask import faas_webhook_view

    app = Flask(__name__)
    app.add_url_rule("/webhooks/mystars", view_func=faas_webhook_view(secret, on_event), methods=["POST"])
"""

from __future__ import annotations

from typing import Callable

from ..errors import WebhookVerificationError
from ..models import WebhookEvent
from ..webhook import WebhookVerifier

EventHandler = Callable[[WebhookEvent], None]


def faas_webhook_view(secret: str, on_event: EventHandler) -> Callable[[], object]:
    """Build a Flask view that verifies and dispatches FaaS webhooks.

    The returned view reads the raw bytes (``request.get_data()`` — never ``request.json``,
    which re-serializes), verifies ``X-Faas-Signature`` (rotation-aware), parses the event,
    calls ``on_event``, and returns ``("ok", 200)`` — or ``("invalid signature", 400)`` on a
    bad/missing signature. Register it with
    ``app.add_url_rule(path, view_func=faas_webhook_view(secret, on_event), methods=["POST"])``.

    Args:
        secret: The tenant webhook secret.
        on_event: Callback invoked with the verified :class:`~mystars_faas.WebhookEvent`. Dedup
            on ``event.order_id`` (delivery is at-least-once).

    Returns:
        A Flask view callable.

    Raises:
        ImportError: If Flask is not installed (``pip install 'mystars-faas[flask]'``).
    """
    try:
        from flask import request  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Flask is required: pip install 'mystars-faas[flask]'") from exc

    verifier = WebhookVerifier(secret)

    def view() -> object:
        from flask import request

        raw = request.get_data()  # raw bytes — do NOT use request.json (re-serialized)
        sig = request.headers.get("X-Faas-Signature")
        try:
            event = verifier.verify(raw, sig)
        except WebhookVerificationError:
            return ("invalid signature", 400)
        on_event(event)
        return ("ok", 200)

    return view
