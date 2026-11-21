"""C3: the recorded fixtures in ``contracts/fixtures/``, made from the recorded Tiingo corpus and
never edited by hand.

The recorded bars go through the real ingestion pipeline into a real database, with fixed
instrument and environment ids, and the replay ticks are built by the same function the replay feed
uses (``qs_market.feeds``). The correlation fixture is the real ``POST /correlations`` answer.

    uv run python scripts/make-fixtures.py            # write the files
    uv run python scripts/make-fixtures.py --check    # fail if a committed file is stale

Without the corpus (it is never committed) these tests are skipped; tests/test_fixtures.py checks
the committed files everywhere."""

import json
import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import xxhash
from sqlalchemy import insert, select

from qs_market import calendars, feeds
from qs_market.models import bar, instrument
from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.contract_support import FIXTURES, tick_problems
from tests.instrument_support import API, bearer, make_token
from tests.read_support import ingest
from tests.realdata.conftest import CORPUS_DIR

client = support.client
database = support.database
pytestmark = pytest.mark.db

WRITE = os.environ.get("QS_WRITE_FIXTURES") == "1"
NAMESPACE = uuid.UUID("c3a9d1f0-5b7e-4c2a-9f61-0d8e4b2a7c15")  # fixed, so ids never change
SYMBOLS = ("AAPL", "MSFT", "NVDA", "TSLA", "KO", "SPY")
REPLAY_SYMBOLS = ("AAPL", "MSFT", "NVDA", "TSLA", "KO")
SYNTHETIC_SYMBOLS = ("AAPL", "MSFT", "NVDA")
INGEST_WINDOW = (date(2019, 1, 2), date(2021, 12, 31))
REPLAY_WINDOW = (date(2020, 1, 2), date(2020, 12, 31))
CREATOR = uuid.uuid5(NAMESPACE, "fixture-user")
REGENERATE = "uv run python scripts/make-fixtures.py"


