"""The shared request budget, on fakeredis."""

import asyncio
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr

from qs_market.vendor.base import BudgetExhausted, BudgetUnavailable
from qs_market.vendor.budget import RequestBudget

KEY = SecretStr("budget-key-abcdef")


class BrokenRedis(FakeAsyncRedis):
    def pipeline(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("redis is down")


def make(redis: FakeAsyncRedis, **kwargs: Any) -> RequestBudget:
    return RequestBudget(redis, KEY, clock=lambda: 7200.0, **kwargs)


async def test_exhausts_then_raises_without_sleeping() -> None:
    budget = make(FakeAsyncRedis(), limit=3, reserve_for_scheduled=0)
    assert [await budget.acquire() for _ in range(3)] == [2, 1, 0]
    with pytest.raises(BudgetExhausted):
        await budget.acquire()


async def test_budget_is_respected_across_concurrent_callers() -> None:
    redis = FakeAsyncRedis()
    budgets = [make(redis, limit=10, reserve_for_scheduled=0) for _ in range(4)]

    async def take(budget: RequestBudget) -> bool:
        try:
            await budget.acquire()
        except BudgetExhausted:
            return False
        return True

    results = await asyncio.gather(*(take(budgets[i % 4]) for i in range(40)))
    assert results.count(True) == 10


async def test_reserve_keeps_backfill_out_of_the_scheduled_share() -> None:
    budget = make(FakeAsyncRedis(), limit=45, reserve_for_scheduled=40)
    for _ in range(5):
        await budget.acquire("backfill")
    with pytest.raises(BudgetExhausted):
        await budget.acquire("backfill")
    for _ in range(40):  # the scheduled run still has its whole share
        await budget.acquire("scheduled")
    with pytest.raises(BudgetExhausted):
        await budget.acquire("scheduled")


async def test_window_rolls_over() -> None:
    now = [0.0]
    budget = RequestBudget(
        FakeAsyncRedis(), KEY, limit=1, reserve_for_scheduled=0, clock=lambda: now[0]
    )
    await budget.acquire()
    with pytest.raises(BudgetExhausted):
        await budget.acquire()
    now[0] = 3600.0
    await budget.acquire()


async def test_redis_down_fails_closed() -> None:
    with pytest.raises(BudgetUnavailable):
        await make(BrokenRedis()).acquire()


async def test_key_is_hashed_in_redis() -> None:
    redis = FakeAsyncRedis()
    await make(redis).acquire()
    keys = [k.decode() if isinstance(k, bytes) else k for k in await redis.keys("*")]
    assert keys
    assert all("budget-key-abcdef" not in k for k in keys)


def test_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        RequestBudget(FakeAsyncRedis(), KEY, limit=5, reserve_for_scheduled=6)
