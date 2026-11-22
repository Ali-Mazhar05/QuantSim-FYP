"""The adapters a run reads through (B16): correlation from the market service or a recorded file,
and VaR/CVaR from K6 when it is installed. No database and no network."""

import sys
import types
import uuid
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from qs_simulation.adapters.correlation_sources import (
    MIN_OBSERVATIONS,
    FileCorrelationSource,
    MarketCorrelationSource,
    assemble,
)
from qs_simulation.adapters.price_sources import FilePriceSource
from qs_simulation.adapters.risk import QuantRisk, ReferenceRisk, default_risk, reference_var_cvar
from qs_simulation.domain.runs import CORRELATION_UNAVAILABLE, RunRefused
from qs_simulation.ports import CorrelationUnavailable, InstrumentNotFound
from qs_template.errors import ServiceError
from tests.calibration_support import AAPL, ScriptedSource, make_points

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
START, END = date(2020, 1, 2), date(2020, 12, 31)


def directory() -> ScriptedSource:
    """Knows A, B and C as MSFT, AAPL and KO (so the market's alphabetical order differs)."""
    source = ScriptedSource()
    for instrument_id in (A, B, C):
        source.add(instrument_id, make_points(5))
    return source


class NamedSource(ScriptedSource):
    names: ClassVar[dict[uuid.UUID, str]] = {A: "MSFT", B: "AAPL", C: "KO"}

    async def instrument(self, instrument_id: uuid.UUID) -> Any:
        info = await super().instrument(instrument_id)
        return type(info)(instrument_id, self.names[instrument_id], "n", "active")


def named() -> NamedSource:
    source = NamedSource()
    for instrument_id in (A, B, C):
        source.add(instrument_id, make_points(5))
    return source


def answer(**override: Any) -> dict[str, Any]:
    """What the market service answers for AAPL, KO, MSFT (its alphabetical order)."""
    window: dict[str, Any] = {
        "start": "2020-01-02",
        "end": "2020-12-31",
        "n_obs": 252,
        "fingerprint": "f",
        "symbols": ["AAPL", "KO", "MSFT"],
        "matrix": [
            ["1.00000000", "0.30000000", "0.80000000"],
            ["0.30000000", "1.00000000", "0.20000000"],
            ["0.80000000", "0.20000000", "1.00000000"],
        ],
        "unavailable": [],
    }
    window.update(override)
    return {"method": "pearson", "method_version": 1, "min_observations": 20, "windows": [window]}


class FakePoster:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, Any]] = []

    async def post_json(self, path: str, *, json: Any) -> Any:
        self.calls.append((path, json))
        result = self.answers.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


# ---- the market source ----


async def test_the_market_source_asks_for_the_window_and_returns_the_order_asked_for() -> None:
    poster = FakePoster(answer())
    found = await MarketCorrelationSource(poster, named()).matrix([A, B, C], START, END)
    [(path, body)] = poster.calls
    assert path == "/api/market/correlations"
    assert body == {
        "instrument_ids": [str(A), str(B), str(C)],
        "windows": [{"start": "2020-01-02", "end": "2020-12-31"}],
        "min_observations": MIN_OBSERVATIONS,
    }
    # asked for MSFT, AAPL, KO: the market answered AAPL, KO, MSFT
    assert found.instrument_ids == (A, B, C) and found.n_obs == 252
    assert found.values == pytest.approx(
        np.array([[1.0, 0.8, 0.2], [0.8, 1.0, 0.3], [0.2, 0.3, 1.0]])
    )
    assert np.allclose(found.values, found.values.T) and found.unavailable == ()


async def test_undefined_cells_come_back_as_nan_with_their_reasons() -> None:
    cells = {
        "matrix": [
            ["1.00000000", None, "0.80000000"],
            [None, "1.00000000", "0.20000000"],
            ["0.80000000", "0.20000000", "1.00000000"],
        ],
        "unavailable": [
            {"row": "AAPL", "column": "KO", "reason": "constant_series"},
            {"row": "KO", "column": "AAPL", "reason": "constant_series"},
        ],
    }
    found = await MarketCorrelationSource(FakePoster(answer(**cells)), named()).matrix(
        [A, B, C], START, END
    )
    assert np.isnan(found.values[1, 2]) and np.isnan(found.values[2, 1])  # AAPL and KO, reordered
    assert found.unavailable[0] == ("AAPL", "KO", "constant_series")
    assert int(np.isnan(found.values).sum()) == 2


def test_cells_of_instruments_that_were_not_asked_for_are_left_out_of_the_list() -> None:
    window = answer(unavailable=[{"row": "AAPL", "column": "KO", "reason": "constant_series"}])[
        "windows"
    ][0]
    only = assemble(window, [B, A], ["AAPL", "MSFT"])
    assert only.unavailable == () and only.values.shape == (2, 2)


