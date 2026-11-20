"""The HTTP adapters (A17) over the C3 fixtures served as the C2 feeds: paging, the frozen
fingerprint in both detail shapes, a restated price, and J2 parity: the same portfolio
over the file adapter and over the HTTP adapter ends on the identical final hash."""

import uuid
from decimal import Decimal

import pytest
from feed_support import (
    PATH_TICKS,
    REPLAY,
    REPLAY_FINGERPRINT,
    REPLAY_ID,
    REPLAY_TICKS,
    RUN_FINGERPRINT,
    RUN_ID,
    SYNTHETIC,
    ContractFeeds,
)

from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.adapters.http_environment import (
    EnvironmentNotActive,
    EnvironmentNotFound,
    FeedRefused,
    ReplayFeed,
    SimulationPathFeed,
)
from qs_trading.engine.core import Engine, RunSpec, SessionResult
from qs_trading.engine.runner import MemorySink, RunResult, load_ticks, run_portfolio
from qs_trading.jobs import is_permanent
from qs_trading.ports.market_environment import (
    MAX_PAGE_SIZE,
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironment,
)

RESTATED = "xxh3:ffffffffffffffffffffffffffffffff"


# --- paging ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("page_size", "pages"), [(500, 3), (MAX_PAGE_SIZE, 1), (100, 13)])
async def test_the_replay_is_read_page_by_page(page_size: int, pages: int) -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert await feed.activate() == REPLAY_FINGERPRINT
    ticks = await load_ticks(feed, REPLAY_FINGERPRINT, page_size=page_size)
    assert [t.seq for t in ticks] == list(range(1, REPLAY_TICKS + 1))
    requests = feeds.tick_requests()
    assert len(requests) == pages  # the frozen value came from the detail: no probe
    after = [int(r.url.params["after_seq"]) for r in requests]
    assert after == [n * page_size for n in range(pages)]
    assert all(int(r.url.params["limit"]) == page_size for r in requests)


async def test_the_http_ticks_equal_the_file_ticks() -> None:
    feed = ReplayFeed(ContractFeeds().market_client(), REPLAY_ID)
    over_http = await load_ticks(feed, await feed.activate())
    file = FileEnvironment(REPLAY)
    assert over_http == await load_ticks(file, await file.activate())


@pytest.mark.parametrize("path_index", [0, 1, 2])
async def test_a_synthetic_path_is_read_with_its_path_always_sent(path_index: int) -> None:
    feeds = ContractFeeds()
    feed = SimulationPathFeed(feeds.simulation_client(), RUN_ID, path_index)
    assert feed.ref == EnvironmentRef("simulation", RUN_ID, path_index)
    assert await feed.activate() == RUN_FINGERPRINT
    assert feed.median_path_index == 2
    ticks = await load_ticks(feed, RUN_FINGERPRINT, page_size=64)
    assert len(ticks) == PATH_TICKS
    file = FileEnvironment(SYNTHETIC, path_index=path_index)
    assert ticks == await load_ticks(file, await file.activate())
    assert all(r.url.params["path"] == str(path_index) for r in feeds.tick_requests())


# --- the frozen fingerprint -----------------------------------------------------------------


async def test_without_a_fingerprint_in_the_detail_the_first_page_gives_it() -> None:
    """#80 as it is today: GET /environments/{id} has no source_fingerprint."""
    feeds = ContractFeeds(detail_fingerprint=False)
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert await feed.activate() == REPLAY_FINGERPRINT
    probe = feeds.tick_requests()
    assert [(r.url.params["after_seq"], r.url.params["limit"]) for r in probe] == [("0", "1")]


async def test_the_detail_fingerprint_is_the_frozen_one_even_after_a_restatement() -> None:
    """With the review's shape the value frozen at activation in the market service wins
    over what the feed serves now, so a restatement before the run is noticed."""
    feeds = ContractFeeds()
    feeds.restate(REPLAY_ID, RESTATED)
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert await feed.activate() == REPLAY_FINGERPRINT
    with pytest.raises(FingerprintChanged) as raised:
        await feed.ticks(0, 500)
    assert (raised.value.expected, raised.value.actual) == (REPLAY_FINGERPRINT, RESTATED)


async def test_a_restatement_between_pages_is_fingerprint_changed() -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    await feed.activate()
    await feed.ticks(0, 500)
    feeds.restate(REPLAY_ID, RESTATED)
    with pytest.raises(FingerprintChanged) as raised:
        await feed.ticks(500, 500)
    assert is_permanent(raised.value)


