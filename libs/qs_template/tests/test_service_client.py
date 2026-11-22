"""Kit K3: the service-to-service client and the DEV service token (A-FR-19)."""

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from qs_template import ServiceError, ServiceSettings
from qs_template.auth import SERVICE_PRINCIPAL, Authenticator, Role, StaticKeys
from qs_template.service_client import (
    CALLER_HEADER,
    IDEMPOTENCY_HEADER,
    CircuitBreaker,
    ServiceCallError,
    ServiceClient,
    StaticServiceToken,
)

TOKEN = SecretStr("dev-service-token-" + "x" * 32)
BASE = "http://market:8000"


async def no_sleep(_: float) -> None:
    return None


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retries: int = 3,
    breaker: CircuitBreaker | None = None,
) -> ServiceClient:
    return ServiceClient(
        BASE,
        caller="trading",
        tokens=StaticServiceToken(TOKEN, environment="dev"),
        retries=retries,
        breaker=breaker,
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )


class Flaky:
    """Answers with the given statuses in turn, then 200."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.statuses:
            return httpx.Response(self.statuses.pop(0))
        return httpx.Response(200, json={"items": [], "next_after_seq": None})


class TestCalls:
    async def test_sends_the_service_token_and_caller(self) -> None:
        handler = Flaky()
        client = client_for(handler)
        body = await client.get_json("/api/market/environments")
        assert body == {"items": [], "next_after_seq": None}
        sent = handler.requests[0]
        assert sent.headers["Authorization"] == f"Bearer {TOKEN.get_secret_value()}"
        assert sent.headers[CALLER_HEADER] == "trading"
        await client.close()

    async def test_retries_a_read_until_it_succeeds(self) -> None:
        handler = Flaky(503, 502)
        client = client_for(handler)
        response = await client.get("/api/market/environments")
        assert response.status_code == 200
        assert len(handler.requests) == 3
        await client.close()

    async def test_provider_down_is_a_controlled_failure(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = client_for(down, retries=2)
        with pytest.raises(ServiceCallError) as caught:
            await client.get("/api/market/environments")
        assert caught.value.status == 503
        assert caught.value.type == "urn:quantsim:problem:upstream-down"
        assert caught.value.extra["target"] == BASE
        assert isinstance(caught.value, ServiceError)
        await client.close()

    async def test_timeouts_are_retried(self) -> None:
        calls = 0

        def slow_then_ok(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(200, json={})

        client = client_for(slow_then_ok)
        assert (await client.get("/x")).status_code == 200
        assert calls == 2
        await client.close()

    async def test_a_write_without_idempotency_key_is_sent_once(self) -> None:
        handler = Flaky(503)
        client = client_for(handler)
        with pytest.raises(ServiceCallError):
            await client.post("/api/simulation/runs", json={})
        assert len(handler.requests) == 1
        await client.close()

    async def test_a_write_with_idempotency_key_is_retried(self) -> None:
        handler = Flaky(503)
        client = client_for(handler)
        response = await client.post("/api/simulation/runs", json={}, idempotency_key="run-42")
        assert response.status_code == 200
        assert [r.headers[IDEMPOTENCY_HEADER] for r in handler.requests] == ["run-42"] * 2
        await client.close()

    async def test_client_errors_are_not_retried_and_carry_the_problem(self) -> None:
        requests: list[httpx.Request] = []

        def not_found(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(404, json={"type": "urn:quantsim:problem:not-found"})

        client = client_for(not_found)
        with pytest.raises(ServiceCallError) as caught:
            await client.get("/api/market/environments/missing")
        assert caught.value.status == 502
        assert caught.value.extra["upstream_status"] == 404
        assert caught.value.extra["upstream_body"]["type"] == "urn:quantsim:problem:not-found"
        assert len(requests) == 1
        assert client.breaker.state == "closed"
        await client.close()


class TestCircuitBreaker:
    async def test_opens_after_repeated_failures_and_fails_fast(self) -> None:
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=2, reset_after_seconds=30, clock=lambda: now[0])
        handler = Flaky(*[503] * 10)
        client = client_for(handler, retries=1, breaker=breaker)

        with pytest.raises(ServiceCallError):
            await client.get("/x")
        assert breaker.state == "open"
        sent = len(handler.requests)

        with pytest.raises(ServiceCallError) as caught:
            await client.get("/x")
        assert caught.value.type == "urn:quantsim:problem:circuit-open"
        assert len(handler.requests) == sent  # nothing was sent
        await client.close()

    async def test_half_opens_after_the_reset_time_and_closes_on_success(self) -> None:
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=30, clock=lambda: now[0])
        handler = Flaky(503)
        client = client_for(handler, retries=0, breaker=breaker)

        with pytest.raises(ServiceCallError):
            await client.get("/x")
        assert breaker.state == "open"
        now[0] = 31.0
        assert breaker.state == "half-open"
        assert (await client.get("/x")).status_code == 200
        assert breaker.state == "closed"
        await client.close()

    def test_a_failed_trial_opens_it_again(self) -> None:
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=3, reset_after_seconds=10, clock=lambda: now[0])
        for _ in range(3):
            breaker.record_failure()
        now[0] = 11.0
        assert breaker.allow()
        assert not breaker.allow()  # only one trial at a time
        breaker.record_failure()
        assert breaker.state == "open"


class TestStaticToken:
    @pytest.mark.parametrize("environment", ["test", "acc", "prod"])
    def test_refused_outside_local_and_dev(self, environment: str) -> None:
        with pytest.raises(ValueError, match="local and dev only"):
            StaticServiceToken(TOKEN, environment=environment)

    def test_refuses_a_short_token(self) -> None:
        with pytest.raises(ValueError, match="32 characters"):
            StaticServiceToken(SecretStr("short"), environment="dev")

    async def test_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QS_SERVICE_TOKEN", TOKEN.get_secret_value())
        settings = ServiceSettings(
            service_name="trading", environment="dev", database_url=SecretStr("sqlite://")
        )
        assert await StaticServiceToken.from_settings(settings).token() == TOKEN.get_secret_value()


def settings_with(environment: str, token: SecretStr | None) -> ServiceSettings:
    return ServiceSettings(
        service_name="market",
        environment=environment,
        database_url=SecretStr("sqlite://"),
        service_token=token,
    )


class TestAcceptingTheToken:
    async def test_the_dev_token_acts_as_a_read_only_service(self) -> None:
        auth = Authenticator(settings_with("dev", TOKEN), jwks=StaticKeys({"keys": []}))
        principal = await auth.verify(TOKEN.get_secret_value())
        assert principal is SERVICE_PRINCIPAL
        assert principal.is_service
        assert principal.role is Role.VIEWER

    async def test_a_forged_token_is_refused(self) -> None:
        auth = Authenticator(settings_with("dev", TOKEN), jwks=StaticKeys({"keys": []}))
        with pytest.raises(ServiceError) as caught:
            await auth.verify(TOKEN.get_secret_value() + "x")
        assert caught.value.status == 401

    async def test_without_a_configured_token_nothing_is_accepted(self) -> None:
        auth = Authenticator(settings_with("dev", None), jwks=StaticKeys({"keys": []}))
        with pytest.raises(ServiceError) as caught:
            await auth.verify(TOKEN.get_secret_value())
        assert caught.value.status == 401

    @pytest.mark.parametrize("environment", ["test", "acc", "prod"])
    def test_configuring_it_outside_dev_fails_at_startup(self, environment: str) -> None:
        with pytest.raises(ValueError, match="local and dev only"):
            Authenticator(settings_with(environment, TOKEN), jwks=StaticKeys({"keys": []}))
