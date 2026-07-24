"""In-process async pub/sub EventBus.

Engines subscribe to specific event types and never call one another
directly (spec §C). Handlers run concurrently as asyncio tasks so a slow
subscriber cannot block publication to others.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from qat.domain.events import Event

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[E], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler[Any]]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].remove(handler)

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            return
        results = await asyncio.gather(
            *(self._run_handler(handler, event) for handler in handlers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.exception("EventBus handler failed", exc_info=result)

    async def _run_handler(self, handler: Handler[Any], event: Event) -> None:
        await handler(event)
