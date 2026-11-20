"""Live check of the Trading API and engine against a deployed environment.

Run by ci/scripts/trading-live-check.sh (inside the pinned uv image); standard library
only. Through the gateway it:

 1. waits for /api/trading/ready, and checks that an unauthenticated POST /strategies is
    refused (401);
 2. signs in as the admin test account and creates a uniquely named buy_and_hold strategy
    and a portfolio bound to the demo replay environment;
 3. submits a run with an Idempotency-Key, twice: both answers name the same job;
 4. signs in as the viewer test account: it may read the run but not start one (403);
 5. polls the run until it has succeeded (or fails on ``failed`` or the timeout);
 6. pages the whole event log and checks the chain: ``seq`` runs 1, 2, 3 without gaps,
    every ``prev_hash`` is the previous event's ``hash`` (the first has none), the log
    starts with RUN_STARTED and ends with RUN_COMPLETED, and the last hash and seq are the
    run result's ``final_hash`` and ``final_seq``.

Settings, from the environment (the passwords are never printed):
  QS_LIVE_BASE_URL          the gateway, e.g. http://host.docker.internal:8081
  QS_LIVE_ENV_ID            id of the demo replay environment the portfolio is bound to
  QS_LIVE_USERNAME          an account that may create strategies and portfolios
  QS_LIVE_PASSWORD
  QS_LIVE_VIEWER_USERNAME   optional: a viewer account for step 4 (same password)
  QS_LIVE_TIMEOUT_SECONDS   how long the run may take (default 180)

``python trading_live_check.py --self-test`` runs the chain check's own examples.
Exit code 0 when every check passed, 1 otherwise, with the reason on stderr.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

TRADING = "/api/trading"
LOGIN = "/api/platform/auth/login"
PAGE_SIZE = 200
MAX_PAGES = 1000
POLL_SECONDS = 2.0
PROGRESS_EVERY_SECONDS = 15.0


class LiveCheckFailed(Exception):
    """A check did not hold; the message says which."""


def check_chain(events: Sequence[Mapping[str, Any]], final_hash: str, final_seq: int) -> None:
    """Checks a run's whole event log, in ``seq`` order, against its result.

    >>> log = [
    ...     {"seq": 1, "type": "RUN_STARTED", "prev_hash": None, "hash": "a"},
    ...     {"seq": 2, "type": "VALUED", "prev_hash": "a", "hash": "b"},
    ...     {"seq": 3, "type": "RUN_COMPLETED", "prev_hash": "b", "hash": "c"},
    ... ]
    >>> check_chain(log, "c", 3)
    >>> check_chain(log, "b", 3)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: the last event's hash c is not the run's final hash b
    >>> check_chain([log[0], log[2]], "c", 3)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: event 2 has seq 3: the log has a gap or is out of order
    >>> check_chain([log[0], {**log[1], "prev_hash": "x"}, log[2]], "c", 3)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: event 2: prev_hash x is not the hash of event 1 (a)
    >>> check_chain([{**log[0], "prev_hash": "z"}, *log[1:]], "c", 3)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: event 1 must have no prev_hash, has z
    >>> check_chain(log[:2], "b", 2)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: the log ends with VALUED, not RUN_COMPLETED
    >>> check_chain([], "c", 3)
    Traceback (most recent call last):
    ...
    LiveCheckFailed: the run has no events
    """
    if not events:
        raise LiveCheckFailed("the run has no events")
    previous: Mapping[str, Any] | None = None
    for position, event in enumerate(events, start=1):
        if event.get("seq") != position:
            raise LiveCheckFailed(
                f"event {position} has seq {event.get('seq')}: the log has a gap or is out of order"
            )
        if previous is None:
            if event.get("prev_hash") is not None:
                raise LiveCheckFailed(f"event 1 must have no prev_hash, has {event['prev_hash']}")
        elif event.get("prev_hash") != previous.get("hash"):
            raise LiveCheckFailed(
                f"event {position}: prev_hash {event.get('prev_hash')} is not the hash of "
                f"event {position - 1} ({previous.get('hash')})"
            )
        previous = event
    first, last = events[0].get("type"), events[-1].get("type")
    if first != "RUN_STARTED":
        raise LiveCheckFailed(f"the log starts with {first}, not RUN_STARTED")
    if last != "RUN_COMPLETED":
        raise LiveCheckFailed(f"the log ends with {last}, not RUN_COMPLETED")
    if events[-1].get("hash") != final_hash:
        raise LiveCheckFailed(
            f"the last event's hash {events[-1].get('hash')} is not the run's final hash "
            f"{final_hash}"
        )
    if len(events) != final_seq:
        raise LiveCheckFailed(f"the log has {len(events)} events, the run reports {final_seq}")


def log(message: str) -> None:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{stamp}] trading live check: {message}", flush=True)


class Api:
    """A tiny JSON client over the gateway."""

    def __init__(self, base_url: str) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise LiveCheckFailed(f"the base URL must be http(s), got {base_url}")
        self.base_url = base_url.rstrip("/")

    def call(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: object = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
    ) -> tuple[int, Any]:
        """Status and decoded JSON body (``None`` when empty or not JSON). Connection
        errors raise :class:`LiveCheckFailed`; HTTP errors are returned, not raised."""
        url = self.base_url + path
        if params:
            url += "?" + "&".join(f"{name}={value}" for name, value in params.items())
        data = None if body is None else json.dumps(body).encode()
        # http(s) only: the base URL is checked in __init__
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _decode(error.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise LiveCheckFailed(
                f"{method} {path}: cannot reach {self.base_url}: {error}"
            ) from None

    def expect(self, status: int, method: str, path: str, **kwargs: Any) -> Any:
        got, body = self.call(method, path, **kwargs)
        if got != status:
            raise LiveCheckFailed(
                f"{method} {path} answered {got}, expected {status}: {_short(body)}"
            )
        return body


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw[:300].decode(errors="replace")


def _short(body: object) -> str:
    text = body if isinstance(body, str) else json.dumps(body)
    return text if len(text) <= 500 else text[:500] + "..."


def _setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise LiveCheckFailed(f"{name} is not set")
    return value


def sign_in(api: Api, username: str, password: str) -> str:
    status, body = api.call("POST", LOGIN, body={"username": username, "password": password})
    if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise LiveCheckFailed(f"could not sign in as {username}: {status} {_short(body)}")
    return str(body["access_token"])


def wait_until_ready(api: Api, seconds: float = 60.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            status, body = api.call("GET", f"{TRADING}/ready")
        except LiveCheckFailed as error:
            status, body = 0, str(error)
        if status == 200:
            return
        if time.monotonic() > deadline:
            raise LiveCheckFailed(f"{TRADING}/ready is not ready: {status} {_short(body)}")
        time.sleep(POLL_SECONDS)


def wait_for_run(api: Api, token: str, run_path: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    last_report = -PROGRESS_EVERY_SECONDS
    last_state: tuple[object, object] | None = None
    while True:
        run = api.expect(200, "GET", run_path, token=token)
        state = (run.get("status"), run.get("progress"))
        elapsed = time.monotonic() - started
        if state != last_state or elapsed - last_report >= PROGRESS_EVERY_SECONDS:
            progress = float(run.get("progress") or 0)
            log(
                f"run {run['status']}, {progress:.0%} of sessions, attempt "
                f"{run.get('attempts')}/{run.get('max_attempts')}, {elapsed:.0f}s"
            )
            last_state, last_report = state, elapsed
        if run["status"] == "succeeded":
            return dict(run)
        if run["status"] == "failed":
            raise LiveCheckFailed(f"the run failed: {run.get('error')}")
        if elapsed > timeout:
            raise LiveCheckFailed(
                f"the run is still {run['status']} after {timeout:.0f}s "
                f"(progress {run.get('progress')}, error {run.get('error')})"
            )
        time.sleep(POLL_SECONDS)


def all_events(api: Api, token: str, events_path: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    after = 0
    for _ in range(MAX_PAGES):
        page = api.expect(
            200, "GET", events_path, token=token, params={"after_seq": after, "limit": PAGE_SIZE}
        )
        items = page.get("items") or []
        events += items
        cursor = page.get("next_cursor")
        if cursor is None:
            return events
        if not items or cursor != items[-1].get("seq") or len(items) != PAGE_SIZE:
            raise LiveCheckFailed(
                f"bad page after seq {after}: {len(items)} items, next_cursor {cursor}"
            )
        after = int(cursor)
    raise LiveCheckFailed(f"the log has more than {MAX_PAGES} pages")


def check_projections(
    api: Api,
    token: str,
    base: str,
    events: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
) -> None:
    """The projection-backed routes agree with the log just checked: fills and value
    points match the ORDER_FILLED and VALUED events, state, verify, holdings and metrics
    end on the run's final seq and hash, and an admin rebuild reports identical."""
    final_hash, final_seq = result["final_hash"], result["final_seq"]
    filled = sum(1 for e in events if e.get("type") == "ORDER_FILLED")
    valued = sum(1 for e in events if e.get("type") == "VALUED")

    fills: list[Any] = []
    after = 0
    while True:
        page = api.expect(
            200, "GET", f"{base}/fills", token=token, params={"after_seq": after, "limit": 500}
        )
        fills.extend(page["items"])
        if page.get("next_cursor") is None:
            break
        after = page["next_cursor"]
    if len(fills) != filled:
        raise LiveCheckFailed(f"/fills lists {len(fills)} fills, the log has {filled}")

    series = api.expect(200, "GET", f"{base}/value-series", token=token)
    if len(series) != valued:
        raise LiveCheckFailed(f"/value-series has {len(series)} points, the log has {valued}")
    final_value = result.get("final_value")
    if final_value is not None and Decimal(series[-1]["value"]) != Decimal(str(final_value)):
        raise LiveCheckFailed(
            f"the last value point {series[-1]['value']} is not the run's {final_value}"
        )

    def ends_on_final(route: str, body: Mapping[str, Any], seq_key: str, hash_key: str) -> None:
        if body.get(seq_key) != final_seq or body.get(hash_key) != final_hash:
            raise LiveCheckFailed(
                f"{route} ends on seq {body.get(seq_key)} hash {body.get(hash_key)}, "
                f"not the run's seq {final_seq} hash {final_hash}"
            )

    ends_on_final("/state", api.expect(200, "GET", f"{base}/state", token=token), "seq", "hash")
    verify = api.expect(200, "GET", f"{base}/verify", token=token)
    if verify.get("valid") is not True:
        raise LiveCheckFailed(f"/verify reports a broken chain: {_short(verify)}")
    ends_on_final("/verify", verify, "last_seq", "last_hash")
    holdings = api.expect(200, "GET", f"{base}/holdings", token=token)
    if holdings.get("last_seq") != final_seq:
        raise LiveCheckFailed(f"/holdings is at seq {holdings.get('last_seq')}, not {final_seq}")
    metrics = api.expect(200, "GET", f"{base}/metrics", token=token)
    if metrics.get("trades") != filled:
        raise LiveCheckFailed(f"/metrics counts {metrics.get('trades')} trades, not {filled}")
    ends_on_final("/metrics", metrics, "final_seq", "final_hash")
    rebuild = api.expect(200, "POST", f"{base}/rebuild", token=token)
    if rebuild.get("status") != "identical":
        raise LiveCheckFailed(f"rebuild found differences: {_short(rebuild)}")
    ends_on_final("rebuild", rebuild, "final_seq", "final_hash")
    log(
        f"projections agree with the log: {filled} fills, {valued} value points, "
        "state, verify, holdings, metrics and rebuild end on the final hash"
    )


