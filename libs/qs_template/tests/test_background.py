import asyncio

from qs_template.background import BackgroundTasks


class Loop:
    def __init__(self, fail: bool = False) -> None:
        self.stopping = asyncio.Event()
        self.ran = False
        self.fail = fail

    async def run(self) -> None:
        self.ran = True
        if self.fail:
            raise RuntimeError("boom")
        await self.stopping.wait()

    def stop(self) -> None:
        self.stopping.set()


async def test_loops_start_with_the_app_and_stop_with_it() -> None:
    first, second = Loop(), Loop()
    tasks = BackgroundTasks()
    tasks.add("first", first.run, first.stop)
    tasks.add("second", second.run, second.stop)
    assert len(tasks) == 2
    await tasks.start()
    await asyncio.sleep(0)
    assert first.ran and second.ran
    await tasks.stop()
    assert first.stopping.is_set() and second.stopping.is_set()


async def test_a_failing_loop_does_not_break_shutdown() -> None:
    broken = Loop(fail=True)
    tasks = BackgroundTasks()
    tasks.add("broken", broken.run, broken.stop)
    await tasks.start()
    await asyncio.sleep(0)
    await tasks.stop()


async def test_a_loop_that_ignores_stop_is_cancelled() -> None:
    async def stubborn() -> None:
        await asyncio.sleep(3600)

    tasks = BackgroundTasks(stop_timeout_seconds=0.05)
    tasks.add("stubborn", stubborn, lambda: None)
    await tasks.start()
    await tasks.stop()


async def test_stop_without_start_is_harmless() -> None:
    await BackgroundTasks().stop()
