"""Every committing ``yield`` dependency finishes before the response is sent, so a
client always reads its own writes (see qs_template.app.request_scoped_yield_dependencies)."""

from __pkg__.main import build_app
from __pkg__.settings import __Class__Settings
from qs_template.app import request_scoped_yield_dependencies


def test_no_yield_dependency_runs_after_the_response(settings: __Class__Settings) -> None:
    assert request_scoped_yield_dependencies(build_app(settings)) == []