async def test_a_restatement_during_a_run_stops_it_before_the_next_session() -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID, fingerprint_ttl_seconds=0)

    class Restating(MemorySink):
        async def commit(self, engine: Engine, result: SessionResult) -> None:
            await super().commit(engine, result)
            if self.sessions_committed == 10:
                feeds.restate(REPLAY_ID, RESTATED)

    sink = Restating()
    with pytest.raises(FingerprintChanged):
        await run_portfolio(_spec(EnvironmentRef("replay", REPLAY_ID)), feed, sink)
    assert sink.sessions_committed == 10


# --- what the feed refuses ------------------------------------------------------------------


async def test_an_unknown_environment_is_permanent() -> None:
    feed = ReplayFeed(ContractFeeds().market_client(), str(uuid.UUID(int=1)))
    with pytest.raises(EnvironmentNotFound) as raised:
        await feed.activate()
    assert is_permanent(raised.value)


async def test_an_unknown_run_is_permanent() -> None:
    feed = SimulationPathFeed(ContractFeeds().simulation_client(), str(uuid.UUID(int=2)), 0)
    with pytest.raises(EnvironmentNotFound):
        await feed.activate()


@pytest.mark.parametrize("status", ["draft", "ready"])
async def test_a_replay_that_is_not_activated_is_refused(status: str) -> None:
    feed = ReplayFeed(ContractFeeds(environment_status=status).market_client(), REPLAY_ID)
    with pytest.raises(EnvironmentNotActive, match="activated in the market service"):
        await feed.activate()


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
async def test_a_run_that_is_not_completed_is_refused(status: str) -> None:
    feeds = ContractFeeds(run_status=status)
    with pytest.raises(EnvironmentNotActive, match="not completed"):
        await SimulationPathFeed(feeds.simulation_client(), RUN_ID, 0).activate()


async def test_a_path_the_run_does_not_hold_is_refused() -> None:
    feeds = ContractFeeds()
    with pytest.raises(FeedRefused, match="3 paths"):
        await SimulationPathFeed(feeds.simulation_client(), RUN_ID, 3).activate()
    feeds = ContractFeeds(detail_fingerprint=False)
    with pytest.raises(FeedRefused, match="no path 3"):  # the feed's own 422
        await SimulationPathFeed(feeds.simulation_client(), RUN_ID, 3).ticks(0, 10)


# --- J2 parity ------------------------------------------------------------------------------


def _spec(ref: EnvironmentRef) -> RunSpec:
    return RunSpec(
        portfolio_id=uuid.UUID("0a170000-0000-4000-8000-000000000002"),
        strategy_kind="buy_and_hold",
        strategy_params={},
        initial_capital=Decimal("100000"),
        cost_model={"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"},
        slippage_model={"kind": "fixed_bps", "bps": "5"},
        environment=ref,
    )


async def _run(environment: MarketEnvironment) -> tuple[RunResult, MemorySink]:
    sink = MemorySink()
    return await run_portfolio(_spec(environment.ref), environment, sink), sink


async def test_j2_parity_on_the_replay() -> None:
    over_file, file_log = await _run(FileEnvironment(REPLAY))
    over_http, http_log = await _run(ReplayFeed(ContractFeeds().market_client(), REPLAY_ID))
    assert over_http.final_hash == over_file.final_hash
    assert over_http.final_value == over_file.final_value
    assert over_http.source_fingerprint == over_file.source_fingerprint == REPLAY_FINGERPRINT
    assert [e.hash for e in http_log.events] == [e.hash for e in file_log.events]
    assert over_file.sessions == 253


@pytest.mark.parametrize("detail_fingerprint", [True, False])
async def test_j2_parity_on_the_median_synthetic_path(detail_fingerprint: bool) -> None:
    feeds = ContractFeeds(detail_fingerprint=detail_fingerprint)
    over_file, _ = await _run(FileEnvironment(SYNTHETIC, path_index=2))
    over_http, _ = await _run(SimulationPathFeed(feeds.simulation_client(), RUN_ID, 2))
    assert over_http.final_hash == over_file.final_hash
    assert over_http.source_fingerprint == RUN_FINGERPRINT


async def test_the_fingerprint_check_per_session_is_answered_from_memory() -> None:
    feeds = ContractFeeds()
    result, _ = await _run(ReplayFeed(feeds.market_client(), REPLAY_ID))
    assert result.sessions == 253
    # one detail and the pages; no request per session within the cache interval
    assert len(feeds.requests) == 1 + 1