def fixed(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


class CorpusSource:
    """The recorded corpus as a vendor: the same rows the pipeline's gate takes."""

    name = "fixture"

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        document = json.loads((CORPUS_DIR / f"{symbol}.json").read_text(encoding="utf-8"))
        return [r for r in document["records"] if start <= date.fromisoformat(r["date"]) <= end]


# ---- one file per fixture, one tick or one small record per line so a diff reads ----


def _flat(value: Any) -> bool:
    return not isinstance(value, dict | list)


def _is_leaf(value: Any) -> bool:
    if isinstance(value, dict):
        return all(
            _flat(v) or (isinstance(v, list) and all(_flat(x) for x in v)) for v in value.values()
        )
    return False


def render(value: Any, level: int = 0) -> str:
    """JSON where a record of only scalars sits on one line, so ticks and matrix rows diff well."""
    pad = "  " * level
    inner = "  " * (level + 1)
    if isinstance(value, dict):
        if _is_leaf(value):
            return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
        body = ",\n".join(
            f"{inner}{json.dumps(k)}: {render(v, level + 1)}" for k, v in value.items()
        )
        return "{\n" + body + "\n" + pad + "}"
    if isinstance(value, list):
        if all(_flat(v) for v in value):
            return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
        return (
            "[\n" + ",\n".join(f"{inner}{render(v, level + 1)}" for v in value) + "\n" + pad + "]"
        )
    return json.dumps(value, ensure_ascii=False)


def meta(kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "contract": "market.tick.v1" if kind != "correlation" else "POST /api/market/correlations",
        "made_by": "scripts/make-fixtures.py; never edit by hand",
        "regenerate": REGENERATE,
        "source": "recorded Tiingo corpus through the real ingestion pipeline",
        **extra,
    }


# ---- building the documents ----


async def load_corpus(database: Database) -> dict[str, uuid.UUID]:
    ids = {symbol: fixed(f"instrument:{symbol}") for symbol in SYMBOLS}
    async with database.transaction() as session:
        for symbol, new_id in ids.items():
            await session.execute(
                insert(instrument).values(
                    id=new_id,
                    symbol=symbol,
                    name=symbol,
                    sector="Fixture",
                    exchange="XNAS",
                    calendar="XNYS",
                    currency="USD",
                    asset_class="etf" if symbol == "SPY" else "equity",
                    vendor_symbol=symbol,
                )
            )
    await ingest(database, CorpusSource(), list(ids.values()), INGEST_WINDOW)
    return ids


async def stored_rows(
    database: Database, ids: list[uuid.UUID], window: tuple[date, date]
) -> list[feeds.BarRow]:
    async with database.transaction() as session:
        result = await session.execute(
            select(
                bar.c.instrument_id,
                instrument.c.symbol,
                bar.c.session_date,
                bar.c.ts,
                bar.c.revision,
                bar.c.adj_open,
                bar.c.adj_high,
                bar.c.adj_low,
                bar.c.adj_close,
                bar.c.adj_volume,
            )
            .join(instrument, instrument.c.id == bar.c.instrument_id)
            .where(bar.c.instrument_id.in_(ids), bar.c.session_date.between(*window))
        )
        return [
            feeds.BarRow(
                r.instrument_id,
                r.symbol,
                r.session_date,
                r.ts,
                r.revision,
                r.adj_open,
                r.adj_high,
                r.adj_low,
                r.adj_close,
                r.adj_volume,
            )
            for r in result.all()
        ]


def replay_document(ids: dict[str, uuid.UUID], rows: list[feeds.BarRow]) -> dict[str, Any]:
    env_id = fixed("environment:replay-2020")
    fingerprint = feeds.fingerprint(rows)
    ticks = feeds.build_ticks(rows, env_id=env_id, source_fingerprint=fingerprint)
    return {
        "meta": meta("replay", note="Five names, every 2020 session; adjusted prices as stored"),
        "environment": {
            "id": str(env_id),
            "name": "Big five 2020 replay",
            "type": "historical_replay",
            "frequency": "daily",
            "start_date": REPLAY_WINDOW[0].isoformat(),
            "end_date": REPLAY_WINDOW[1].isoformat(),
            "instruments": [{"id": str(ids[s]), "symbol": s} for s in REPLAY_SYMBOLS],
            "source_fingerprint": fingerprint,
            "tick_count": len(ticks),
        },
        "items": ticks,
        "next_after_seq": None,
    }


def synthetic_document(ids: dict[str, uuid.UUID], anchors: dict[str, Decimal]) -> dict[str, Any]:
    """Three correlated GBM paths for three names, started from their last 2020 close. Illustrative
    and seeded (42), not a recorded run; the generators in qs_simulation produce the same kind."""
    steps, paths, dt = 60, 3, 1 / 252
    s0 = np.array([float(anchors[s]) for s in SYNTHETIC_SYMBOLS])
    mu = np.array([0.08, 0.07, 0.15])
    sigma = np.array([0.35, 0.30, 0.55])
    rho = np.array([[1.0, 0.6, 0.5], [0.6, 1.0, 0.55], [0.5, 0.55, 1.0]])
    shocks = (
        np.random.default_rng(42).standard_normal((paths, steps, 3)) @ np.linalg.cholesky(rho).T
    )
    prices = s0 * np.exp(
        np.cumsum((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks, axis=1)
    )
    # real NYSE sessions after the replay window, and their real closes (21:00 or 20:00 UTC)
    sessions = calendars.sessions("XNYS", date(2021, 1, 1), date(2021, 6, 30))[:steps]
    closes = [feeds.utc_text(calendars.session_close("XNYS", day)) for day in sessions]
    # ADR 03: rank the paths by the terminal value of the equal-weighted basket of normalised prices
    # and take the lower median; ties go to the lowest path index
    basket = (prices[:, -1, :] / s0).mean(axis=1)
    median_path = int(np.argsort(basket, kind="stable")[(paths - 1) // 2])
    run_id = fixed("run:synthetic-demo")
    config = f"gbm|seed=42|paths={paths}|steps={steps}|{','.join(SYNTHETIC_SYMBOLS)}"
    fingerprint = feeds.FINGERPRINT_PREFIX + xxhash.xxh3_128(config.encode()).hexdigest()
    scale = Decimal("1E-10")
    documents: list[dict[str, Any]] = []
    for path in range(paths):
        items: list[dict[str, Any]] = []
        for step in range(steps):
            for column, symbol in enumerate(SYNTHETIC_SYMBOLS):
                price = format(
                    Decimal(repr(float(prices[path, step, column]))).quantize(scale), "f"
                )
                items.append(
                    {
                        "env_id": str(run_id),
                        "env_type": "synthetic",
                        "source_fingerprint": fingerprint,
                        "seq": len(items) + 1,
                        "session": step,
                        "ts": closes[step],
                        "instrument_id": str(ids[symbol]),
                        "symbol": symbol,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": "0.00000000",
                        "path_index": path,
                        "scenario": None,
                    }
                )
        documents.append({"path_index": path, "items": items, "next_after_seq": None})
    return {
        "meta": meta(
            "synthetic",
            source="generated from a seed, not recorded",
            note="Illustrative correlated GBM, seed 42; one price per step, so open, high, low and "
            "close are equal and volume is zero. Starts from the last 2020 close of each name.",
        ),
        "run": {
            "id": str(run_id),
            "model": "gbm",
            "seed": 42,
            "n_paths": paths,
            "n_steps": steps,
            "symbols": list(SYNTHETIC_SYMBOLS),
            "source_fingerprint": fingerprint,
            "median_path_index": median_path,
        },
        "paths": documents,
    }


async def correlation_document(http: httpx.AsyncClient) -> dict[str, Any]:
    request = {
        "symbols": list(SYMBOLS),
        "rolling": {"length": 60, "step": 5, "start": "2019-01-02", "end": "2021-12-31"},
    }
    response = await http.post(
        f"{API}/correlations", json=request, headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 200, response.text
    return {
        "meta": meta(
            "correlation",
            note="Six recorded names (the corpus holds six); regenerated for the 40-name universe "
            "once that data is loaded",
            request=request,
        ),
        **response.json(),
    }


# ---- the test ----


async def test_the_committed_fixtures_are_what_the_recorded_corpus_makes(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = await load_corpus(database)
    replay_ids = [ids[s] for s in REPLAY_SYMBOLS]
    rows = await stored_rows(database, replay_ids, REPLAY_WINDOW)
    assert {r.symbol for r in rows} == set(REPLAY_SYMBOLS)
    anchors = {
        s: max((r for r in rows if r.symbol == s), key=lambda r: r.session_date).adj_close
        for s in SYNTHETIC_SYMBOLS
    }
    assert all(a is not None for a in anchors.values())
    made = {
        "replay_ticks_2020.json": replay_document(ids, rows),
        "synthetic_ticks.json": synthetic_document(ids, {k: v for k, v in anchors.items() if v}),
        "correlation_rolling_60_5.json": await correlation_document(client),
    }
    for document in made.values():
        for tick in document.get("items", []) + [
            t for p in document.get("paths", []) for t in p["items"]
        ]:
            assert tick_problems(tick) == [], tick

    stale = settle(made)
    assert not stale, f"stale or missing fixtures {stale}; run {REGENERATE}"


def settle(made: dict[str, dict[str, Any]]) -> list[str]:
    """Write the files when asked to; otherwise name the ones that differ from what is made."""
    stale = []
    for name, document in made.items():
        text = render(document) + "\n"
        path: Path = FIXTURES / name
        if WRITE:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.exists() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            stale.append(name)
    return stale
