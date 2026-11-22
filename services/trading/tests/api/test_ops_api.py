"""A-NFR-14: GET /ops/metrics, without a database: the response shape, admins only, the
``recent`` bounds, and the percentile maths behind the job durations."""

import uuid
from dataclasses import dataclass, field

import pytest
from api_support import API, FakeOps, FakeStore, as_role, client_for, fake_app
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template.auth import Role
from qs_trading.api_ops import DEFAULT_RECENT, MAX_RECENT, OpsReader, durations_out, percentile
from qs_trading.schemas import OpsMetricsOut

OPS = f"{API}/ops/metrics"


@dataclass
class _Recording(FakeOps):
    asked: list[int] = field(default_factory=list)

    async def ops_metrics(self, recent: int) -> OpsMetricsOut:
        self.asked.append(recent)
        return await super().ops_metrics(recent)


async def test_an_admin_gets_queue_depth_durations_and_outbox_backlog() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.get(OPS, headers=as_role(Role.ADMIN))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"generated_at", "queue", "durations", "outbox"}
    assert body["queue"] == {
        "kind": "engine.run",
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "oldest_queued_seconds": None,
    }
    assert body["durations"] == {
        "window": DEFAULT_RECENT,
        "count": 0,
        "p50_seconds": None,
        "p95_seconds": None,
        "max_seconds": None,
    }
    assert body["outbox"] == {"pending": 0, "oldest_pending_seconds": None}


@pytest.mark.parametrize("role", [Role.QUANT, Role.ANALYST, Role.VIEWER])
async def test_other_roles_are_refused(role: Role) -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.get(OPS, headers=as_role(role, user_id=uuid.uuid4()))
    assert response.status_code == 403
    assert response.json()["type"] == "urn:quantsim:problem:forbidden"


async def test_anonymous_is_refused() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        assert (await http.get(OPS)).status_code == 401


async def test_recent_is_passed_on_and_bounded() -> None:
    reader = _Recording()

    def ops(_: AsyncSession) -> OpsReader:
        return reader

    admin = as_role(Role.ADMIN)
    async with client_for(fake_app(FakeStore(), ops=ops)) as http:
        ok = await http.get(OPS, headers=admin, params={"recent": 20})
        assert ok.status_code == 200 and ok.json()["durations"]["window"] == 20
        for bad in (0, MAX_RECENT + 1, "many"):
            response = await http.get(OPS, headers=admin, params={"recent": bad})
            assert response.status_code == 422, bad
    assert reader.asked == [20]


def test_the_route_is_in_the_openapi_document() -> None:
    paths = fake_app(FakeStore()).openapi()["paths"]
    schema = paths[OPS]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/OpsMetricsOut"}


def test_percentile_is_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]  # 1 .. 100
    assert percentile(values, 0.5) == 50
    assert percentile(values, 0.95) == 95
    assert percentile(values, 1.0) == 100
    assert percentile([float(n) for n in range(1, 21)], 0.95) == 19
    assert percentile([3.0], 0.5) == 3 and percentile([3.0], 0.95) == 3
    assert percentile([1.0, 2.0], 0.5) == 1
    assert percentile([], 0.5) is None


def test_durations_sort_their_input() -> None:
    out = durations_out([5.0, 1.0, 3.0, 2.0, 4.0], window=10)
    assert (out.window, out.count) == (10, 5)
    assert (out.p50_seconds, out.p95_seconds, out.max_seconds) == (3, 5, 5)
