"""Minimal webhook receiver for BOTH kinds of MyStars webhook on one endpoint.

Order callbacks (``callback_url``) and tenant events (campaigns, giveaways, series) are told apart
by ``WebhookVerifier.verify_event``, which verifies ``X-Faas-Signature-V2`` (the HMAC covers the
send time, so a captured request cannot be replayed later) and falls back to the legacy
``X-Faas-Signature`` only for an order body without V2. Delivery is at-least-once: dedup orders on
``order_id`` and tenant events on ``id``. Uses only the stdlib http.server (zero extra deps); for
FastAPI/Flask use the route factories in mystars_faas.integrations.fastapi / .flask - see the README.

Run:
    MYSTARS_WEBHOOK_SECRET=... python examples/webhook_server.py
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from mystars_faas import TenantEvent, WebhookVerificationError, WebhookVerifier

_secret = os.environ.get("MYSTARS_WEBHOOK_SECRET")
if not _secret:
    raise SystemExit("set MYSTARS_WEBHOOK_SECRET")

_verifier = WebhookVerifier(_secret)
_seen: set[str] = set()  # replace with a durable store


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/webhooks/mystars":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            # Verify BEFORE trusting the body.
            event = _verifier.verify_event(raw_body, dict(self.headers.items()))
            key = event.id if isinstance(event, TenantEvent) else f"order:{event.order_id}"
            if key not in _seen:
                _seen.add(key)
                if isinstance(event, TenantEvent):
                    print(event.type, event.data)  # campaign.*, giveaway.*, series.*
                else:
                    print("order", event.order_id, "->", event.status)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        except WebhookVerificationError:
            # Bad/missing/stale signature - never act on an unverified body.
            self.send_response(400)
            self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
