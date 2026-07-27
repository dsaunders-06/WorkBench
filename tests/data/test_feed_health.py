"""A feed that never delivers must say so (spec M26).

Per-symbol staleness cannot cover this case and never could: it reads
`_last_seen`, which a symbol only enters once it has ticked. A source that
failed from its very first poll left the map empty, so every symbol was
skipped, no DataStaleEvent was raised, no kill-switch trip followed, and the
first unattended session spent six hours seventeen minutes on an open market
with no prices while the banner read AUTO-TRADE ACTIVE.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from qat.data.market_data import MarketDataFeed, RawTick
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataFeedEvent


class _SilentSource:
    """Never yields. The exact shape of the BRK-B outage."""

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        while True:
            await asyncio.sleep(0.01)
        yield  # pragma: no cover - unreachable, keeps this an async generator


class _OneTickThenSilence:
    def __init__(self) -> None:
        self.sent = False

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        from datetime import UTC, datetime

        yield RawTick(symbol=symbols[0], ts=datetime.now(UTC), price=100.0, volume=1.0)
        self.sent = True
        while True:
            await asyncio.sleep(0.01)


async def _collect(bus: EventBus) -> list[MarketDataFeedEvent]:
    seen: list[MarketDataFeedEvent] = []

    async def record(event: MarketDataFeedEvent) -> None:
        seen.append(event)

    bus.subscribe(MarketDataFeedEvent, record)
    return seen


async def test_a_feed_that_never_ticks_is_reported_down() -> None:
    bus = EventBus()
    seen = await _collect(bus)
    stale: list[DataStaleEvent] = []

    async def record_stale(event: DataStaleEvent) -> None:
        stale.append(event)

    bus.subscribe(DataStaleEvent, record_stale)

    feed = MarketDataFeed(
        bus,
        _SilentSource(),
        ["AAPL"],
        staleness_check_interval=0.01,
        feed_down_seconds=0.05,
    )
    await feed.start()
    await asyncio.sleep(0.3)
    await feed.stop()

    assert seen, "the feed went down and said nothing"
    assert seen[0].healthy is False
    assert "since the feed started" in seen[0].reason
    # The gap this closes: per-symbol staleness stays silent throughout,
    # because AAPL never ticked and so was never in _last_seen.
    assert stale == []


async def test_the_down_event_is_raised_once_not_every_check() -> None:
    """An alarm repeating every five seconds is an alarm nobody reads."""
    bus = EventBus()
    seen = await _collect(bus)

    feed = MarketDataFeed(
        bus, _SilentSource(), ["AAPL"], staleness_check_interval=0.01, feed_down_seconds=0.02
    )
    await feed.start()
    await asyncio.sleep(0.3)
    await feed.stop()

    assert len(seen) == 1


async def test_recovery_is_announced_so_the_banner_can_clear() -> None:
    bus = EventBus()
    seen = await _collect(bus)
    source = _OneTickThenSilence()

    feed = MarketDataFeed(
        bus, source, ["AAPL"], staleness_check_interval=0.01, feed_down_seconds=0.05
    )
    await feed.start()
    await asyncio.sleep(0.25)
    assert seen and seen[-1].healthy is False

    # A tick arriving after the outage must flip it back. Asserted on the
    # transition rather than the final event: this source is silent again
    # immediately afterwards, so it correctly goes down a second time, and
    # pinning the last event would be testing the sleep rather than the code.
    await feed._queue.put(RawTick(symbol="AAPL", ts=seen[-1].ts, price=101.0, volume=1.0))
    await asyncio.sleep(0.1)
    await feed.stop()

    recoveries = [event for event in seen if event.healthy]
    assert recoveries, "the feed came back and the banner was never told"
    assert "flowing again" in recoveries[0].reason
    assert seen.index(recoveries[0]) > 0, "recovery must follow the outage, not precede it"


async def test_a_healthy_feed_says_nothing() -> None:
    """Silence is the normal case and must stay silent."""
    bus = EventBus()
    seen = await _collect(bus)

    feed = MarketDataFeed(
        bus,
        _OneTickThenSilence(),
        ["AAPL"],
        staleness_check_interval=0.01,
        feed_down_seconds=5.0,
    )
    await feed.start()
    await asyncio.sleep(0.15)
    await feed.stop()

    assert seen == []
