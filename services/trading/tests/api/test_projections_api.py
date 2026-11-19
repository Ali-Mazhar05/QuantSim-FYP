"""Projection, state, verify, rebuild and metrics routes over the in-memory store, whose
portfolio has run on the A14 fixture through the real engine and fold: the pages and
cursors, the shapes and decimal strings, the 404s and 422s, admin-only rebuild, a broken
log as 409, and metrics equal to sums over the fills (A-FR-11, A-FR-14, A-FR-15)."""

import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import httpx
import pytest
from api_support import (
    API,
    MOMENTUM,
    FakeStore,
    as_role,
    client_for,
    fake_app,
    portfolio_body,
)

from qs_template.auth import Role
from qs_trading.metrics import RunFigures, SeriesMetrics

VIEWER = Role.VIEWER


async def _portfolio(http: httpx.AsyncClient) -> uuid.UUID:
    quant = as_role(Role.QUANT)
    strategy = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
    created = await http.post(
        f"{API}/portfolios", json=portfolio_body(strategy.json()["id"]), headers=quant
    )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


async def _ran(http: httpx.AsyncClient, store: FakeStore) -> uuid.UUID:
    portfolio_id = await _portfolio(http)
    await store.add_run(portfolio_id)
    return portfolio_id


async def _pages(http: httpx.AsyncClient, url: str, limit: int) -> list[dict[str, Any]]:
    """Every item of a seq-paged route, checking each cursor on the way."""
    items: list[dict[str, Any]] = []
    after = 0
    while True:
        page = await http.get(
            url, params={"after_seq": after, "limit": limit}, headers=as_role(VIEWER)
        )
        assert page.status_code == 200, page.text
        body = page.json()
        assert len(body["items"]) <= limit
        items += body["items"]
        if body["next_cursor"] is None:
            return items
        assert len(body["items"]) == limit
        assert body["next_cursor"] == body["items"][-1]["seq"]
        after = body["next_cursor"]


async def test_fills_page_by_seq_with_a_cursor_and_carry_decimal_strings() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        stored = store.projections[portfolio_id].fills
        assert len(stored) > 2

        items = await _pages(http, f"{API}/portfolios/{portfolio_id}/fills", limit=2)
        assert [f["seq"] for f in items] == sorted(stored)
        first = items[0]
        assert set(first) == {
            "seq",
            "order_id",
            "session",
            "symbol",
            "side",
            "quantity",
            "reference_price",
            "fill_price",
            "slippage",
            "cost_fixed",
            "cost_per_share",
            "cost_percentage",
            "cost_total",
            "cash_after",
        }
        row = stored[first["seq"]]
        assert Decimal(first["fill_price"]) == row["fill_price"]
        assert Decimal(first["cost_total"]) == row["cost_total"]
        assert isinstance(first["cash_after"], str) and isinstance(first["quantity"], int)

        past = await http.get(
            f"{API}/portfolios/{portfolio_id}/fills",
            params={"after_seq": items[-1]["seq"]},
            headers=as_role(VIEWER),
        )
        assert past.json() == {"items": [], "next_cursor": None}


async def test_holdings_are_the_state_row_and_empty_before_a_run() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        idle = await _portfolio(http)
        empty = await http.get(f"{API}/portfolios/{idle}/holdings", headers=as_role(VIEWER))
        assert empty.status_code == 200, empty.text
        assert empty.json() == {
            "portfolio_id": str(idle),
            "last_seq": 0,
            "last_session": None,
            "cash": None,
            "positions": [],
        }

        portfolio_id = await _ran(http, store)
        state = store.projections[portfolio_id].state
        assert state is not None
        body = (
            await http.get(f"{API}/portfolios/{portfolio_id}/holdings", headers=as_role(VIEWER))
        ).json()
        assert body["last_seq"] == state["last_seq"]
        assert body["last_session"] == state["last_session"]
        assert Decimal(body["cash"]) == state["cash"]
        assert {
            p["symbol"]: (p["quantity"], Decimal(p["cost_basis"])) for p in body["positions"]
        } == {
            symbol: (item["quantity"], Decimal(item["cost_basis"]))
            for symbol, item in state["positions"].items()
        }


async def test_the_holding_history_pages_one_row_per_fill() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        items = await _pages(http, f"{API}/portfolios/{portfolio_id}/holdings/history", limit=3)
        stored = store.projections[portfolio_id]
        assert [(h["seq"], h["symbol"]) for h in items] == sorted(stored.holdings)
        assert {h["seq"] for h in items} == set(stored.fills)
        assert set(items[0]) == {"seq", "session", "symbol", "quantity", "cost_basis"}


