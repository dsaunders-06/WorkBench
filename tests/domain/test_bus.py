from __future__ import annotations

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent, MarketDataEvent


@pytest.mark.asyncio
async def test_publish_delivers_to_subscribed_handler():
    bus = EventBus()
    received: list[MarketDataEvent] = []

    async def handler(event: MarketDataEvent) -> None:
        received.append(event)

    bus.subscribe(MarketDataEvent, handler)
    event = MarketDataEvent(symbol="AAPL", price=100.0, volume=10)
    await bus.publish(event)

    assert received == [event]


@pytest.mark.asyncio
async def test_publish_delivers_to_multiple_handlers():
    bus = EventBus()
    counts = {"a": 0, "b": 0}

    async def handler_a(event: MarketDataEvent) -> None:
        counts["a"] += 1

    async def handler_b(event: MarketDataEvent) -> None:
        counts["b"] += 1

    bus.subscribe(MarketDataEvent, handler_a)
    bus.subscribe(MarketDataEvent, handler_b)
    await bus.publish(MarketDataEvent(symbol="AAPL", price=100.0, volume=10))

    assert counts == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_publish_does_not_cross_deliver_event_types():
    bus = EventBus()
    received: list[object] = []

    async def handler(event: MarketDataEvent) -> None:
        received.append(event)

    bus.subscribe(MarketDataEvent, handler)
    await bus.publish(KillSwitchEvent(reason="test", triggered_by="unit-test"))

    assert received == []


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received: list[object] = []

    async def handler(event: MarketDataEvent) -> None:
        received.append(event)

    bus.subscribe(MarketDataEvent, handler)
    bus.unsubscribe(MarketDataEvent, handler)
    await bus.publish(MarketDataEvent(symbol="AAPL", price=100.0, volume=10))

    assert received == []


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.publish(MarketDataEvent(symbol="AAPL", price=100.0, volume=10))


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_other_handlers():
    bus = EventBus()
    received: list[object] = []

    async def failing_handler(event: MarketDataEvent) -> None:
        raise RuntimeError("boom")

    async def ok_handler(event: MarketDataEvent) -> None:
        received.append(event)

    bus.subscribe(MarketDataEvent, failing_handler)
    bus.subscribe(MarketDataEvent, ok_handler)
    await bus.publish(MarketDataEvent(symbol="AAPL", price=100.0, volume=10))

    assert len(received) == 1
