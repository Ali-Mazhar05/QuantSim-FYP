"""DEV stand-in for Lane B's feeds (contract C2) over the recorded C3 fixtures.

Until the market and simulation services serve their feed routes (task B12; they answer
501 today), DEV mounts this app inside the Trading service at ``/demo-feeds`` and points
``QS_TRADING_MARKET_URL`` and ``QS_TRADING_SIMULATION_URL`` at it. A portfolio bound to the
recorded 2020 replay (:data:`REPLAY_ID`) or the recorded synthetic run (:data:`RUN_ID`)
then runs through the worker's real HTTP path: K3's ``ServiceClient`` with a platform
service token, paging, the fingerprint header and the per-session fingerprint check. The
DEV live check compares that run with the same data read from the file copy
(:data:`FILE_COPY_ID`, a demo environment), which is the J2 hash comparison on a deployed
worker.

The routes and shapes are the contract's (the ones ``tests/contract/feed_support.py``
serves): pages of at most ``limit`` (1 to 2000, default 500) after ``after_seq``,
``next_after_seq`` the last ``seq`` or null, the ``X-Source-Fingerprint`` header, and the
environment and run details; errors are problem+json. A bearer token is required but not
checked: the app is reachable only inside the DEV network (the gateway routes
``/api/trading`` only), and its data is public recorded prices. It is refused outside
local and dev (``QS_TRADING_DEMO_FEEDS``).

    GET /api/market/environments/{id}
    GET /api/market/environments/{id}/ticks?after_seq=&limit=
    GET /api/simulation/runs/{id}
    GET /api/simulation/runs/{id}/ticks?path=&after_seq=&limit=
"""

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

__all__ = [
    "FEEDS_DIRECTORY",
    "FILE_COPY_ID",
    "REPLAY_ID",
    "RUN_ID",
    "demo_feeds_app",
]

FEEDS_DIRECTORY = Path(__file__).resolve().parent / "feeds"
REPLAY_FILE = FEEDS_DIRECTORY / "replay_ticks_2020.json"
RUN_FILE = FEEDS_DIRECTORY / "synthetic_ticks.json"

REPLAY_ID = "c74eb808-acc6-5fc0-9400-7faa69480261"
RUN_ID = "91fc2771-788d-5a18-99f9-b724c10ea8c8"
# The demo environment holding the same replay as a file (demo/environments/<id>.json)
FILE_COPY_ID = "5d0c6c1e-7a14-4a14-8a14-000000002020"

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000
# Who "activated" the recorded environment; fixed, so the details never change
RECORDED_BY = "9d1e5c7b-2222-4b00-8000-000000000001"
RECORDED_AT = "2026-11-18T09:30:00Z"
PROBLEM_JSON = "application/problem+json"


@cache
def _load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_bytes())
    return document


def _problem(status: int, kind: str, detail: str) -> JSONResponse:
    body = {
        "type": f"urn:quantsim:problem:{kind}",
        "title": kind,
        "status": status,
        "detail": detail,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _page(items: list[dict[str, Any]], fingerprint: str, request: Request) -> JSONResponse:
    params = request.query_params
    try:
        after_seq = int(params.get("after_seq", "0"))
        limit = int(params.get("limit", str(DEFAULT_LIMIT)))
    except ValueError:
        return _problem(422, "validation", "after_seq and limit are whole numbers")
    if after_seq < 0 or not 1 <= limit <= MAX_LIMIT:
        return _problem(422, "validation", f"after_seq >= 0 and limit 1 to {MAX_LIMIT}")
    served = copy.deepcopy(items[after_seq : after_seq + limit])
    more = after_seq + limit < len(items)
    body = {"items": served, "next_after_seq": served[-1]["seq"] if served and more else None}
    return JSONResponse(body, headers={"X-Source-Fingerprint": fingerprint})


def _environment_detail(document: dict[str, Any]) -> dict[str, Any]:
    environment = document["environment"]
    return {
        "id": environment["id"],
        "name": environment["name"],
        "type": environment["type"],
        "universe": "custom",
        "instrument_ids": [i["id"] for i in environment["instruments"]],
        "symbols": [i["symbol"] for i in environment["instruments"]],
        "start_date": environment["start_date"],
        "end_date": environment["end_date"],
        "frequency": environment["frequency"],
        "status": "active",
        "created_by": RECORDED_BY,
        "created_at": RECORDED_AT,
        "source_fingerprint": environment["source_fingerprint"],
        "activated_at": RECORDED_AT,
        "activated_by": RECORDED_BY,
    }


def _run_detail(document: dict[str, Any]) -> dict[str, Any]:
    run = document["run"]
    return {
        "id": run["id"],
        "status": "completed",
        "model": run["model"],
        "n_paths": run["n_paths"],
        "n_steps": run["n_steps"],
        "symbols": run["symbols"],
        "median_path_index": run["median_path_index"],
        "parent_run_id": None,
        "scenario": None,
        "created_at": RECORDED_AT,
        "progress": 1.0,
        "seed": run["seed"],
        "storage_mode": "full",
        "statistics": [],
        "source_fingerprint": run["source_fingerprint"],
    }


def _signed(request: Request) -> bool:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(token.strip())


def demo_feeds_app() -> FastAPI:
    """The stand-in feed app, to be mounted at ``/demo-feeds`` (left out of the OpenAPI)."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def require_a_token(request: Request, call_next: Any) -> Any:
        if not _signed(request):
            return _problem(401, "unauthorized", "a bearer token is required")
        return await call_next(request)

    @app.get("/api/market/environments/{env_id}")
    async def environment(env_id: str) -> JSONResponse:
        if env_id != REPLAY_ID:
            return _problem(404, "not-found", f"no environment {env_id}")
        return JSONResponse(_environment_detail(_load(REPLAY_FILE)))

    @app.get("/api/market/environments/{env_id}/ticks")
    async def environment_ticks(env_id: str, request: Request) -> JSONResponse:
        if env_id != REPLAY_ID:
            return _problem(404, "not-found", f"no environment {env_id}")
        document = _load(REPLAY_FILE)
        return _page(document["items"], document["environment"]["source_fingerprint"], request)

    @app.get("/api/simulation/runs/{run_id}")
    async def run(run_id: str) -> JSONResponse:
        if run_id != RUN_ID:
            return _problem(404, "not-found", f"no run {run_id}")
        return JSONResponse(_run_detail(_load(RUN_FILE)))

    @app.get("/api/simulation/runs/{run_id}/ticks")
    async def run_ticks(run_id: str, request: Request) -> JSONResponse:
        if run_id != RUN_ID:
            return _problem(404, "not-found", f"no run {run_id}")
        raw = request.query_params.get("path")
        if raw is None or not raw.isdigit():
            return _problem(422, "validation", "path is required: a whole number >= 0")
        document = _load(RUN_FILE)
        paths = [p for p in document["paths"] if p["path_index"] == int(raw)]
        if not paths:
            return _problem(422, "validation", f"the run has no path {raw}")
        return _page(paths[0]["items"], document["run"]["source_fingerprint"], request)

    return app
