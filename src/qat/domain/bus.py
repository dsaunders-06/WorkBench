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
        self._critical_handlers: set[tuple[type[Event], Handler[Any]]] = set()

    def subscribe(
        self, event_type: type[E], handler: Handler[E], *, critical: bool = False
    ) -> None:
        self._handlers[event_type].append(handler)
        if critical:
            self._critical_handlers.add((event_type, handler))

    def unsubscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].remove(handler)
        self._critical_handlers.discard((event_type, handler))

    async def publish(self, event: Event) -> tuple[Exception, ...]:
        # A handler can subscribe/unsubscribe while another handler awaits.
        # Delivery and result classification must use one immutable snapshot.
        handlers = tuple(self._handlers.get(type(event), ()))
        if not handlers:
            return ()
        critical = tuple((type(event), handler) in self._critical_handlers for handler in handlers)
        results = await asyncio.gather(
            *(self._run_handler(handler, event) for handler in handlers),
            return_exceptions=True,
        )
        failures: list[Exception] = []
        for is_critical, result in zip(critical, results, strict=True):
            if isinstance(result, Exception):
                logger.exception("EventBus handler failed", exc_info=result)
                if is_critical:
                    failures.append(result)
        return tuple(failures)

    async def _run_handler(self, handler: Handler[Any], event: Event) -> None:
        await handler(event)
