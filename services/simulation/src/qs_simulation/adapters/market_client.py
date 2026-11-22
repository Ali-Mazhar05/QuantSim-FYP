"""The service client (K3) as the market adapters use it (B15, B16).

``ServiceClient.get_json`` is already what ``MarketPriceSource`` needs. A POST that returns JSON is
one more call: ``JsonPoster``. The correlation window request changes nothing on the market side, so
every send of the same body carries the same idempotency key; K3 only retries a request that has
one, and this way a dropped connection is retried instead of failing the whole run.
"""

import json
from typing import Any

import xxhash

from qs_template.service_client import ServiceClient


class JsonPoster:
    def __init__(self, client: ServiceClient) -> None:
        self._client = client

    async def post_json(self, path: str, *, json: Any) -> Any:
        key = idempotency_key(path, json)
        return (await self._client.post(path, json=json, idempotency_key=key)).json()


def idempotency_key(path: str, body: Any) -> str:
    """The same path and body always give the same key (canonical JSON, then a 128 bit hash)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return xxhash.xxh3_128_hexdigest(f"{path}\n{canonical}")
