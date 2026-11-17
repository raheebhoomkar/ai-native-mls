"""A sample third-party client for the AI-Native MLS public API. Standard library only.

    export MLS_API_URL=http://localhost:8000/api/v1
    export MLS_API_KEY=mls_xxxxxxxx_...   # created on the "API keys" page
    python examples/mls_client.py list
    python examples/mls_client.py create   # needs the listing:write scope

It shows the three things a client must get right: the bearer key, waiting when told to
(HTTP 429 and Retry-After), and an Idempotency-Key on writes so a retry never makes a
second listing.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

BASE = os.environ.get("MLS_API_URL", "http://localhost:8000/api/v1").rstrip("/")
MAX_TRIES = 4


class ApiError(Exception):
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        error = body.get("error", {})
        super().__init__(f"HTTP {status} {error.get('code')}: {error.get('message')}")
        self.status = status
        self.body = body


def call(method: str, path: str, body: Any = None, *, idempotency_key: str | None = None) -> Any:
    """Send one request; wait and try again on 429 and on network or server errors."""
    headers = {"Authorization": f"Bearer {os.environ['MLS_API_KEY']}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    for attempt in range(1, MAX_TRIES + 1):
        request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                text = response.read().decode()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            payload = json.loads(error.read().decode() or "{}")
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt == MAX_TRIES:
                raise ApiError(error.code, payload) from None
            wait = int(error.headers.get("Retry-After", 2**attempt))
        except urllib.error.URLError:
            if attempt == MAX_TRIES:
                raise
            wait = 2**attempt
        # Safe to send again: a write carries the same Idempotency-Key every time.
        time.sleep(wait)
    raise AssertionError("unreachable")


def list_listings() -> None:
    page = call("GET", "/listings?limit=10")
    for listing in page["items"]:
        price = listing["list_price"]
        print(f"{listing['id']}  {listing['status']:<15} {price['amount']:>14} {price['currency']}  {listing['title']}")


def create_listing() -> None:
    prop = call(
        "POST",
        "/properties",
        {
            "property_type": "apartment",
            "address": {"line1": "4 Hill Road", "locality": "Bandra West", "city": "Mumbai", "country": "IN"},
            "bedrooms": 2,
            "bathrooms": 2,
            "area": {"value": "950", "unit": "sqft"},
        },
        idempotency_key=str(uuid.uuid4()),
    )
    listing = call(
        "POST",
        "/listings",
        {
            "property_id": prop["id"],
            "listing_type": "sale",
            "title": "2 BHK near Bandstand (created by the sample client)",
            "list_price": {"amount": "32000000", "currency": "INR"},
        },
        idempotency_key=str(uuid.uuid4()),
    )
    print(f"Created draft listing {listing['id']}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    try:
        {"list": list_listings, "create": create_listing}[command]()
    except ApiError as error:
        sys.exit(str(error))
