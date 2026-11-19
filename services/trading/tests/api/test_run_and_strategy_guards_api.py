"""One run in progress per portfolio, and strategy edits by their owner or an admin only,
over the in-memory store."""

import uuid

import httpx
from api_support import API, MOMENTUM, FakeStore, as_role, client_for, fake_app, portfolio_body

from qs_template.auth import Principal, Role
from qs_trading.api_strategies import may_edit

STRATEGIES = f"{API}/strategies"


async def _portfolio(http: httpx.AsyncClient) -> str:
    quant = as_role(Role.QUANT)
    strategy = await http.post(STRATEGIES, json=MOMENTUM, headers=quant)
    created = await http.post(
        f"{API}/portfolios", json=portfolio_body(strategy.json()["id"]), headers=quant
    )
    assert created.status_code == 201, created.text
    portfolio_id: str = created.json()["id"]
    return portfolio_id


async def test_a_new_key_while_a_run_is_in_progress_is_409_naming_the_run() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http)
        runs = f"{API}/portfolios/{portfolio_id}/runs"
        quant = as_role(Role.QUANT)
        first = await http.post(runs, headers={**quant, "Idempotency-Key": "a"})
        assert first.status_code == 202, first.text
        job_id = first.json()["job_id"]

        for headers in ({**quant, "Idempotency-Key": "b"}, quant):
            refused = await http.post(runs, headers=headers)
            assert refused.status_code == 409, refused.text
            assert refused.headers["content-type"].startswith("application/problem+json")
            body = refused.json()
            assert body["type"] == "urn:quantsim:problem:run-in-progress"
            assert body["job_id"] == job_id
        assert len(store.jobs) == 1

        # The same key still answers with its own job
        again = await http.post(runs, headers={**quant, "Idempotency-Key": "a"})
        assert again.status_code == 202
        assert again.json()["job_id"] == job_id and again.json()["created"] is False

        # A run in progress only blocks its own portfolio
        other = await _portfolio(http)
        elsewhere = await http.post(f"{API}/portfolios/{other}/runs", headers=quant)
        assert elsewhere.status_code == 202, elsewhere.text


async def test_a_new_key_is_accepted_once_the_run_has_finished() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        portfolio_id = await _portfolio(http)
        runs = f"{API}/portfolios/{portfolio_id}/runs"
        quant = as_role(Role.QUANT)
        seen: set[str] = set()
        for n, outcome in enumerate(["succeeded", "failed", "succeeded"]):
            submitted = await http.post(runs, headers={**quant, "Idempotency-Key": f"k{n}"})
            assert submitted.status_code == 202, submitted.text
            assert submitted.json()["created"] is True
            seen.add(submitted.json()["job_id"])
            store.finish_runs(uuid.UUID(portfolio_id), outcome)
        assert len(seen) == 3


def _principal(role: Role, user_id: uuid.UUID) -> Principal:
    return Principal(user_id=user_id, username="u", role=role, token_id="t", issued_at=0)


def test_only_the_owner_or_an_admin_may_edit() -> None:
    owner, other = uuid.uuid4(), uuid.uuid4()
    assert may_edit(_principal(Role.QUANT, owner), owner)
    assert not may_edit(_principal(Role.QUANT, other), owner)
    assert may_edit(_principal(Role.ADMIN, other), owner)


async def test_another_quant_may_not_edit_a_strategy_but_may_read_it() -> None:
    store = FakeStore()
    owner = uuid.uuid4()
    async with client_for(fake_app(store)) as http:
        mine = as_role(Role.QUANT, user_id=owner)
        created = (await http.post(STRATEGIES, json=MOMENTUM, headers=mine)).json()
        url = f"{STRATEGIES}/{created['id']}"
        edit = {**MOMENTUM, "name": "Edited"}

        stranger = as_role(Role.QUANT)
        refused = await http.put(url, json=edit, headers=stranger)
        assert refused.status_code == 403, refused.text
        assert refused.json()["type"] == "urn:quantsim:problem:forbidden"
        # Refused before the body is judged, and nothing changed
        bad = await http.put(url, json={**MOMENTUM, "params": {"lookback": -1}}, headers=stranger)
        assert bad.status_code == 403
        assert store.strategies[uuid.UUID(created["id"])].name == MOMENTUM["name"]
        for role in Role:
            got = await http.get(url, headers=as_role(role))
            assert got.status_code == 200 and got.json()["name"] == MOMENTUM["name"]

        by_owner = await http.put(url, json=edit, headers=mine)
        assert by_owner.status_code == 200, by_owner.text
        assert by_owner.json()["owner_id"] == str(owner)

        by_admin = await http.put(url, json={**edit, "name": "Admin"}, headers=as_role(Role.ADMIN))
        assert by_admin.status_code == 200, by_admin.text
        # The owner stays the owner when an admin edits
        assert by_admin.json()["name"] == "Admin" and by_admin.json()["owner_id"] == str(owner)

        for role in (Role.ANALYST, Role.VIEWER):
            assert (await http.put(url, json=edit, headers=as_role(role))).status_code == 403
        missing = await http.put(f"{STRATEGIES}/{uuid.uuid4()}", json=edit, headers=stranger)
        assert missing.status_code == 404