async def test_the_value_series_is_one_point_per_session_in_order() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        response = await http.get(
            f"{API}/portfolios/{portfolio_id}/value-series", headers=as_role(VIEWER)
        )
        assert response.status_code == 200, response.text
        series = response.json()
        assert [p["session"] for p in series] == list(range(10))
        stored = store.projections[portfolio_id].values
        for point in series:
            row = stored[point["seq"]]
            assert Decimal(point["value"]) == row["value"]
            assert Decimal(point["cash"]) + Decimal(point["market_value"]) == row["value"]
            assert isinstance(point["total_costs"], str)


async def test_the_state_as_of_the_last_seq_is_the_state_row() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        log = store.stored_logs[portfolio_id]
        state = store.projections[portfolio_id].state
        assert state is not None
        url = f"{API}/portfolios/{portfolio_id}/state"

        last = await http.get(url, params={"as_of_seq": log[-1].seq}, headers=as_role(VIEWER))
        assert last.status_code == 200, last.text
        body = last.json()
        assert body["seq"] == state["last_seq"] and body["hash"] == state["last_hash"]
        assert body["session"] == state["last_session"]
        assert Decimal(body["cash"]) == state["cash"]
        assert {p["symbol"]: p["quantity"] for p in body["positions"]} == {
            symbol: item["quantity"] for symbol, item in state["positions"].items()
        }
        assert body["open_orders"] == [] and body["initial_capital"] == "10000.00"
        assert (await http.get(url, headers=as_role(VIEWER))).json() == body

        first = (await http.get(url, params={"as_of_seq": 1}, headers=as_role(VIEWER))).json()
        assert first["seq"] == 1 and first["hash"] == log[0].hash
        assert Decimal(first["cash"]) == Decimal("10000") and first["positions"] == []
        assert first["last_value"] is None and first["last_valued_seq"] is None


async def test_state_errors_are_problems() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        idle = await _portfolio(http)
        last = store.stored_logs[portfolio_id][-1].seq
        viewer = as_role(VIEWER)

        beyond = await http.get(
            f"{API}/portfolios/{portfolio_id}/state", params={"as_of_seq": last + 1}, headers=viewer
        )
        assert beyond.status_code == 404
        assert beyond.json()["type"] == "urn:quantsim:problem:not-found"
        assert beyond.json()["title"] == "Event not found"
        not_run = await http.get(f"{API}/portfolios/{idle}/state", headers=viewer)
        assert not_run.status_code == 404
        unknown = await http.get(f"{API}/portfolios/{uuid.uuid4()}/state", headers=viewer)
        assert unknown.status_code == 404 and unknown.json()["title"] == "Portfolio not found"
        for bad in ("0", "-3", "x"):
            refused = await http.get(
                f"{API}/portfolios/{portfolio_id}/state", params={"as_of_seq": bad}, headers=viewer
            )
            assert refused.status_code == 422, refused.text


def _tamper(store: FakeStore, portfolio_id: uuid.UUID, seq: int) -> None:
    """Changes the stored payload at ``seq`` without re-hashing it."""
    log = store.stored_logs[portfolio_id]
    log[seq - 1] = replace(log[seq - 1], payload={**log[seq - 1].payload, "tampered": True})


async def test_a_broken_log_is_409_for_state_and_rebuild_and_reported_by_verify() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        base = f"{API}/portfolios/{portfolio_id}"

        report = (await http.get(f"{base}/verify", headers=as_role(VIEWER))).json()
        log = store.stored_logs[portfolio_id]
        assert report == {
            "portfolio_id": str(portfolio_id),
            "valid": True,
            "events": len(log),
            "last_seq": log[-1].seq,
            "last_hash": log[-1].hash,
            "broken_seq": None,
            "reason": None,
        }

        _tamper(store, portfolio_id, 5)
        broken = (await http.get(f"{base}/verify", headers=as_role(VIEWER))).json()
        assert broken["valid"] is False and broken["broken_seq"] == 5
        assert broken["last_seq"] == 4 and broken["last_hash"] == log[3].hash

        before = await http.get(f"{base}/state", params={"as_of_seq": 4}, headers=as_role(VIEWER))
        assert before.status_code == 200, before.text
        for response in (
            await http.get(f"{base}/state", params={"as_of_seq": 5}, headers=as_role(VIEWER)),
            await http.post(f"{base}/rebuild", headers=as_role(Role.ADMIN)),
        ):
            assert response.status_code == 409, response.text
            problem = response.json()
            assert response.headers["content-type"].startswith("application/problem+json")
            assert problem["type"] == "urn:quantsim:problem:log-broken"
            assert problem["broken_seq"] == 5 and problem["reason"]


