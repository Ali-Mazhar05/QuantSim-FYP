"""Run submit, run status and the paged trade log over the in-memory store: a repeated
Idempotency-Key returns the same job, and the log pages gap-free with a correct cursor."""

import uuid

import httpx
import pytest
from api_support import (
    API,
    MOMENTUM,
    FakeStore,
    as_role,
    client_for,
    fake_app,
    portfolio_body,
)

from qs_template.auth import Role


async def _portfolio(http: httpx.AsyncClient, store: FakeStore) -> str:
    quant = as_role(Role.QUANT)
    strategy = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
    created = await http.post(
        f"{API}/portfolios", json=portfolio_body(strategy.json()["id"]), headers=quant
    )
    assert created.status_code == 201, created.text
    portfolio_id: str = created.json()["id"]
    return portfolio_id


async def test_a_submit_is_202_and_a_repeated_key_returns_the_same_job() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http, store)
        runs = f"{API}/portfolios/{portfolio_id}/runs"
        quant = as_role(Role.QUANT)

        first = await http.post(runs, headers={**quant, "Idempotency-Key": "run-1"})
        assert first.status_code == 202, first.text
        accepted = first.json()
        assert accepted["status"] == "queued" and accepted["created"] is True
        assert accepted["portfolio_id"] == portfolio_id
        assert first.headers["location"] == f"{runs}/{accepted['job_id']}"

        again = await http.post(runs, headers={**quant, "Idempotency-Key": "run-1"})
        assert again.status_code == 202
        assert again.json()["job_id"] == accepted["job_id"]
        assert again.json()["created"] is False

        other = await http.post(runs, headers={**quant, "Idempotency-Key": "run-2"})
        assert other.json()["job_id"] != accepted["job_id"]

        # Without a key a portfolio has one run job
        plain = [(await http.post(runs, headers=quant)).json()["job_id"] for _ in range(2)]
        assert plain[0] == plain[1] and plain[0] not in {accepted["job_id"]}


async def test_the_run_status_is_read_by_any_role_under_its_own_portfolio() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http, store)
        submitted = await http.post(
            f"{API}/portfolios/{portfolio_id}/runs", headers=as_role(Role.QUANT)
        )
        job_id = submitted.json()["job_id"]
        status = await http.get(
            f"{API}/portfolios/{portfolio_id}/runs/{job_id}", headers=as_role(Role.VIEWER)
        )
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["job_id"] == job_id and body["status"] == "queued"
        assert body["progress"] == 0.0 and body["error"] is None and body["result"] is None

        elsewhere = await http.get(
            f"{API}/portfolios/{uuid.uuid4()}/runs/{job_id}", headers=as_role(Role.VIEWER)
        )
        assert elsewhere.status_code == 404
        unknown = await http.get(
            f"{API}/portfolios/{portfolio_id}/runs/{uuid.uuid4()}", headers=as_role(Role.VIEWER)
        )
        assert unknown.status_code == 404


async def test_a_submit_for_an_unknown_portfolio_is_404_and_queues_nothing() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        response = await http.post(
            f"{API}/portfolios/{uuid.uuid4()}/runs", headers=as_role(Role.QUANT)
        )
        assert response.status_code == 404
        assert store.jobs == {}


@pytest.mark.parametrize("key", ["", "k" * 201])
async def test_a_bad_idempotency_key_is_422(key: str) -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http, store)
        response = await http.post(
            f"{API}/portfolios/{portfolio_id}/runs",
            headers={**as_role(Role.QUANT), "Idempotency-Key": key},
        )
        assert response.status_code == 422, response.text
        assert store.jobs == {}


async def test_the_event_log_pages_gap_free_with_a_cursor() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http, store)
        log = store.add_log(uuid.UUID(portfolio_id), 7)
        events = f"{API}/portfolios/{portfolio_id}/events"
        viewer = as_role(Role.VIEWER)

        seen: list[int] = []
        cursors: list[int | None] = []
        after = 0
        while True:
            page = await http.get(events, params={"after_seq": after, "limit": 3}, headers=viewer)
            assert page.status_code == 200, page.text
            body = page.json()
            seen += [e["seq"] for e in body["items"]]
            cursors.append(body["next_cursor"])
            if body["next_cursor"] is None:
                break
            after = body["next_cursor"]
        assert seen == list(range(1, 8))
        assert cursors == [3, 6, None]

        first = (await http.get(events, headers=viewer)).json()
        assert first["next_cursor"] is None
        item = first["items"][0]
        assert set(item) == {"seq", "type", "version", "event_time", "payload", "prev_hash", "hash"}
        assert item["hash"] == log[0].hash and item["prev_hash"] is None
        assert first["items"][1]["prev_hash"] == log[0].hash

        exact = (await http.get(events, params={"limit": 7}, headers=viewer)).json()
        assert len(exact["items"]) == 7 and exact["next_cursor"] is None
        past = (await http.get(events, params={"after_seq": 7}, headers=viewer)).json()
        assert past == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 2001}, {"after_seq": -1}])
async def test_bad_paging_parameters_are_422(params: dict[str, int]) -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http, store)
        response = await http.get(
            f"{API}/portfolios/{portfolio_id}/events", params=params, headers=as_role(Role.VIEWER)
        )
        assert response.status_code == 422


async def test_the_log_of_an_unknown_portfolio_is_404() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.get(
            f"{API}/portfolios/{uuid.uuid4()}/events", headers=as_role(Role.VIEWER)
        )
        assert response.status_code == 404
