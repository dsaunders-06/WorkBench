"""Real-time ingestion pipeline: source -> bounded queue -> validated events
(spec §D/§17.1), plus the data-staleness monitor (§17.2, §18.2 kill-switch trigger).

MarketDataSource is the extension point: SyntheticMarketDataSource here is
deterministic and seeded for tests/dev. An IBKR-backed implementation
(reqMktData over ib_async) is added in M7 behind this same interface -
nothing else in the pipeline needs to change when that lands.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataEvent, MarketDataFeedEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RawTick:
    symbol: str
    ts: datetime
    price: float
    volume: float


class MarketDataSource(Protocol):
    def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]: ...


class SyntheticMarketDataSource:
    """Deterministic seeded random-walk tick generator."""

    def __init__(
        self, seed: int = 0, interval_seconds: float = 0.0, base_price: float = 100.0
    ) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic ticks, not crypto
        self._interval = interval_seconds
        self._base_price = base_price
        self._prices: dict[str, float] = {}

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        while True:
            for symbol in symbols:
                price = self._prices.setdefault(symbol, self._base_price)
                price = max(0.01, price + self._rng.uniform(-0.5, 0.5))
                self._prices[symbol] = price
                yield RawTick(
                    symbol=symbol,
                    ts=datetime.now(UTC),
                    price=round(price, 2),
                    volume=float(self._rng.randint(1, 1000)),
                )
            if self._interval:
                await asyncio.sleep(self._interval)


class MarketDataFeed:
    """Engine (per domain.orchestrator.Engine protocol): ingests from a
    MarketDataSource, publishes MarketDataEvent per tick, and raises
    DataStaleEvent when a symbol stops updating within staleness_seconds."""

    name = "market-data-feed"

    def __init__(
        self,
        bus: EventBus,
        source: MarketDataSource,
        symbols: Sequence[str],
        staleness_seconds: float = 60.0,
        staleness_check_interval: float = 5.0,
        queue_maxsize: int = 1000,
        feed_down_seconds: float = 300.0,
    ) -> None:
        self.bus = bus
        self.source = source
        self.symbols = list(symbols)
        self.staleness_seconds = staleness_seconds
        self.staleness_check_interval = staleness_check_interval
        self.feed_down_seconds = feed_down_seconds
        self._queue: asyncio.Queue[RawTick] = asyncio.Queue(maxsize=queue_maxsize)
        self._last_seen: dict[str, datetime] = {}
        self._tasks: list[asyncio.Task[None]] = []
        # Feed-level health, tracked separately from per-symbol staleness.
        # Measured from when the feed started rather than from the first tick,
        # which is the case per-symbol staleness cannot see: a source that has
        # never produced anything leaves _last_seen empty, so every symbol is
        # skipped and nothing is ever reported.
        self._started_at: datetime | None = None
        self._last_tick_at: datetime | None = None
        self._feed_healthy = True

    async def start(self) -> None:
        # Cleared so a feed restarted after a break (M19: the overnight stand
        # down) does not immediately report every symbol as stale against a
        # last-seen timestamp from before it slept.
        self._last_seen.clear()
        self._started_at = datetime.now(UTC)
        self._last_tick_at = None
        self._feed_healthy = True
        self._tasks = [
            asyncio.create_task(self._ingest_loop()),
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._staleness_loop()),
            asyncio.create_task(self._feed_health_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _ingest_loop(self) -> None:
        async for tick in self.source.stream_ticks(self.symbols):
            await self._queue.put(tick)

    async def _process_loop(self) -> None:
        while True:
            tick = await self._queue.get()
            self._last_seen[tick.symbol] = tick.ts
            self._last_tick_at = datetime.now(UTC)
            if not self._feed_healthy:
                self._feed_healthy = True
                await self.bus.publish(
                    MarketDataFeedEvent(healthy=True, reason="market data is flowing again")
                )
            await self.bus.publish(
                MarketDataEvent(
                    symbol=tick.symbol, price=tick.price, volume=tick.volume, ts=tick.ts
                )
            )

    async def _feed_health_loop(self) -> None:
        """Is anything arriving at all?

        Deliberately not a kill-switch trigger. No ticks means no feature
        snapshots, so no signals and no orders - the danger of a dead feed is
        not that it trades wrongly but that nobody notices it has stopped. The
        answer to that is to say so, loudly, not to demand a manual reset for
        an outage that may clear itself.
        """
        while True:
            await asyncio.sleep(self.staleness_check_interval)
            if not self._feed_healthy:
                continue
            reference = self._last_tick_at or self._started_at
            if reference is None:
                continue
            quiet = (datetime.now(UTC) - reference).total_seconds()
            if quiet <= self.feed_down_seconds:
                continue
            self._feed_healthy = False
            reason = (
                f"no market data for {quiet / 60:.0f} minutes"
                if self._last_tick_at is not None
                else f"no market data since the feed started {quiet / 60:.0f} minutes ago"
            )
            logger.error("MARKET DATA DOWN: %s", reason)
            await self.bus.publish(
                MarketDataFeedEvent(healthy=False, reason=reason, seconds_since_last_tick=quiet)
            )

    async def _staleness_loop(self) -> None:
        while True:
            await asyncio.sleep(self.staleness_check_interval)
            now = datetime.now(UTC)
            for symbol in self.symbols:
                last = self._last_seen.get(symbol)
                if last is None:
                    continue
                elapsed = (now - last).total_seconds()
                if elapsed > self.staleness_seconds:
                    await self.bus.publish(
                        DataStaleEvent(symbol=symbol, seconds_since_update=elapsed)
                    )
