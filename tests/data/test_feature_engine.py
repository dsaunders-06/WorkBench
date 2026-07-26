from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.data.feature_engine import FeatureEngine
from qat.domain.bus import EventBus
from qat.domain.events import FeatureEvent, MarketDataEvent

_BASE = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_feature_engine_publishes_feature_event_per_tick():
    bus = EventBus()
    received: list[FeatureEvent] = []

    async def handler(event: FeatureEvent) -> None:
        received.append(event)

    bus.subscribe(FeatureEvent, handler)
    engine = FeatureEngine(bus)
    await engine.start()

    # Separate bars: ticks are aggregated into fixed-interval OHLC bars (M14),
    # so a return between them only exists once they are in different bars.
    await bus.publish(MarketDataEvent(symbol="AAPL", price=100.0, volume=10.0, ts=_BASE))
    await bus.publish(
        MarketDataEvent(symbol="AAPL", price=101.0, volume=10.0, ts=_BASE + timedelta(seconds=60))
    )

    assert len(received) == 2
    assert received[-1].symbol == "AAPL"
    assert set(received[-1].features) == {"return_1d", "realized_vol", "atr", "trend_pct_above_sma"}
    # second bar vs first: return_1d should reflect the 100 -> 101 move
    assert received[-1].features["return_1d"] == pytest.approx(0.01)

    await engine.stop()


@pytest.mark.asyncio
async def test_ticks_within_one_interval_build_a_bar_with_real_range():
    """The M14 fix: several ticks in one interval produce one bar carrying the
    range traded, not one flat bar per tick."""
    bus = EventBus()
    engine = FeatureEngine(bus)
    await engine.start()

    for offset, price in ((0, 100.0), (10, 108.0), (20, 95.0), (30, 102.0)):
        await bus.publish(
            MarketDataEvent(
                symbol="AAPL", price=price, volume=10.0, ts=_BASE + timedelta(seconds=offset)
            )
        )

    bars = engine.bars.frame("AAPL")
    assert len(bars) == 1
    assert bars["high"].iloc[-1] == 108.0
    assert bars["low"].iloc[-1] == 95.0
    assert bars["close"].iloc[-1] == 102.0
    assert bars["volume"].iloc[-1] == 40.0

    await engine.stop()


@pytest.mark.asyncio
async def test_feature_engine_stop_unsubscribes():
    bus = EventBus()
    received: list[FeatureEvent] = []

    async def handler(event: FeatureEvent) -> None:
        received.append(event)

    bus.subscribe(FeatureEvent, handler)
    engine = FeatureEngine(bus)
    await engine.start()
    await engine.stop()

    await bus.publish(
        MarketDataEvent(symbol="AAPL", price=100.0, volume=10.0, ts=datetime.now(UTC))
    )

    assert received == []


@pytest.mark.asyncio
async def test_feature_engine_caps_history_length():
    bus = EventBus()
    engine = FeatureEngine(bus, max_history=3)
    await engine.start()

    for i in range(10):
        await bus.publish(
            MarketDataEvent(
                symbol="AAPL",
                price=100.0 + i,
                volume=10.0,
                ts=_BASE + timedelta(seconds=i * 60),
            )
        )

    # max_history caps *completed* bars; the forming bar is additional, since
    # it has not been committed to history yet.
    assert len(engine.bars.for_symbol("AAPL").completed_bars()) == 3
    await engine.stop()
