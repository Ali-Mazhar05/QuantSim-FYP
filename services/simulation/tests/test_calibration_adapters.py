"""The adapters of the calibration ports (B15): the market source, the file source over the recorded
fixture and the K5 calibrator. No database and no network."""

import sys
import types
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from qs_simulation.adapters.calibrators import DT, QuantCalibrator
from qs_simulation.adapters.price_sources import MAX_PAGES, FilePriceSource, MarketPriceSource
from qs_simulation.domain.calibration import (
    MISSING_ADJUSTED_PRICES,
    CalibrationRefused,
    log_prices,
    log_returns,
)
from qs_simulation.ports import CalibratorUnavailable, InstrumentNotFound, PriceSourceError
from qs_template.errors import ServiceError
from tests.calibration_support import AAPL, make_points

FIXTURE = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "replay_ticks_2020.json"
ID = uuid.uuid4()


def bar(day: str, adj: str | None = "100.5", revision: int = 1) -> dict[str, Any]:
    return {
        "session_date": day,
        "open": "1",
        "high": "1",
        "low": "1",
        "close": "1",
        "volume": "1",
        "adj_close": adj,
        "quality_flags": [],
        "revision": revision,
        "content_hash": "h",
    }


class FakeGetter:
    """Answers from a list of pages (or raises what it is told), and remembers every call."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get_json(self, path: str, *, params: Any = None) -> Any:
        self.calls.append((path, dict(params) if params else None))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


# ---- the market source ----


async def test_the_market_source_follows_the_cursor_and_reads_every_close() -> None:
    getter = FakeGetter(
        {"items": [bar("2024-01-02"), bar("2024-01-03", "101")], "next_cursor": "2024-01-03"},
        {"items": [bar("2024-01-04", "102", revision=2)], "next_cursor": None},
    )
    points = await MarketPriceSource(getter).window(ID, date(2024, 1, 1), date(2024, 2, 1))
    assert [(p.session_date.isoformat(), p.adj_close, p.revision) for p in points] == [
        ("2024-01-02", Decimal("100.5"), 1),
        ("2024-01-03", Decimal("101"), 1),
        ("2024-01-04", Decimal("102"), 2),
    ]
    first, second = getter.calls
    assert first == (
        f"/api/market/instruments/{ID}/bars",
        {"from": "2024-01-01", "to": "2024-02-01", "limit": 2000},
    )
    assert second[1] is not None and second[1]["cursor"] == "2024-01-03"


async def test_a_bar_without_an_adjusted_close_refuses_and_a_raw_price_is_never_used() -> None:
    getter = FakeGetter(
        {"items": [bar("2024-01-02"), bar("2024-01-03", None)], "next_cursor": None}
    )
    with pytest.raises(CalibrationRefused) as refused:
        await MarketPriceSource(getter).window(ID, date(2024, 1, 1), date(2024, 2, 1))
    assert refused.value.code == MISSING_ADJUSTED_PRICES and "2024-01-03" in refused.value.reason


async def test_a_close_that_is_not_a_number_refuses() -> None:
    getter = FakeGetter({"items": [bar("2024-01-02", "abc")], "next_cursor": None})
    with pytest.raises(CalibrationRefused):
        await MarketPriceSource(getter).window(ID, date(2024, 1, 1), date(2024, 2, 1))


async def test_a_404_from_market_is_an_unknown_instrument_whichever_way_it_arrives() -> None:
    direct = ServiceError(404, "Not found", "no such instrument")
    wrapped = ServiceError(
        502, "Upstream error", "market answered 404", extra={"upstream_status": 404}
    )
    for error in (direct, wrapped):
        source = MarketPriceSource(FakeGetter(error))
        with pytest.raises(InstrumentNotFound):
            await source.instrument(ID)


@pytest.mark.parametrize(
    "error",
    [
        ServiceError(502, "Upstream error", extra={"upstream_status": 500}),
        ServiceError(503, "Service unavailable", "circuit open"),
        TimeoutError("slow"),
        ConnectionRefusedError("down"),
    ],
)
async def test_any_other_failure_is_a_price_source_error_that_the_job_retries(
    error: BaseException,
) -> None:
    source = MarketPriceSource(FakeGetter(error))
    with pytest.raises(PriceSourceError):
        await source.window(ID, date(2024, 1, 1), date(2024, 2, 1))


async def test_a_cursor_that_never_ends_is_stopped() -> None:
    forever = {"items": [bar("2024-01-02")], "next_cursor": "2024-01-02"}
    source = MarketPriceSource(FakeGetter(*[forever] * (MAX_PAGES + 1)))
    with pytest.raises(PriceSourceError, match="past the limit"):
        await source.window(ID, date(2024, 1, 1), date(2024, 2, 1))


async def test_the_instrument_is_read_with_its_symbol_and_name() -> None:
    info = await MarketPriceSource(
        FakeGetter({"symbol": "AAPL", "name": "Apple Inc.", "status": "active", "id": str(ID)})
    ).instrument(ID)
    assert (info.symbol, info.name, info.status) == ("AAPL", "Apple Inc.", "active")


# ---- the file source over the recorded fixture ----


async def test_the_file_source_gives_the_closes_the_replay_feed_serves() -> None:
    source = FilePriceSource(FIXTURE)
    info = await source.instrument(AAPL)
    assert info.symbol == "AAPL"
    points = await source.window(AAPL, date(2020, 1, 1), date(2020, 12, 31))
    assert len(points) == 253 and points[0].session_date == date(2020, 1, 2)
    assert points[-1].session_date == date(2020, 12, 31)
    assert all(p.adj_close > 0 and p.revision == 1 for p in points)
    spring = await source.window(AAPL, date(2020, 3, 1), date(2020, 3, 31))
    assert len(spring) == 22 and all(p.session_date.month == 3 for p in spring)


async def test_the_file_source_does_not_know_other_instruments() -> None:
    source = FilePriceSource(FIXTURE)
    with pytest.raises(InstrumentNotFound):
        await source.instrument(uuid.uuid4())
    with pytest.raises(InstrumentNotFound):
        await source.window(uuid.uuid4(), date(2020, 1, 1), date(2020, 12, 31))


# ---- the K5 calibrator ----


def install_fake_quant(**functions: Any) -> str:
    package = types.ModuleType("fake_quant")
    package.__version__ = "9.9.9"  # type: ignore[attr-defined]
    module = types.ModuleType("fake_quant.calibration")
    for name, function in functions.items():
        setattr(module, name, function)
    sys.modules["fake_quant"] = package
    sys.modules["fake_quant.calibration"] = module
    return "fake_quant.calibration"


@pytest.fixture(autouse=True)
def _remove_fake_quant() -> Any:
    yield
    sys.modules.pop("fake_quant", None)
    sys.modules.pop("fake_quant.calibration", None)


def test_without_the_quant_library_nothing_can_be_calibrated_and_it_says_so() -> None:
    calibrator = QuantCalibrator("no_such_package.calibration")
    assert calibrator.version == "unavailable"
    assert not any(calibrator.supports(m) for m in ("gbm", "ou", "merton"))
    with pytest.raises(CalibratorUnavailable) as unavailable:
        calibrator.fit("gbm", make_points(80))
    assert unavailable.value.model == "gbm"


def test_the_calibrator_hands_log_returns_to_gbm_and_log_prices_to_ou_with_dt() -> None:
    seen: dict[str, Any] = {}

    class Result:
        params = {"a": 1}  # noqa: RUF012
        std_errors = {"a": float("nan")}  # noqa: RUF012
        log_likelihood = 12.5
        aic = -21.0
        n_obs = 79
        converged = True
        refusal_reason = None

    def fit_gbm(returns: np.ndarray, dt: float) -> Result:
        seen["gbm"] = (returns, dt)
        return Result()

    def fit_ou(prices: np.ndarray, dt: float) -> Result:
        seen["ou"] = (prices, dt)
        return Result()

    calibrator = QuantCalibrator(install_fake_quant(fit_gbm=fit_gbm, fit_ou=fit_ou))
    points = make_points(80)
    gbm = calibrator.fit("gbm", points)
    calibrator.fit("ou", points)
    assert np.array_equal(seen["gbm"][0], log_returns(points)) and seen["gbm"][1] == DT == 1 / 252
    assert np.array_equal(seen["ou"][0], log_prices(points)) and seen["ou"][1] == DT
    assert (gbm.model, gbm.params, gbm.n_obs, gbm.converged) == ("gbm", {"a": 1.0}, 79, True)
    assert np.isnan(gbm.std_errors["a"]) and gbm.refusal_reason is None
    assert calibrator.version == "9.9.9"


def test_a_model_the_library_has_not_delivered_is_unsupported_not_faked() -> None:
    calibrator = QuantCalibrator(install_fake_quant(fit_gbm=lambda r, dt: None))
    assert calibrator.supports("gbm") and not calibrator.supports("merton")
    with pytest.raises(CalibratorUnavailable):
        calibrator.fit("merton", make_points(600))


def test_a_refusal_from_the_library_is_carried_not_raised() -> None:
    class Refusal:
        params: dict[str, float] = {}  # noqa: RUF012
        std_errors: dict[str, float] = {}  # noqa: RUF012
        log_likelihood = 0.0
        aic = 0.0
        n_obs = 100
        converged = False
        refusal_reason = "series is not mean-reverting (ADF p = 0.41)"

    calibrator = QuantCalibrator(install_fake_quant(fit_ou=lambda x, dt: Refusal()))
    fit = calibrator.fit("ou", make_points(100))
    assert fit.refusal_reason == "series is not mean-reverting (ADF p = 0.41)"
