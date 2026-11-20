"""Lane B's feeds (contract C2) served from the recorded C3 fixtures with
``httpx.MockTransport``, as the contract describes them: pages of at most ``limit`` (1 to
2000) after ``after_seq``, ``next_after_seq`` the last ``seq`` or null, the header
``X-Source-Fingerprint``, and the environment and run details.

Two detail shapes are served (``detail_fingerprint``): an activated environment whose
detail carries ``source_fingerprint``, ``activated_at`` and ``activated_by`` (and a run
with ``source_fingerprint``), and one where they are null, so the consumer reads the
fingerprint from the first page. Every page and detail served is kept
(:attr:`ContractFeeds.pages`, :attr:`ContractFeeds.details`) so the contract tests can
validate it against the contract (``contracts/`` and the market OpenAPI).

The clients are the worker's own: :func:`~qs_trading.adapters.feed_client.service_client_feed`
(K3's ``ServiceClient``) over ``httpx.MockTransport``, with no wait between retries.
"""

import copy
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from qs_template.service_client import StaticServiceToken
from qs_trading.adapters.feed_client import ServiceClientFeed, service_client_feed

CONTRACTS = Path(__file__).resolve().parents[1] / "fixtures/contracts"
REPLAY = CONTRACTS / "replay_ticks_2020.json"
SYNTHETIC = CONTRACTS / "synthetic_ticks.json"
REPO = Path(__file__).resolve().parents[4]
SCHEMA = REPO / "contracts/events/market.tick.v1.schema.json"
SAMPLES = REPO / "contracts/events/samples"
MARKET_OPENAPI = REPO / "frontend/src/services/generated/market/openapi.json"

REPLAY_ID = "c74eb808-acc6-5fc0-9400-7faa69480261"
REPLAY_FINGERPRINT = "xxh3:2f5521859c9b7beb06802a3df29ef9c3"
REPLAY_TICKS = 1265
RUN_ID = "91fc2771-788d-5a18-99f9-b724c10ea8c8"
RUN_FINGERPRINT = "xxh3:23276fd99c1dff797c94878a6340a06a"
PATH_TICKS = 180

MARKET_URL = "http://market.test"
SIMULATION_URL = "http://simulation.test"
TOKEN = "dev-service-token-0123456789abcdef0123"
ACTIVATED_BY = "9d1e5c7b-2222-4b00-8000-000000000001"
ACTIVATED_AT = "2026-11-18T09:30:00Z"
MAX_LIMIT = 2000
DEFAULT_LIMIT = 500


def load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_bytes())
    return document


async def no_wait(seconds: float) -> None:
    return None


def feed(base_url: str, transport: httpx.AsyncBaseTransport, **options: Any) -> ServiceClientFeed:
    """The worker's feed client on ``transport``, retrying without waiting."""
    tokens = StaticServiceToken(SecretStr(TOKEN), environment="dev")
    return service_client_feed(base_url, tokens, transport=transport, sleep=no_wait, **options)


def problem(status: int, kind: str, detail: str, **members: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "type": f"urn:quantsim:problem:{kind}",
            "title": kind,
            "status": status,
            "detail": detail,
            **members,
        },
        headers={"Content-Type": "application/problem+json"},
    )