def check_one_active_run(api: Api, token: str, base: str, run_path: str, job_id: str) -> None:
    """A run with a new idempotency key while ``job_id`` is still queued or running is
    refused with 409 naming that job. If the first run already finished (a very fast
    worker), the rule cannot be observed and a second run is legitimately accepted."""
    other = {"Idempotency-Key": f"live-check-{uuid.uuid4()}"}
    status, body = api.call("POST", f"{base}/runs", token=token, headers=other)
    if status == 409:
        if not isinstance(body, dict) or body.get("job_id") != job_id:
            raise LiveCheckFailed(f"the 409 does not name the active job {job_id}: {_short(body)}")
        log("a second run while the first is active is refused (409 run-in-progress)")
        return
    if status == 202:
        current = api.expect(200, "GET", run_path, token=token)
        if current.get("status") in ("succeeded", "failed"):
            log("the first run had already finished, so the one-active-run rule was not observed")
            return
        raise LiveCheckFailed(
            f"a second run was accepted while job {job_id} is {current.get('status')}"
        )
    raise LiveCheckFailed(f"a second run key answered {status}: {_short(body)}")


BENCHMARK_LIMIT_SECONDS = 60.0


def run_benchmark(api: Api, token: str, env_id: str, name: str) -> None:
    """A-NFR-01: a momentum run over the 40-instrument, 252-session benchmark environment
    must succeed with an intact log in under 60 s, from submit to success."""
    strategy = api.expect(
        201,
        "POST",
        f"{TRADING}/strategies",
        token=token,
        body={
            "name": f"{name} benchmark",
            "kind": "momentum",
            "params": {
                "lookback": 60,
                "top_n": 10,
                "rebalance_every": 5,
                "max_position": "0.15",
            },
        },
    )
    portfolio = api.expect(
        201,
        "POST",
        f"{TRADING}/portfolios",
        token=token,
        body={
            "name": f"{name} benchmark",
            "strategy_id": strategy["id"],
            "initial_capital": "1000000",
            "cost_model": {"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"},
            "slippage_model": {"kind": "volume", "bps": "10"},
            "replay_environment_id": env_id,
        },
    )
    base = f"{TRADING}/portfolios/{portfolio['id']}"
    started = time.monotonic()
    submitted = api.expect(
        202,
        "POST",
        f"{base}/runs",
        token=token,
        headers={"Idempotency-Key": f"live-benchmark-{uuid.uuid4()}"},
    )
    run = wait_for_run(
        api, token, f"{base}/runs/{submitted['job_id']}", 2 * BENCHMARK_LIMIT_SECONDS
    )
    elapsed = time.monotonic() - started
    result = run.get("result") or {}
    events = all_events(api, token, f"{base}/events")
    check_chain(events, result.get("final_hash", ""), result.get("final_seq", -1))
    sessions = sum(1 for e in events if e.get("type") == "TICK")
    if elapsed >= BENCHMARK_LIMIT_SECONDS:
        raise LiveCheckFailed(
            f"A-NFR-01: the benchmark run took {elapsed:.1f}s, over {BENCHMARK_LIMIT_SECONDS:.0f}s"
        )
    log(
        f"A-NFR-01 benchmark: {sessions} sessions, {len(events)} events, chain intact, "
        f"{elapsed:.1f}s from submit to success (limit {BENCHMARK_LIMIT_SECONDS:.0f}s)"
    )


