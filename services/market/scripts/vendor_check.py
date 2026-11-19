"""Check the real Tiingo vendor by hand, with one symbol and at most two requests.

    TIINGO_API_KEY=... python services/market/scripts/vendor_check.py [SYMBOL]

Prints the HTTP status, the latency, the fields and the first row of a short price
history. It makes no retries, uses no Redis budget (a human is counting) and never prints
the key. Run it from a trusted machine; tests never call the vendor.
"""

import asyncio
import os
import sys
import time
from datetime import date, timedelta

import httpx

BASE_URL = "https://api.tiingo.com"
MAX_REQUESTS = 2


async def main(symbol: str) -> int:
    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        print("TIINGO_API_KEY is not set", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Token {key}"}
    end = date.today()
    start = end - timedelta(days=10)
    requests = [
        ("metadata", f"{BASE_URL}/tiingo/daily/{symbol}", {}),
        (
            "prices",
            f"{BASE_URL}/tiingo/daily/{symbol}/prices",
            {"startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json"},
        ),
    ][:MAX_REQUESTS]
    failed = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        for label, url, params in requests:
            began = time.monotonic()
            try:
                response = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                print(f"{label}: request failed ({type(exc).__name__})")
                failed = True
                continue
            elapsed = time.monotonic() - began
            print(f"{label}: HTTP {response.status_code} in {elapsed:.2f}s")
            if response.status_code != 200:
                failed = True
                continue
            body = response.json()
            first = body[0] if isinstance(body, list) and body else body
            if isinstance(first, dict):
                print(f"{label}: fields {sorted(first)}")
                print(f"{label}: first row {first}")
            else:
                print(f"{label}: no rows in the window")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "AAPL")))
