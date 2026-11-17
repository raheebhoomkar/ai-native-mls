"""A sample webhook receiver that checks the signature. Standard library only.

    MLS_WEBHOOK_SECRET=whsec_... python examples/webhook_receiver.py 9099

Then add a webhook for http://localhost:9099/ on the Webhooks page (outside production,
http and local addresses are allowed). Each event is printed with "signature ok" or refused
with 401.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ["MLS_WEBHOOK_SECRET"]
TOLERANCE_SECONDS = 300


def verify(header: str, body: bytes) -> bool:
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - timestamp) > TOLERANCE_SECONDS:
        return False  # too old: maybe a replay
    expected = hmac.new(SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return hmac.compare_digest(f"t={timestamp},v1={expected.hexdigest()}", header)


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not verify(self.headers.get("X-MLS-Signature", ""), body):
            self.send_response(401)
            self.end_headers()
            print("refused: bad signature", flush=True)
            return
        event = json.loads(body)
        # Deliveries can repeat: use X-MLS-Delivery (or the event id) to skip duplicates.
        print(f"signature ok: {event['type']} {event['data']}", flush=True)
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    HTTPServer(("127.0.0.1", port), Receiver).serve_forever()
