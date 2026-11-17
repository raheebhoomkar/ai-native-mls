"""Load smoke test: a few concurrent clients read listings for a short time.

Standard library only. Not a capacity test; it catches a release that is suddenly slow
or fails under light concurrent use.

    python3 scripts/load_smoke.py --base-url http://localhost:8000 \
        --email sunrise.agent@demo.example.com --password local-dev-password

Exits 1 when the error rate or the 95th percentile latency is over its limit.
"""

# ruff: noqa: S310  # main() accepts only http and https base URLs

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

PATHS = ("/api/v1/listings?limit=20", "/api/v1/health", "/api/v1/dashboard")


def sign_in(base_url: str, email: str, password: str) -> str:
    """Return the session cookie. One sign-in is shared, so the sign-in rate limit is not hit."""
    request = urllib.request.Request(
        f"{base_url}/api/v1/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        cookie = response.headers.get("Set-Cookie", "")
    return cookie.split(";", 1)[0]


def client(
    base_url: str, cookie: str, until: float, latencies: list[float], errors: list[str]
) -> None:
    n = 0
    while time.monotonic() < until:
        path = PATHS[n % len(PATHS)]
        n += 1
        request = urllib.request.Request(f"{base_url}{path}", headers={"Cookie": cookie})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            errors.append(f"{path}: {error}")
        latencies.append((time.monotonic() - started) * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        parser.error("--base-url must start with http:// or https://")
    cookie = sign_in(base_url, args.email, args.password)
    latencies: list[float] = []  # list.append is atomic, so threads can share these
    errors: list[str] = []
    until = time.monotonic() + args.seconds
    threads = [
        threading.Thread(target=client, args=(base_url, cookie, until, latencies, errors))
        for _ in range(args.clients)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    total = len(latencies)
    if total == 0:
        print("No requests were made.")
        return 1
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[-1] if total > 1 else latencies[0]
    error_rate = len(errors) / total
    print(
        f"{total} requests from {args.clients} clients in {args.seconds:g} s "
        f"({total / args.seconds:.1f}/s); errors {len(errors)} ({error_rate:.1%}); "
        f"p50 {p50:.0f} ms, p95 {p95:.0f} ms"
    )
    for error in sorted(set(errors))[:5]:
        print(f"  {error}")
    failed = error_rate > args.max_error_rate or p95 > args.max_p95_ms
    if failed:
        limits = f"p95 {args.max_p95_ms:g} ms, error rate {args.max_error_rate:.1%}"
        print(f"FAILED: limits are {limits}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
