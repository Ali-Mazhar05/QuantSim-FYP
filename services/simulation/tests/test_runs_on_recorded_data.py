"""B16 on recorded data and at demo size (B-NFR-03; the plan combination test): five recorded names
are calibrated through the real calibration route, simulated correlated through the real run route,
and the stored paths are checked against the history they were calibrated on."""

import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from qs_simulation.adapters.correlation_sources import FileCorrelationSource
from qs_simulation.adapters.price_sources import FilePriceSource
from qs_template.auth import Role
from tests.auth_support import API, bearer, make_token
from tests.calibration_support import reference_gbm
from tests.run_support import RUNS, RunWorld, run_body
from tests.test_runs import complete, poll, stored_paths

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
NAMES = ("AAPL", "MSFT", "NVDA", "TSLA", "KO")
SESSIONS_PER_YEAR = 252


async def test_five_recorded_names_calibrated_then_simulated_match_the_history_they_came_from(
    run_world: RunWorld,
) -> None:
    prices = FilePriceSource(FIXTURES / "replay_ticks_2020.json")
    ids = [i for symbol in NAMES for i, s in prices._symbols.items() if s == symbol]
    for instrument_id in ids:
        run_world.source.add(instrument_id, prices._closes[instrument_id])
        run_world.source.symbols[instrument_id] = prices._symbols[instrument_id]
    history = {i: prices._closes[i] for i in ids}
    # the recorded correlation window for these names, as the run will be given it
    recorded = await FileCorrelationSource(
        FIXTURES / "correlation_rolling_60_5.json", prices
    ).matrix(ids, date(2020, 1, 1), date(2020, 12, 31))
    run_world.correlations.full = np.array(recorded.values)

    # calibrate each name on 2020 through the real route and worker
    quant = bearer(make_token(Role.QUANT))
    calibrations: list[tuple[uuid.UUID, uuid.UUID]] = []
    for instrument_id in ids:
        response = await run_world.client.post(
            f"{API}/calibrations",
            json={
                "instrument_id": str(instrument_id),
                "model": "gbm",
                "window_start": "2020-01-01",
                "window_end": "2020-12-31",
            },
            headers=quant,
        )
        assert response.status_code == 202, response.text
        calibrations.append((instrument_id, uuid.UUID(response.json()["id"])))
    await run_world.run_jobs()

    done = await complete(
        run_world, run_body(calibrations, n_paths=900, n_steps=SESSIONS_PER_YEAR, seed=2020)
    )
    assert done["status"] == "completed" and done["storage_mode"] == "full"
    assert done["symbols"] == list(NAMES)
    stored = await stored_paths(run_world, done["id"], 5, 900, SESSIONS_PER_YEAR)
    paths = np.vectorize(float)(stored)

    # the start prices are the last recorded closes of 2020
    for position, instrument_id in enumerate(ids):
        [row] = await run_world.sql(
            "SELECT s0 FROM run_instrument WHERE run_id = :r AND position = :p",
            r=uuid.UUID(done["id"]),
            p=position,
        )
        assert float(row.s0) == pytest.approx(float(history[instrument_id][-1].adj_close), abs=1e-9)

    s0 = np.array([float(history[i][-1].adj_close) for i in ids])
    log_paths = np.log(np.concatenate([s0[None, None, :].repeat(900, 0), paths], axis=1))
    steps = np.diff(log_paths, axis=1)  # (paths, steps, names): the simulated daily log returns
    dt = 1 / SESSIONS_PER_YEAR
    for position, instrument_id in enumerate(ids):
        fit = reference_gbm(history[instrument_id])
        mu, sigma = fit.params["mu"], fit.params["sigma"]
        # volatility: the simulated daily vol is the calibrated one, to well within sampling error
        daily = steps[:, :, position]
        assert daily.std() / np.sqrt(dt) == pytest.approx(sigma, rel=0.02), NAMES[position]
        # drift: the mean terminal log price is log S0 + (mu - sigma^2 / 2) T
        terminal = log_paths[:, -1, position]
        expected = np.log(s0[position]) + (mu - sigma**2 / 2) * 1.0
        standard_error = sigma / np.sqrt(900)
        assert abs(terminal.mean() - expected) < 4 * standard_error, NAMES[position]
    # dependence: the simulated daily returns correlate as the recorded window says
    sample = np.corrcoef(steps.reshape(-1, 5), rowvar=False)
    assert np.allclose(sample, recorded.values, atol=0.01), np.abs(sample - recorded.values).max()
    assert done["median_path_index"] is not None and 0 <= done["median_path_index"] < 900
    # the statistics are about the same paths
    for position, stat in enumerate(done["statistics"]):
        terminal_prices = paths[:, -1, position]
        assert float(stat["mean_price"]) == pytest.approx(terminal_prices.mean(), abs=1e-9)
        assert float(stat["median_price"]) == pytest.approx(np.median(terminal_prices), abs=1e-9)


async def test_the_demo_run_of_five_names_1000_paths_252_steps_completes_and_is_timed(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(5)
    queued_at = time.perf_counter()
    response = await run_world.client.post(
        RUNS,
        json=run_body(basket, n_paths=1000, n_steps=252),
        headers=bearer(make_token(Role.QUANT)),
    )
    assert response.status_code == 202
    submitted = time.perf_counter() - queued_at
    began = time.perf_counter()
    await run_world.run_jobs()
    ran = time.perf_counter() - began
    done: dict[str, Any] = await poll(run_world, response.json()["id"])
    assert done["status"] == "completed" and done["storage_mode"] == "full"
    [rows] = await run_world.sql("SELECT count(*) AS n FROM path_value")
    assert rows.n == 1_260_000
    # measured on the development machine (generation, statistics, COPY of 1.26 million rows):
    # about 75 s here and 150 s on a loaded machine (PostgreSQL checks the foreign key of
    # path_value row by row, DL-041); the bound catches a regression of several times
    assert submitted < 0.8, f"submit took {submitted:.2f}s"
    assert ran < 300, f"the demo run took {ran:.1f}s"
    print(f"\nDEMO submit={submitted * 1000:.0f} ms, run={ran:.1f} s, rows={rows.n}")