async def test_a_symbol_the_market_did_not_answer_for_is_an_unknown_instrument() -> None:
    short = answer(symbols=["AAPL", "KO"], matrix=[["1", "0.3"], ["0.3", "1"]])
    with pytest.raises(InstrumentNotFound, match="MSFT"):
        await MarketCorrelationSource(FakePoster(short), named()).matrix([A, B, C], START, END)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ServiceError(404, "x", extra={}), InstrumentNotFound),
        (ServiceError(502, "x", extra={"upstream_status": 404}), InstrumentNotFound),
        (ServiceError(502, "x", extra={"upstream_status": 500}), CorrelationUnavailable),
        (ServiceError(503, "circuit open"), CorrelationUnavailable),
        (TimeoutError("slow"), CorrelationUnavailable),
        (ConnectionRefusedError("down"), CorrelationUnavailable),
    ],
)
async def test_a_failing_market_service_is_a_missing_instrument_or_a_retryable_outage(
    error: BaseException, expected: type[Exception]
) -> None:
    with pytest.raises(expected):
        await MarketCorrelationSource(FakePoster(error), named()).matrix([A, B, C], START, END)


async def test_a_422_from_the_market_service_refuses_the_run_for_good() -> None:
    error = ServiceError(502, "Upstream error", extra={"upstream_status": 422})
    with pytest.raises(RunRefused) as refused:
        await MarketCorrelationSource(FakePoster(error), named()).matrix([A, B, C], START, END)
    assert refused.value.code == CORRELATION_UNAVAILABLE


# ---- the file source over the recorded fixture ----


async def test_the_file_source_gives_the_latest_recorded_window_for_the_names_asked() -> None:
    prices = FilePriceSource(FIXTURES / "replay_ticks_2020.json")
    source = FileCorrelationSource(FIXTURES / "correlation_rolling_60_5.json", prices)
    ids = [AAPL, *[i for i in prices._symbols if i != AAPL][:2]]
    found = await source.matrix(ids, date(2019, 1, 1), date(2021, 12, 31))
    assert found.values.shape == (3, 3) and np.allclose(np.diag(found.values), 1.0)
    assert np.allclose(found.values, found.values.T) and found.unavailable == ()
    assert np.all(np.abs(found.values) <= 1.0) and found.n_obs == 60
    early = await source.matrix(ids, date(2019, 1, 1), date(2019, 6, 30))
    assert not np.array_equal(early.values, found.values)  # another window


async def test_the_file_source_has_no_window_before_the_data_starts() -> None:
    prices = FilePriceSource(FIXTURES / "replay_ticks_2020.json")
    source = FileCorrelationSource(FIXTURES / "correlation_rolling_60_5.json", prices)
    ids = list(prices._symbols)[:2]
    with pytest.raises(CorrelationUnavailable):
        await source.matrix(ids, date(2010, 1, 1), date(2010, 12, 31))


# ---- VaR and CVaR from K6 ----


def install_fake_metrics(function: Any) -> str:
    package = types.ModuleType("fake_quant_metrics")
    package.__version__ = "3.1.4"  # type: ignore[attr-defined]
    module = types.ModuleType("fake_quant_metrics.metrics")
    if function is not None:
        module.var_cvar = function  # type: ignore[attr-defined]
    sys.modules["fake_quant_metrics"] = package
    sys.modules["fake_quant_metrics.metrics"] = module
    return "fake_quant_metrics.metrics"


@pytest.fixture(autouse=True)
def _remove_fake_metrics() -> Any:
    yield
    sys.modules.pop("fake_quant_metrics", None)
    sys.modules.pop("fake_quant_metrics.metrics", None)


def test_without_k6_the_quant_adapter_is_unavailable_and_the_default_is_the_specification() -> None:
    quant = QuantRisk("no_such_package.metrics")
    assert not quant.available
    with pytest.raises(RuntimeError, match="not installed"):
        quant.var_cvar(np.zeros(30))
    assert isinstance(default_risk(), (ReferenceRisk, QuantRisk))


def test_with_k6_installed_its_answer_and_version_are_used() -> None:
    calls: list[tuple[np.ndarray, float]] = []

    def var_cvar(returns: np.ndarray, alpha: float) -> tuple[float, float]:
        calls.append((returns, alpha))
        return 0.11, 0.22

    quant = QuantRisk(install_fake_metrics(var_cvar))
    assert quant.available and quant.version == "3.1.4"
    assert quant.var_cvar([0.1, -0.1] * 20, 0.9) == (0.11, 0.22)
    assert calls[0][1] == 0.9 and calls[0][0].dtype == np.float64


def test_a_library_without_var_cvar_is_not_available() -> None:
    assert not QuantRisk(install_fake_metrics(None)).available


def test_k6_and_the_specification_agree_on_the_same_returns() -> None:
    """K6 is installed (tracker I-04): VaR and CVaR equal the specification's formula, both are
    positive losses, CVaR is at least VaR, and the service picks K6 up by itself."""
    returns = np.random.default_rng(5).normal(0.0, 0.04, size=500)
    quant = QuantRisk()
    assert quant.available
    for alpha in (0.9, 0.95, 0.99):
        var, cvar = quant.var_cvar(returns, alpha)
        assert (var, cvar) == pytest.approx(reference_var_cvar(returns, alpha))
        assert 0 < var <= cvar
    assert isinstance(default_risk(), QuantRisk)
    assert default_risk().version == quant.version
