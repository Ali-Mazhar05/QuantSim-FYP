"""Every committing ``yield`` dependency finishes before the response is sent, so a
client always reads its own writes (see qs_template.app.request_scoped_yield_dependencies)."""

from fakeredis import FakeAsyncRedis

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_template.app import request_scoped_yield_dependencies
from qs_template.revocation import RevocationList
from tests.conftest import make_settings


def test_no_yield_dependency_runs_after_the_response() -> None:
    redis = FakeAsyncRedis()
    app = build_app(make_settings(), revocations=RevocationList(redis), limiter=RateLimiter(redis))
    assert request_scoped_yield_dependencies(app) == []
