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
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataEvent


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
    ) -> None:
        self.bus = bus
        self.source = source
        self.symbols = list(symbols)
        self.staleness_seconds = staleness_seconds
        self.staleness_check_interval = staleness_check_interval
        self._queue: asyncio.Queue[RawTick] = asyncio.Queue(maxsize=queue_maxsize)
        self._last_seen: dict[str, datetime] = {}
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._ingest_loop()),
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._staleness_loop()),
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
            await self.bus.publish(
                MarketDataEvent(
                    symbol=tick.symbol, price=tick.price, volume=tick.volume, ts=tick.ts
                )
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