async def test_rebuild_is_admin_only_and_reports_identical_differs_and_applied() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _ran(http, store)
        url = f"{API}/portfolios/{portfolio_id}/rebuild"
        log = store.stored_logs[portfolio_id]
        admin = as_role(Role.ADMIN)

        for role in (Role.VIEWER, Role.ANALYST, Role.QUANT):
            refused = await http.post(url, headers=as_role(role))
            assert refused.status_code == 403
            assert refused.json()["type"] == "urn:quantsim:problem:forbidden"

        same = await http.post(url, headers=admin)
        assert same.status_code == 200, same.text
        assert same.json() == {
            "portfolio_id": str(portfolio_id),
            "status": "identical",
            "events": len(log),
            "final_seq": log[-1].seq,
            "final_hash": log[-1].hash,
            "differences": [],
            "applied": False,
        }

        stored = store.projections[portfolio_id]
        dropped = min(stored.fills)
        fills = {seq: row for seq, row in stored.fills.items() if seq != dropped}
        store.projections[portfolio_id] = replace(stored, fills=fills)

        differs = (await http.post(url, headers=admin)).json()
        assert differs["status"] == "differs" and differs["applied"] is False
        assert differs["differences"] == [
            {"table": "fill", "missing": [f"seq={dropped}"], "unexpected": [], "changed": []}
        ]
        applied = (await http.post(url, params={"apply": "true"}, headers=admin)).json()
        assert applied["status"] == "differs" and applied["applied"] is True
        again = (await http.post(url, headers=admin)).json()
        assert again["status"] == "identical" and again["final_hash"] == log[-1].hash

        refused = await http.post(url, params={"apply": "perhaps"}, headers=admin)
        assert refused.status_code == 422


async def test_metrics_count_trades_and_costs_and_leave_the_ratios_pending() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        idle = await _portfolio(http)
        empty = (await http.get(f"{API}/portfolios/{idle}/metrics", headers=as_role(VIEWER))).json()
        assert empty == {
            "portfolio_id": str(idle),
            "final_seq": 0,
            "final_hash": None,
            "sessions": 0,
            "initial_capital": "10000.00",
            "final_value": None,
            "trades": 0,
            "total_costs": "0",
            "total_return": None,
            "volatility": None,
            "sharpe": None,
            "max_drawdown": None,
            "turnover": None,
            "pending": ["total_return", "volatility", "sharpe", "max_drawdown", "turnover"],
        }

        portfolio_id = await _ran(http, store)
        body = (
            await http.get(f"{API}/portfolios/{portfolio_id}/metrics", headers=as_role(VIEWER))
        ).json()
        stored = store.projections[portfolio_id]
        fills = stored.fills.values()
        last_value = stored.values[max(stored.values)]
        assert body["trades"] == len(fills) > 0
        assert Decimal(body["total_costs"]) == sum(row["cost_total"] for row in fills)
        assert body["sessions"] == 10
        assert Decimal(body["final_value"]) == last_value["value"]
        assert body["final_seq"] == store.stored_logs[portfolio_id][-1].seq
        assert body["final_hash"] == store.stored_logs[portfolio_id][-1].hash
        assert body["total_return"] is None and len(body["pending"]) == 5


class _Library:
    """Stands in for the shared metrics library: a return and a drawdown only."""

    def __init__(self) -> None:
        self.seen: list[RunFigures] = []

    def series_metrics(self, figures: RunFigures) -> SeriesMetrics:
        self.seen.append(figures)
        final = figures.final_value
        assert final is not None
        return SeriesMetrics(
            total_return=final / figures.initial_capital - 1, max_drawdown=Decimal("0.05")
        )


async def test_a_metrics_calculator_fills_in_the_ratios_it_computes() -> None:
    store, library = FakeStore(), _Library()
    async with client_for(fake_app(store, metrics=library)) as http:
        portfolio_id = await _ran(http, store)
        body = (
            await http.get(f"{API}/portfolios/{portfolio_id}/metrics", headers=as_role(VIEWER))
        ).json()
        (figures,) = library.seen
        assert figures.sessions == 10 and figures.trades == body["trades"]
        assert figures.traded_notional > 0
        assert Decimal(body["total_return"]) == figures.values[-1] / Decimal(10000) - 1
        assert body["max_drawdown"] == "0.05"
        assert body["pending"] == ["volatility", "sharpe", "turnover"]


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "fills"),
        ("GET", "holdings"),
        ("GET", "holdings/history"),
        ("GET", "value-series"),
        ("GET", "state"),
        ("GET", "verify"),
        ("GET", "metrics"),
        ("POST", "rebuild"),
    ],
)
async def test_an_unknown_portfolio_is_404(method: str, route: str) -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.request(
            method, f"{API}/portfolios/{uuid.uuid4()}/{route}", headers=as_role(Role.ADMIN)
        )
        assert response.status_code == 404, response.text
        assert response.json()["type"] == "urn:quantsim:problem:not-found"


@pytest.mark.parametrize("route", ["fills", "holdings/history"])
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 2001}, {"after_seq": -1}])
async def test_bad_paging_parameters_are_422(route: str, params: dict[str, int]) -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http)
        response = await http.get(
            f"{API}/portfolios/{portfolio_id}/{route}", params=params, headers=as_role(VIEWER)
        )
        assert response.status_code == 422
