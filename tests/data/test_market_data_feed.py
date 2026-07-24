from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest

from qat.data.market_data import MarketDataFeed, RawTick, SyntheticMarketDataSource
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataEvent


class _FiniteSource:
    """Yields one tick per symbol then stops - simulates a feed going quiet."""

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        for symbol in symbols:
            yield RawTick(symbol=symbol, ts=datetime.now(UTC), price=100.0, volume=10.0)


@pytest.mark.asyncio
async def test_synthetic_source_publishes_market_data_events():
    bus = EventBus()
    received: list[MarketDataEvent] = []

    async def handler(event: MarketDataEvent) -> None:
        received.append(event)

    bus.subscribe(MarketDataEvent, handler)
    source = SyntheticMarketDataSource(seed=1, interval_seconds=0.01)
    feed = MarketDataFeed(bus, source, ["AAPL"], staleness_seconds=10, staleness_check_interval=10)

    await feed.start()
    await asyncio.sleep(0.05)
    await feed.stop()

    assert len(received) > 0
    assert received[0].symbol == "AAPL"


async def _take(
    source: SyntheticMarketDataSource, symbols: Sequence[str], count: int
) -> list[RawTick]:
    result: list[RawTick] = []
    async for tick in source.stream_ticks(symbols):
        result.append(tick)
        if len(result) >= count:
            break
    return result


@pytest.mark.asyncio
async def test_same_seed_produces_same_price_sequence():
    ticks_a = await _take(SyntheticMarketDataSource(seed=5), ["AAPL"], 3)
    ticks_b = await _take(SyntheticMarketDataSource(seed=5), ["AAPL"], 3)

    assert [t.price for t in ticks_a] == [t.price for t in ticks_b]


@pytest.mark.asyncio
async def test_staleness_event_fires_after_feed_goes_quiet():
    bus = EventBus()
    stale_events: list[DataStaleEvent] = []

    async def handler(event: DataStaleEvent) -> None:
        stale_events.append(event)

    bus.subscribe(DataStaleEvent, handler)
    feed = MarketDataFeed(
        bus, _FiniteSource(), ["AAPL"], staleness_seconds=0.02, staleness_check_interval=0.02
    )

    await feed.start()
    await asyncio.sleep(0.1)
    await feed.stop()

    assert len(stale_events) > 0
    assert stale_events[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_no_staleness_event_while_feed_is_active():
    bus = EventBus()
    stale_events: list[DataStaleEvent] = []

    async def handler(event: DataStaleEvent) -> None:
        stale_events.append(event)

    bus.subscribe(DataStaleEvent, handler)
    source = SyntheticMarketDataSource(seed=2, interval_seconds=0.01)
    feed = MarketDataFeed(bus, source, ["AAPL"], staleness_seconds=5, staleness_check_interval=0.02)

    await feed.start()
    await asyncio.sleep(0.06)
    await feed.stop()

    assert stale_events == []
