import time
import uuid

import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from qs_template import ServiceError
from qs_template.auth import Principal, Role
from qs_template.revocation import RevocationList

USER = uuid.UUID("5c2d8e1a-7b3f-4e9d-8a6c-1f2e3d4c5b6a")


def principal(issued_at: int, user_id: uuid.UUID = USER) -> Principal:
    return Principal(
        user_id=user_id, username="u", role=Role.QUANT, token_id="t", issued_at=issued_at
    )


@pytest.fixture
def revocations() -> RevocationList:
    return RevocationList(FakeAsyncRedis())


async def test_tokens_are_valid_until_revoked(revocations: RevocationList) -> None:
    assert await revocations.is_revoked(principal(int(time.time()))) is False


async def test_revocation_cuts_off_earlier_tokens(revocations: RevocationList) -> None:
    earlier = principal(int(time.time()) - 600)

    await revocations.revoke_user(USER)

    assert await revocations.is_revoked(earlier) is True


def principal_ms(issued_at_ms: int) -> Principal:
    return Principal(
        user_id=USER,
        username="u",
        role=Role.QUANT,
        token_id="t",
        issued_at=issued_at_ms // 1000,
        issued_at_ms=issued_at_ms,
    )


async def test_cut_off_is_exact_to_the_millisecond(revocations: RevocationList) -> None:
    cutoff_ms = await revocations.revoke_user(USER)

    # A sign-in right after the revocation, even in the same second, works
    assert await revocations.is_revoked(principal_ms(cutoff_ms)) is False
    assert await revocations.is_revoked(principal_ms(cutoff_ms + 1)) is False
    assert await revocations.is_revoked(principal_ms(cutoff_ms - 1)) is True


async def test_tokens_without_millisecond_times_err_on_refusal(
    revocations: RevocationList,
) -> None:
    cutoff_ms = await revocations.revoke_user(USER)

    same_second = principal(cutoff_ms // 1000)

    assert same_second.issued_at_ms <= cutoff_ms
    assert await revocations.is_revoked(same_second) is (same_second.issued_at_ms < cutoff_ms)


async def test_revocation_only_affects_that_user(revocations: RevocationList) -> None:
    await revocations.revoke_user(USER)

    other = principal(int(time.time()) - 600, user_id=uuid.uuid4())
    assert await revocations.is_revoked(other) is False


async def test_revocation_expires_with_the_longest_token_lifetime() -> None:
    redis = FakeAsyncRedis()
    revocations = RevocationList(redis, max_token_lifetime_seconds=900)

    await revocations.revoke_user(USER)

    ttl = await redis.ttl(f"qs:auth:revoked-before:{USER}")
    assert 0 < ttl <= 900


class BrokenRedis(FakeAsyncRedis):
    async def get(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("connection refused")


async def test_fails_closed_when_redis_is_down() -> None:
    revocations = RevocationList(BrokenRedis())

    with pytest.raises(ServiceError) as error:
        await revocations.is_revoked(principal(int(time.time())))

    assert error.value.status == 503
