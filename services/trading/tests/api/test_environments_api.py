"""GET /demo-environments (A18): the demo fixtures the worker can run over, listed for the
Create Portfolio page when QS_TRADING_DEMO_ENVIRONMENTS is set, and nothing otherwise."""

import json
from pathlib import Path

import pytest
from api_support import API, FakeStore, as_role, client_for, fake_app

from qs_template.auth import Role
from qs_trading.api_environments import demo_directory, list_demo_environments
from qs_trading.demo.feeds import FILE_COPY_ID
from qs_trading.jobs import BUNDLED_DEMO_ENVIRONMENTS

DEMO_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
BENCHMARK_ID = "5d0c6c1e-7a14-4a14-8a14-000000000040"


async def test_lists_the_bundled_demo_environments_when_set() -> None:
    async with client_for(fake_app(FakeStore(), demo_environments="bundled")) as http:
        response = await http.get(f"{API}/demo-environments", headers=as_role(Role.VIEWER))
    assert response.status_code == 200, response.text
    by_id = {e["id"]: e for e in response.json()}
    # FILE_COPY_ID: the recorded 2020 replay as a file, for the DEV J2 check
    assert set(by_id) == {DEMO_ID, BENCHMARK_ID, FILE_COPY_ID}
    assert by_id[DEMO_ID] == {
        "id": DEMO_ID,
        "name": "A14 two-symbol fixture",
        "env_type": "replay",
        "sessions": 10,
        "start_date": "2026-01-05",
        "end_date": "2026-01-16",
    }
    assert by_id[BENCHMARK_ID]["sessions"] == 252
    assert by_id[FILE_COPY_ID]["sessions"] == 253


async def test_is_empty_without_the_setting() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.get(f"{API}/demo-environments", headers=as_role(Role.QUANT))
    assert response.status_code == 200
    assert response.json() == []


async def test_needs_a_signed_in_user() -> None:
    async with client_for(fake_app(FakeStore(), demo_environments="bundled")) as http:
        response = await http.get(f"{API}/demo-environments")
    assert response.status_code == 401


def test_the_setting_names_the_directory(tmp_path: Path) -> None:
    assert demo_directory("") is None
    assert demo_directory("bundled") == BUNDLED_DEMO_ENVIRONMENTS
    assert demo_directory(str(tmp_path)) == tmp_path
    assert list_demo_environments(None) == []
    assert list_demo_environments(tmp_path / "missing") == []


def _write(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_leaves_out_files_that_are_not_replay_fixtures(tmp_path: Path) -> None:
    replay = "11111111-1111-4111-8111-111111111111"
    _write(
        tmp_path / f"{replay}.json",
        {
            "environment": {"id": replay, "type": "replay"},
            "items": [
                {"session": 0, "session_date": "2024-01-02"},
                {"session": 0, "session_date": "2024-01-02"},
                {"session": 1, "session_date": "2024-01-03"},
            ],
        },
    )
    _write(tmp_path / "run.json", {"run": {"id": "x"}, "paths": []})
    _write(tmp_path / "sim.json", {"environment": {"id": replay, "type": "synthetic"}, "items": []})
    no_uuid = {"environment": {"id": "abc", "type": "replay"}, "items": []}
    _write(tmp_path / "not-uuid.json", no_uuid)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    _write(tmp_path / "list.json", [1, 2])

    listed = list_demo_environments(tmp_path)

    assert [(str(e.id), e.name, e.sessions) for e in listed] == [(replay, replay, 2)]
    assert listed[0].start_date is not None and listed[0].start_date.isoformat() == "2024-01-02"
    assert listed[0].end_date is not None and listed[0].end_date.isoformat() == "2024-01-03"


def test_a_changed_file_is_read_again(tmp_path: Path) -> None:
    env_id = "22222222-2222-4222-8222-222222222222"
    path = tmp_path / f"{env_id}.json"
    _write(path, {"environment": {"id": env_id, "type": "replay", "name": "First"}, "items": []})
    assert [e.name for e in list_demo_environments(tmp_path)] == ["First"]
    _write(
        path,
        {"environment": {"id": env_id, "type": "replay", "name": "Second, longer"}, "items": []},
    )
    assert [e.name for e in list_demo_environments(tmp_path)] == ["Second, longer"]


@pytest.mark.parametrize("role", list(Role))
async def test_every_role_may_read_it(role: Role) -> None:
    async with client_for(fake_app(FakeStore(), demo_environments="bundled")) as http:
        response = await http.get(f"{API}/demo-environments", headers=as_role(role))
    assert response.status_code == 200
