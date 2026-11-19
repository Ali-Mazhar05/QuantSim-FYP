"""Long-running loops (job worker, outbox relay) run inside the API process.

On DEV each service runs its worker and relay in the API container instead of in
containers of their own (``QS_EMBEDDED_WORKERS=true``), which saves memory and disk on a
laptop host. :class:`BackgroundTasks` starts the loops with the app and stops them
cleanly with it: ``on_startup=[tasks.start], on_shutdown=[tasks.stop]``.
"""

import asyncio
from collections.abc import Awaitable, Callable

from qs_template.logging import get_logger

log = get_logger(__name__)


class BackgroundTasks:
    def __init__(self, stop_timeout_seconds: float = 10.0) -> None:
        self._loops: list[tuple[str, Callable[[], Awaitable[None]], Callable[[], None]]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self.stop_timeout_seconds = stop_timeout_seconds

    def add(self, name: str, run: Callable[[], Awaitable[None]], stop: Callable[[], None]) -> None:
        """Register a loop: ``run`` until ``stop`` is called."""
        self._loops.append((name, run, stop))

    def __len__(self) -> int:
        return len(self._loops)

    async def start(self) -> None:
        for name, run, _ in self._loops:
            self._tasks.append(asyncio.create_task(self._guard(name, run), name=name))

    async def stop(self) -> None:
        for _, _, stop in self._loops:
            stop()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=self.stop_timeout_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    @staticmethod
    async def _guard(name: str, run: Callable[[], Awaitable[None]]) -> None:
        try:
            await run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background loop stopped with an error", loop=name)