def live_check() -> None:
    api = Api(_setting("QS_LIVE_BASE_URL"))
    env_id = _setting("QS_LIVE_ENV_ID")
    username = _setting("QS_LIVE_USERNAME")
    password = _setting("QS_LIVE_PASSWORD")
    viewer = os.environ.get("QS_LIVE_VIEWER_USERNAME", "")
    timeout = float(_setting("QS_LIVE_TIMEOUT_SECONDS", "180"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"live check {stamp} {uuid.uuid4().hex[:8]}"

    log(f"against {api.base_url}, demo environment {env_id}")
    wait_until_ready(api)
    api.expect(
        401,
        "POST",
        f"{TRADING}/strategies",
        body={"name": name, "kind": "buy_and_hold", "params": {}},
    )
    log("unauthenticated POST /strategies is refused (401)")

    token = sign_in(api, username, password)
    log(f"signed in as {username}")
    strategy = api.expect(
        201,
        "POST",
        f"{TRADING}/strategies",
        token=token,
        body={"name": name, "kind": "buy_and_hold", "params": {}},
    )
    portfolio = api.expect(
        201,
        "POST",
        f"{TRADING}/portfolios",
        token=token,
        body={
            "name": name,
            "strategy_id": strategy["id"],
            "initial_capital": "10000",
            "replay_environment_id": env_id,
        },
    )
    portfolio_id = portfolio["id"]
    base = f"{TRADING}/portfolios/{portfolio_id}"
    log(f"strategy {strategy['id']}, portfolio {portfolio_id} ({name})")

    key = {"Idempotency-Key": f"live-check-{uuid.uuid4()}"}
    first = api.expect(202, "POST", f"{base}/runs", token=token, headers=key)
    again = api.expect(202, "POST", f"{base}/runs", token=token, headers=key)
    job_id = first["job_id"]
    if again["job_id"] != job_id or first.get("created") is not True or again.get("created"):
        raise LiveCheckFailed(
            f"the repeated submit is not the same job: {_short(first)} then {_short(again)}"
        )
    log(f"run submitted as job {job_id}; the repeated submit returned the same job")
    run_path = f"{base}/runs/{job_id}"
    check_one_active_run(api, token, base, run_path, job_id)

    if viewer:
        viewer_token = sign_in(api, viewer, password)
        api.expect(200, "GET", run_path, token=viewer_token)
        api.expect(403, "POST", f"{base}/runs", token=viewer_token, headers=key)
        log(f"{viewer} may read the run but not start one (403)")
    quant = os.environ.get("QS_LIVE_QUANT_USERNAME", "")
    if quant:
        quant_token = sign_in(api, quant, password)
        api.expect(
            403,
            "PUT",
            f"{TRADING}/strategies/{strategy['id']}",
            token=quant_token,
            body={"name": f"{name} edited", "kind": "buy_and_hold", "params": {}},
        )
        log(f"{quant} may not edit {username}'s strategy (403)")

    run = wait_for_run(api, token, run_path, timeout)
    result = run.get("result") or {}
    final_hash, final_seq = result.get("final_hash"), result.get("final_seq")
    if not isinstance(final_hash, str) or not isinstance(final_seq, int):
        raise LiveCheckFailed(f"the run succeeded without a final hash and seq: {_short(result)}")

    events = all_events(api, token, f"{base}/events")
    check_chain(events, final_hash, final_seq)
    reloaded = api.expect(200, "GET", base, token=token)
    if reloaded.get("source_fingerprint") != result.get("source_fingerprint"):
        raise LiveCheckFailed(
            f"the portfolio's source fingerprint {reloaded.get('source_fingerprint')} is not "
            f"the run's {result.get('source_fingerprint')}"
        )
    check_projections(api, token, base, events, result)
    benchmark = os.environ.get("QS_LIVE_BENCHMARK_ENV_ID", "")
    if benchmark:
        run_benchmark(api, token, benchmark, name)

    log("passed")
    log(f"  portfolio    {portfolio_id}")
    log(f"  job          {job_id}")
    log(f"  events       {len(events)} (seq 1..{final_seq}, chain intact)")
    log(f"  final value  {result.get('final_value')}")
    log(f"  final hash   {final_hash}")


def main(argv: Sequence[str]) -> int:
    if list(argv) == ["--self-test"]:
        import doctest

        failures, tests = doctest.testmod()
        print(f"self-test: {tests - failures}/{tests} examples passed")
        return 1 if failures or not tests else 0
    try:
        live_check()
    except LiveCheckFailed as error:
        print(f"trading live check FAILED: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
