"""Quote freshness excludes one symbol; it never halts the account (M28a).

The rail has never once fired correctly. Every trip it produced was a false
positive, and it was only ever masked by the feed being broken in other ways:

| Trip | Symbol | Reported age | Reality |
|---|---|---|---|
| 27 Jul | (feed dead) | - | never fired; per-symbol staleness skips symbols that never ticked |
| 28 Jul | BRK.B | 63,017s | thin on IEX, last print was the previous close |
| 28 Jul | HON | 97s | liquid; the poll interval itself |
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from qat.data.fundamentals import MockFundamentalsSource
from qat.data.market_data import MarketDataFeed, RawTick
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataEvent, RegimeEvent, SignalEvent
from qat.domain.strategies.engine import StrategyEngine


class _OneOldPrint:
    """Delivers a tick whose trade timestamp is already hours old - a thin
    ticker whose last print was the previous close."""

    def __init__(self, age_seconds: float) -> None:
        self.age_seconds = age_seconds

    async def stream_ticks(self, symbols):
        for symbol in symbols:
            yield RawTick(
                symbol=symbol,
                ts=datetime.now(UTC) - timedelta(seconds=self.age_seconds),
                price=100.0,
                volume=1.0,
            )
        while True:  # pragma: no cover - keeps the stream open
            await asyncio.sleep(0.05)


async def _collect(bus: EventBus) -> list[DataStaleEvent]:
    seen: list[DataStaleEvent] = []

    async def handler(event: DataStaleEvent) -> None:
        seen.append(event)

    bus.subscribe(DataStaleEvent, handler)
    return seen


@pytest.mark.asyncio
async def test_an_old_print_reports_that_symbol_stale():
    bus = EventBus()
    seen = await _collect(bus)
    feed = MarketDataFeed(
        bus,
        _OneOldPrint(age_seconds=7200),
        ["BRK.B"],
        staleness_seconds=900,
        staleness_check_interval=0.01,
    )

    await feed.start()
    await asyncio.sleep(0.15)
    await feed.stop()

    assert seen and seen[0].symbol == "BRK.B"
    assert seen[0].stale is True


@pytest.mark.asyncio
async def test_the_poll_interval_alone_is_not_staleness():
    """28 July: HON reported at 97s and halted the account. With a 60s poll
    against a 60s threshold that was arithmetic, not risk."""
    bus = EventBus()
    seen = await _collect(bus)
    feed = MarketDataFeed(
        bus,
        _OneOldPrint(age_seconds=97),
        ["HON"],
        staleness_seconds=900,
        staleness_check_interval=0.01,
    )

    await feed.start()
    await asyncio.sleep(0.1)
    await feed.stop()

    assert not seen, "a 97-second-old print is a normal poll interval"


@pytest.mark.asyncio
async def test_staleness_is_reported_on_the_edges_only():
    """A rail that republishes the same stale symbol every interval is noise."""
    bus = EventBus()
    seen = await _collect(bus)
    feed = MarketDataFeed(
        bus,
        _OneOldPrint(age_seconds=7200),
        ["BRK.B"],
        staleness_seconds=900,
        staleness_check_interval=0.01,
    )

    await feed.start()
    await asyncio.sleep(0.2)  # many check intervals
    await feed.stop()

    assert len(seen) == 1, "the transition is the news, not every check"


@pytest.mark.asyncio
async def test_a_stale_symbol_stops_producing_signals_and_others_continue():
    from qat.domain.strategies.base import Strategy

    class _AlwaysSignals:
        name = "always"

        def suitable_regimes(self):
            from qat.domain.regime import Regime

            return set(Regime)

        def params(self):
            return {}

        def on_features(self, snapshot):
            return [
                SignalEvent(
                    symbol=snapshot.symbol,
                    side="buy",
                    conviction=1.0,
                    strategy=self.name,
                    meta={},
                    ts=snapshot.as_of,
                )
            ]

    bus = EventBus()
    signals: list[SignalEvent] = []

    async def on_signal(event: SignalEvent) -> None:
        signals.append(event)

    bus.subscribe(SignalEvent, on_signal)
    strategy: Strategy = _AlwaysSignals()  # type: ignore[assignment]
    engine = StrategyEngine(bus, [strategy], MockFundamentalsSource(seed=1))
    await engine.start()

    # ⚠️ A REGIME FIRST, or this tests the wrong thing. Since 10 September the
    # engine refuses ALL entries until one is published, so without this every
    # symbol is excluded and the assertion below would pass for a reason that
    # has nothing to do with staleness - which is what it exists to measure.
    await bus.publish(RegimeEvent(label="sideways", probs={}, exposure_scalar=1.0))

    await bus.publish(DataStaleEvent(symbol="BRK.B", seconds_since_update=63_017.0, stale=True))
    for symbol in ("BRK.B", "AAPL"):
        await bus.publish(
            MarketDataEvent(symbol=symbol, price=100.0, volume=1.0, ts=datetime.now(UTC))
        )

    assert [s.symbol for s in signals] == ["AAPL"], "the stale symbol alone is excluded"

    # And it comes back when it prints again, rather than being lost for the session.
    signals.clear()
    await bus.publish(DataStaleEvent(symbol="BRK.B", seconds_since_update=3.0, stale=False))
    await bus.publish(
        MarketDataEvent(symbol="BRK.B", price=100.0, volume=1.0, ts=datetime.now(UTC))
    )
    await engine.stop()

    assert [s.symbol for s in signals] == ["BRK.B"]
