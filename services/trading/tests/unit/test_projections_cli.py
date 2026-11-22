"""The ``verify`` and ``rebuild`` commands (A15): arguments, the JSON report and the exit
codes, with the database replaced by a stand-in (the real run is in tests/db)."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from qs_trading import cli
from qs_trading.engine.store import PortfolioNotFound
from qs_trading.projections import ChainReport, TableDifference
from qs_trading.projections.rebuild import ChainBroken, RebuildResult

PORTFOLIO = uuid.UUID("0a150000-0000-4000-8000-000000000003")


class FakeDatabase:
    closed = False

    def __init__(self, settings: object) -> None:
        pass

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[object]:
        yield object()

    async def close(self) -> None:
        FakeDatabase.closed = True


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeDatabase.closed = False
    monkeypatch.setattr(cli, "Database", FakeDatabase)
    monkeypatch.setattr(cli, "_settings", lambda process: None)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    with pytest.raises(SystemExit) as stopped:
        cli.main(argv)
    assert FakeDatabase.closed
    code = stopped.value.code
    assert isinstance(code, int)
    return code, json.loads(capsys.readouterr().out)


def _result(**changes: Any) -> RebuildResult:
    base: dict[str, Any] = {
        "portfolio_id": PORTFOLIO,
        "status": "identical",
        "events": 3,
        "final_seq": 3,
        "final_hash": "abc",
    }
    return RebuildResult(**{**base, **changes})


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (_result(), 0),
        (_result(status="differs", differences=(TableDifference("fill", ("seq=4",)),)), 1),
        (_result(status="differs", applied=True), 0),
    ],
    ids=["identical", "differs", "applied"],
)
def test_rebuild_prints_the_result_and_exits_by_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: RebuildResult,
    code: int,
) -> None:
    calls: list[tuple[uuid.UUID, bool]] = []

    async def rebuild(session: object, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildResult:
        calls.append((portfolio_id, apply))
        return result

    monkeypatch.setattr(cli, "rebuild_portfolio", rebuild)
    argv = ["rebuild", str(PORTFOLIO)] + (["--apply"] if result.applied else [])
    assert _run(argv, capsys) == (code, result.to_json())
    assert calls == [(PORTFOLIO, result.applied)]


def test_rebuild_reports_a_broken_chain_and_an_unknown_portfolio(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = ChainReport(PORTFOLIO, 4, 4, "h4", broken_seq=5, reason="expected seq 5")

    async def broken(session: object, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildResult:
        raise ChainBroken(report)

    monkeypatch.setattr(cli, "rebuild_portfolio", broken)
    code, document = _run(["rebuild", str(PORTFOLIO)], capsys)
    assert code == cli.EXIT_BROKEN
    assert document["broken_seq"] == 5 and "breaks at seq 5" in document["error"]

    async def missing(session: object, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildResult:
        raise PortfolioNotFound(str(portfolio_id))

    monkeypatch.setattr(cli, "rebuild_portfolio", missing)
    code, document = _run(["rebuild", str(PORTFOLIO)], capsys)
    assert code == cli.EXIT_NOT_FOUND and document["error"] == "portfolio not found"


@pytest.mark.parametrize(
    ("report", "code"),
    [
        (ChainReport(PORTFOLIO, 3, 3, "h3"), 0),
        (ChainReport(PORTFOLIO, 1, 1, "h1", broken_seq=2, reason="prev_hash"), 2),
    ],
    ids=["intact", "broken"],
)
def test_verify_prints_the_report_and_exits_by_validity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    report: ChainReport,
    code: int,
) -> None:
    async def verify(session: object, portfolio_id: uuid.UUID) -> ChainReport:
        assert portfolio_id == PORTFOLIO
        return report

    monkeypatch.setattr(cli, "verify_portfolio", verify)
    assert _run(["verify", str(PORTFOLIO)], capsys) == (code, report.to_json())


def test_verify_reports_an_unknown_portfolio(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def missing(session: object, portfolio_id: uuid.UUID) -> ChainReport:
        raise PortfolioNotFound(str(portfolio_id))

    monkeypatch.setattr(cli, "verify_portfolio", missing)
    assert _run(["verify", str(PORTFOLIO)], capsys)[0] == cli.EXIT_NOT_FOUND


def test_a_portfolio_id_must_be_a_uuid(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["rebuild", "not-a-uuid"])
    assert stopped.value.code == 2
    assert "invalid UUID" in capsys.readouterr().err
