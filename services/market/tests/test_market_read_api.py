"""The read API for stored market data against a real database loaded through the real
pipeline runner. Each check states the ideal (what was ingested, what returns.compute
gives on the same bars) rather than re-running the route's own query."""

import json
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from qs_market import returns
from qs_market.models import data_gap
from qs_template import Database
from qs_template.auth import Role
from tests import read_support as support
from tests.instrument_support import API, bearer, make_token
from tests.read_support import (
    WINDOWS,
    add_instrument,
    get_json,
    pages,
    recorded,
)

client = support.client
database = support.database
loaded = support.loaded
pytestmark = pytest.mark.db


def expected_dates(symbol: str) -> list[str]:
    low, high = (d.isoformat() for d in WINDOWS[symbol])
    return sorted(r["date"][:10] for r in recorded(symbol) if low <= r["date"][:10] <= high)


def _refuse_float(value: str) -> None:
    raise AssertionError(f"a JSON number with a fraction, {value}")


async def all_bars(http: httpx.AsyncClient, instrument_id: uuid.UUID, **params: Any) -> list[Any]:
    return [
        item
        async for page in pages(http, f"/instruments/{instrument_id}/bars", **params)
        for item in page["items"]
    ]


async def test_bars_are_exactly_what_was_ingested(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    for symbol, instrument_id in loaded.items():
        page = await get_json(client, f"/instruments/{instrument_id}/bars")
        items = page["items"]
        assert [i["session_date"] for i in items] == expected_dates(symbol)
        assert page["next_cursor"] is None
        by_date = {r["date"][:10]: r for r in recorded(symbol)}
        for item in items:
            source = by_date[item["session_date"]]
            for field in ("open", "high", "low", "close", "volume"):
                assert Decimal(item[field]) == Decimal(str(source[field])), (symbol, item)
            assert Decimal(item["adj_close"]) == Decimal(str(source["adjClose"]))
            assert item["revision"] == 1
            assert item["quality_flags"] == []
            assert len(item["content_hash"]) > 10


async def test_every_decimal_is_a_string_and_never_a_float(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    instrument_id = loaded["AAPL"]
    for path in ("bars", "returns"):
        response = await client.get(
            f"{API}/instruments/{instrument_id}/{path}", headers=bearer(make_token(Role.VIEWER))
        )

        json.loads(response.text, parse_float=_refuse_float)
        for item in response.json()["items"]:
            for key, value in item.items():
                if key not in ("session_date", "revision", "quality_flags", "content_hash"):
                    assert value is None or isinstance(value, str), (path, key, value)
                    assert value is None or "e" not in value.lower(), (path, key, value)
    quote = await get_json(client, f"/instruments/{instrument_id}/quote")
    assert all(isinstance(quote[k], str) for k in ("price", "previous_close", "change_pct"))


async def test_pagination_returns_every_bar_exactly_once(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    wanted = expected_dates("AAPL")
    for limit in (1, 7, len(wanted) - 1, len(wanted), len(wanted) + 5):
        seen: list[str] = []
        sizes: list[int] = []
        async for page in pages(client, f"/instruments/{loaded['AAPL']}/bars", limit=limit):
            sizes.append(len(page["items"]))
            seen += [i["session_date"] for i in page["items"]]
            assert len(page["items"]) <= limit
        assert seen == wanted, f"limit {limit}"
        assert all(s == limit for s in sizes[:-1])


async def test_from_and_to_bound_the_bars_inclusively(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    wanted = expected_dates("AAPL")
    low, high = wanted[3], wanted[9]
    bars = await all_bars(client, loaded["AAPL"], **{"from": low, "to": high}, limit=4)
    assert [b["session_date"] for b in bars] == wanted[3:10]
    after = await all_bars(client, loaded["AAPL"], **{"from": "2030-01-01"})
    assert after == []


async def test_returns_equal_returns_compute_on_the_same_bars(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    for symbol, instrument_id in loaded.items():
        bars = await all_bars(client, instrument_id)
        points = [
            returns.PricePoint(
                date.fromisoformat(b["session_date"]),
                Decimal(b["close"]),
                Decimal(b["adj_close"]),
            )
            for b in bars
        ]
        ideal = returns.compute(points)
        stored = [
            item
            async for page in pages(client, f"/instruments/{instrument_id}/returns", limit=9)
            for item in page["items"]
        ]
        assert [s["session_date"] for s in stored] == [p.session_date.isoformat() for p in ideal]
        tolerance = Decimal("0.000000000001")
        for s, p in zip(stored, ideal, strict=True):
            for key in ("log_return", "adj_log_return", "vol_20d", "vol_60d"):
                want = getattr(p, key)
                if want is None:
                    assert s[key] is None, (symbol, s)
                else:
                    assert s[key] is not None
                    assert abs(Decimal(s[key]) - Decimal(repr(want))) <= tolerance, (symbol, key)
        # The first session has no previous close
        assert stored[0]["log_return"] is None


async def test_the_nvda_split_and_the_aapl_dividend_are_listed(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    nvda = await get_json(client, f"/instruments/{loaded['NVDA']}/corporate-actions")
    split = next(a for a in nvda if a["session_date"] == "2024-06-10")
    assert split["kind"] == "split"
    assert Decimal(split["split_factor"]) == 10
    assert any(a["kind"] == "dividend" for a in nvda)
    aapl = await get_json(client, f"/instruments/{loaded['AAPL']}/corporate-actions")
    assert [(a["session_date"], a["kind"], Decimal(a["dividend"])) for a in aapl] == [
        ("2024-02-09", "dividend", Decimal("0.24"))
    ]
    assert [a["session_date"] for a in nvda] == sorted(a["session_date"] for a in nvda)


async def test_gaps_filter_by_status(
    client: httpx.AsyncClient, database: Database, loaded: dict[str, uuid.UUID]
) -> None:
    run_id = uuid.uuid4()
    async with database.transaction() as session:
        for day, resolved in (("2024-01-10", False), ("2024-01-11", True), ("2024-01-12", False)):
            await session.execute(
                data_gap.insert().values(
                    instrument_id=loaded["AAPL"],
                    session_date=date.fromisoformat(day),
                    opened_by_run=run_id,
                    resolved_by_run=run_id if resolved else None,
                    resolved_at=datetime.now(UTC) if resolved else None,
                )
            )
    path = f"/instruments/{loaded['AAPL']}/gaps"
    everything = await get_json(client, path)
    assert [(g["session_date"], g["status"]) for g in everything] == [
        ("2024-01-10", "open"),
        ("2024-01-11", "resolved"),
        ("2024-01-12", "open"),
    ]
    open_ = await get_json(client, path, status="open")
    assert [g["session_date"] for g in open_] == ["2024-01-10", "2024-01-12"]
    resolved = await get_json(client, path, status="resolved")
    assert [g["session_date"] for g in resolved] == ["2024-01-11"]
    assert resolved[0]["resolved_at"] is not None
    assert await get_json(client, f"/instruments/{loaded['NVDA']}/gaps") == []
    bad = await client.get(
        f"{API}{path}", params={"status": "maybe"}, headers=bearer(make_token(Role.VIEWER))
    )
    assert bad.status_code == 422


async def test_the_quote_is_the_last_two_clean_closes(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    dates = expected_dates("AAPL")
    by_date = {r["date"][:10]: Decimal(str(r["close"])) for r in recorded("AAPL")}
    latest, previous = by_date[dates[-1]], by_date[dates[-2]]
    quote = await get_json(client, f"/instruments/{loaded['AAPL']}/quote")
    assert quote["as_of"] == dates[-1]
    assert Decimal(quote["price"]) == latest
    assert Decimal(quote["previous_close"]) == previous
    ideal = ((latest - previous) / previous * 100).quantize(Decimal("0.01"))
    assert Decimal(quote["change_pct"]) == ideal
    listed = await get_json(client, "/instruments")
    row = next(i for i in listed if i["symbol"] == "AAPL")
    assert (row["price"], row["change_pct"]) == (quote["price"], quote["change_pct"])


async def test_an_instrument_without_bars_has_an_empty_quote_and_no_bars(
    client: httpx.AsyncClient, database: Database
) -> None:
    empty = await add_instrument(database, "EMPTY")
    quote = await get_json(client, f"/instruments/{empty}/quote")
    assert quote["price"] is None and quote["as_of"] is None and quote["change_pct"] is None
    page = await get_json(client, f"/instruments/{empty}/bars")
    assert page == {"items": [], "next_cursor": None}


async def test_data_quality_has_one_correct_row_per_active_instrument(
    client: httpx.AsyncClient, database: Database, loaded: dict[str, uuid.UUID]
) -> None:
    await add_instrument(database, "EMPTY")
    async with database.transaction() as session:
        await session.execute(
            text(
                "UPDATE bar SET quality_flags = '[\"outlier\"]'::jsonb"
                " WHERE instrument_id = :i AND session_date IN ('2024-01-03', '2024-01-04')"
            ),
            {"i": loaded["AAPL"]},
        )
        await session.execute(
            text(
                "INSERT INTO data_gap (instrument_id, session_date, opened_by_run)"
                " VALUES (:i, '2024-01-10', :r)"
            ),
            {"i": loaded["AAPL"], "r": uuid.uuid4()},
        )
    rows = await get_json(client, "/data-quality", Role.ANALYST)
    by_symbol = {r["symbol"]: r for r in rows}
    assert list(by_symbol) == ["AAPL", "EMPTY", "NVDA"]
    for symbol in ("AAPL", "NVDA"):
        row = by_symbol[symbol]
        assert row["bar_count"] == len(expected_dates(symbol))
        assert row["last_session"] == expected_dates(symbol)[-1]
        assert row["rejected_total"] == 0
        assert row["last_run_status"] == "succeeded"
        assert row["last_run_id"] is not None
    assert (by_symbol["AAPL"]["flagged_bars"], by_symbol["AAPL"]["open_gaps"]) == (2, 1)
    assert (by_symbol["NVDA"]["flagged_bars"], by_symbol["NVDA"]["open_gaps"]) == (0, 0)
    assert by_symbol["EMPTY"] == {
        "instrument_id": by_symbol["EMPTY"]["instrument_id"],
        "symbol": "EMPTY",
        "last_session": None,
        "bar_count": 0,
        "open_gaps": 0,
        "flagged_bars": 0,
        "rejected_total": 0,
        "last_run_id": None,
        "last_run_status": None,
    }


async def test_retired_instruments_are_left_out_of_data_quality(
    client: httpx.AsyncClient, database: Database, loaded: dict[str, uuid.UUID]
) -> None:
    async with database.transaction() as session:
        await session.execute(
            text("UPDATE instrument SET status = 'retired', retired_at = now() WHERE symbol='NVDA'")
        )
    rows = await get_json(client, "/data-quality", Role.QUANT)
    assert [r["symbol"] for r in rows] == ["AAPL"]


async def test_data_quality_runs_the_same_statements_for_any_number_of_instruments(
    client: httpx.AsyncClient, database: Database, loaded: dict[str, uuid.UUID]
) -> None:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    async def measure() -> int:
        statements.clear()
        await get_json(client, "/data-quality", Role.ADMIN)
        return len(statements)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        before = await measure()
        for n in range(8):
            await add_instrument(database, f"X{n}")
        after = await measure()
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert before == after
    assert after <= 2


async def test_unknown_instrument_is_404_on_every_route(client: httpx.AsyncClient) -> None:
    headers = bearer(make_token(Role.VIEWER))
    for path in ("bars", "returns", "corporate-actions", "gaps", "quote"):
        response = await client.get(f"{API}/instruments/{uuid.uuid4()}/{path}", headers=headers)
        assert response.status_code == 404, path


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2024-02-01", "to": "2024-01-01"},
        {"limit": "0"},
        {"limit": "2001"},
        {"cursor": "not-a-date"},
        {"from": "yesterday"},
    ],
)
async def test_bad_query_parameters_are_422(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID], params: dict[str, str]
) -> None:
    for path in ("bars", "returns"):
        response = await client.get(
            f"{API}/instruments/{loaded['AAPL']}/{path}",
            params=params,
            headers=bearer(make_token(Role.VIEWER)),
        )
        assert response.status_code == 422, (path, params, response.text)


async def test_the_role_matrix(client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]) -> None:
    target = loaded["AAPL"]
    for role in Role:
        headers = bearer(make_token(role))
        for path in ("bars", "returns", "corporate-actions", "gaps", "quote"):
            response = await client.get(f"{API}/instruments/{target}/{path}", headers=headers)
            assert response.status_code == 200, (role, path)
        quality = await client.get(f"{API}/data-quality", headers=headers)
        assert quality.status_code == (403 if role is Role.VIEWER else 200), role
    anonymous = await client.get(f"{API}/instruments/{target}/bars")
    assert anonymous.status_code == 401
    assert (await client.get(f"{API}/data-quality")).status_code == 401


async def test_the_first_page_of_a_large_instrument_is_fast(
    client: httpx.AsyncClient, database: Database
) -> None:
    big = await add_instrument(database, "BIG")
    async with database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO bar (instrument_id, session_date, ts, open, high, low, close,"
                " volume, adj_close, content_hash, run_id, vendor, ruleset_version)"
                " SELECT :i, d::date, d + interval '21 hours', 10, 12, 9, 11, 1000, 11, 'h',"
                " :r, 'fixture', 'v1'"
                " FROM generate_series(date '2010-01-01', date '2010-01-01' + 2999,"
                " interval '1 day') AS g(d)"
            ),
            {"i": big, "r": uuid.uuid4()},
        )
    await get_json(client, f"/instruments/{big}/quote")  # warm the connection pool
    started = time.perf_counter()
    page = await get_json(client, f"/instruments/{big}/bars", limit=2000)
    elapsed = time.perf_counter() - started
    assert len(page["items"]) == 2000
    assert page["next_cursor"] == page["items"][-1]["session_date"]
    assert elapsed < 1.0, f"{elapsed:.2f}s"
    rest = await get_json(
        client, f"/instruments/{big}/bars", limit=2000, cursor=page["next_cursor"]
    )
    assert len(rest["items"]) == 1000 and rest["next_cursor"] is None
