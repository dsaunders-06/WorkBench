"""Engine lifecycle management.

The Orchestrator owns the EventBus and the set of registered engines,
starting and stopping them together. No strategy/regime/risk engines are
registered yet in M1 - this only proves the lifecycle wiring that later
milestones will plug into.
"""

from __future__ import annotations

import logging
from typing import Protocol

from qat.domain.bus import EventBus

logger = logging.getLogger(__name__)


class Engine(Protocol):
    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class Orchestrator:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._engines: list[Engine] = []
        self._running = False

    def register(self, engine: Engine) -> None:
        self._engines.append(engine)

    async def start_all(self) -> None:
        if self._running:
            return
        for engine in self._engines:
            logger.info("Starting engine: %s", engine.name)
            await engine.start()
        self._running = True

    async def stop_all(self) -> None:
        if not self._running:
            return
        for engine in reversed(self._engines):
            logger.info("Stopping engine: %s", engine.name)
            await engine.stop()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
