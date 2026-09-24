"""Minimal webhook receiver - verifies X-Faas-Signature over the RAW body, dedups on order_id.

Delivery is at-least-once, so dedup on order_id. Uses only the stdlib http.server (zero extra
deps); for FastAPI/Flask use the route factories in mystars_faas.integrations.fastapi / .flask
instead - see the README.

Run:
    MYSTARS_WEBHOOK_SECRET=... python examples/webhook_server.py
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from mystars_faas import WebhookVerificationError, WebhookVerifier

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
        signature = self.headers.get("X-Faas-Signature")
        try:
            # Verify BEFORE trusting the body (handles the 24h "current,previous" rotation).
            event = _verifier.verify(raw_body, signature)
            if event.order_id not in _seen:
                _seen.add(event.order_id)
                print("order", event.order_id, "->", event.status)
                # ... advance your own order state here ...
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        except WebhookVerificationError:
            # Bad/missing signature - never act on an unverified body.
            self.send_response(400)
            self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
