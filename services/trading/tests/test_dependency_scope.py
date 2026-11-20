"""Every committing ``yield`` dependency finishes before the response is sent, so a
client always reads its own writes (see qs_template.app.request_scoped_yield_dependencies)."""

from qs_template.app import request_scoped_yield_dependencies
from qs_trading.main import build_app
from qs_trading.settings import TradingSettings


def test_no_yield_dependency_runs_after_the_response(settings: TradingSettings) -> None:
    assert request_scoped_yield_dependencies(build_app(settings)) == []