class ContractFeeds:
    """Both services over the fixtures. ``restate(env_id, fingerprint)`` makes the feed
    serve another fingerprint from then on (a restated adjusted price, ADR 08)."""

    def __init__(
        self,
        *,
        detail_fingerprint: bool = True,
        environment_status: str = "active",
        run_status: str = "completed",
    ) -> None:
        self.replay = load(REPLAY)
        self.run = load(SYNTHETIC)
        self.detail_fingerprint = detail_fingerprint
        self.environment_status = environment_status
        self.run_status = run_status
        self.fingerprints = {REPLAY_ID: REPLAY_FINGERPRINT, RUN_ID: RUN_FINGERPRINT}
        self.requests: list[httpx.Request] = []
        self.pages: list[dict[str, Any]] = []
        self.details: list[dict[str, Any]] = []
        self.problems: list[dict[str, Any]] = []
        self.missing: dict[str, int] | None = None  # set: the replay feed answers 422
        self.detail_changes: dict[str, Any] = {}  # applied to the environment detail

    def restate(self, env_id: str, fingerprint: str) -> None:
        self.fingerprints[env_id] = fingerprint

    def _page(
        self, env_id: str, items: list[dict[str, Any]], request: httpx.Request
    ) -> httpx.Response:
        params = request.url.params
        try:
            after_seq = int(params.get("after_seq", "0"))
            limit = int(params.get("limit", str(DEFAULT_LIMIT)))
        except ValueError:
            return problem(422, "validation", "after_seq and limit are whole numbers")
        if after_seq < 0 or not 1 <= limit <= MAX_LIMIT:
            return problem(422, "validation", f"limit must be 1 to {MAX_LIMIT}")
        fingerprint = self.fingerprints[env_id]
        served = copy.deepcopy(items[after_seq : after_seq + limit])
        for item in served:
            item["source_fingerprint"] = fingerprint
        more = after_seq + limit < len(items)
        body = {"items": served, "next_after_seq": served[-1]["seq"] if served and more else None}
        self.pages.append(body)
        return httpx.Response(200, json=body, headers={"X-Source-Fingerprint": fingerprint})

    def _environment(self) -> dict[str, Any]:
        environment = self.replay["environment"]
        detail = {
            "id": REPLAY_ID,
            "name": environment["name"],
            "type": environment["type"],
            "universe": "custom",
            "instrument_ids": [i["id"] for i in environment["instruments"]],
            "symbols": [i["symbol"] for i in environment["instruments"]],
            "start_date": environment["start_date"],
            "end_date": environment["end_date"],
            "frequency": environment["frequency"],
            "status": self.environment_status,
            "created_by": ACTIVATED_BY,
            "created_at": "2026-11-18T09:00:00Z",
            # frozen at activation, null until then
            "source_fingerprint": None,
            "activated_at": None,
            "activated_by": None,
        }
        if self.detail_fingerprint:
            detail["source_fingerprint"] = REPLAY_FINGERPRINT
            detail["activated_at"] = ACTIVATED_AT
            detail["activated_by"] = ACTIVATED_BY
        detail.update(self.detail_changes)
        self.details.append(detail)
        return detail

    def _run(self) -> dict[str, Any]:
        run = self.run["run"]
        detail = {
            "id": RUN_ID,
            "status": self.run_status,
            "model": run["model"],
            "n_paths": run["n_paths"],
            "n_steps": run["n_steps"],
            "symbols": run["symbols"],
            "median_path_index": run["median_path_index"],
            "parent_run_id": None,
            "scenario": None,
            "created_at": "2026-11-18T10:00:00Z",
            "progress": 1.0,
            "seed": run["seed"],
            "storage_mode": "full",
            "statistics": [],
        }
        if self.detail_fingerprint:
            detail["source_fingerprint"] = RUN_FINGERPRINT
        return detail

    def _missing_adjusted_prices(self, missing: dict[str, int]) -> httpx.Response:
        bars = ", ".join(f"{symbol} ({count})" for symbol, count in missing.items())
        response = problem(
            422,
            "missing-adjusted-prices",
            f"bars without adjusted prices: {bars}",
            missing=missing,
        )
        self.problems.append(json.loads(response.content))
        return response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return problem(401, "unauthorized", "no or bad token")
        parts = request.url.path.strip("/").split("/")
        host = request.url.host
        if host == "market.test" and parts[:3] == ["api", "market", "environments"]:
            if len(parts) < 4 or parts[3] != REPLAY_ID:
                return problem(404, "not-found", "no such environment")
            if len(parts) == 4:
                return httpx.Response(200, json=self._environment())
            if parts[4:] == ["ticks"]:
                if self.missing is not None:
                    return self._missing_adjusted_prices(self.missing)
                return self._page(REPLAY_ID, self.replay["items"], request)
        if host == "simulation.test" and parts[:3] == ["api", "simulation", "runs"]:
            if len(parts) < 4 or parts[3] != RUN_ID:
                return problem(404, "not-found", "no such run")
            if len(parts) == 4:
                return httpx.Response(200, json=self._run())
            if parts[4:] == ["ticks"]:
                if "path" not in request.url.params:  # required, as the #80 review asks
                    return problem(422, "validation", "path is required")
                index = int(request.url.params["path"])
                paths = [p for p in self.run["paths"] if p["path_index"] == index]
                if not paths:
                    return problem(422, "validation", f"the run has no path {index}")
                return self._page(RUN_ID, paths[0]["items"], request)
        return problem(404, "not-found", request.url.path)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def market_client(self) -> ServiceClientFeed:
        return feed(MARKET_URL, self.transport())

    def simulation_client(self) -> ServiceClientFeed:
        return feed(SIMULATION_URL, self.transport())

    def tick_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/ticks")]
