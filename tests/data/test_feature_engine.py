from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.data.feature_engine import FeatureEngine
from qat.domain.bus import EventBus
from qat.domain.events import FeatureEvent, MarketDataEvent


@pytest.mark.asyncio
async def test_feature_engine_publishes_feature_event_per_tick():
    bus = EventBus()
    received: list[FeatureEvent] = []

    async def handler(event: FeatureEvent) -> None:
        received.append(event)

    bus.subscribe(FeatureEvent, handler)
    engine = FeatureEngine(bus)
    await engine.start()

    await bus.publish(
        MarketDataEvent(symbol="AAPL", price=100.0, volume=10.0, ts=datetime.now(UTC))
    )
    await bus.publish(
        MarketDataEvent(symbol="AAPL", price=101.0, volume=10.0, ts=datetime.now(UTC))
    )

    assert len(received) == 2
    assert received[-1].symbol == "AAPL"
    assert set(received[-1].features) == {"return_1d", "realized_vol", "atr", "trend_pct_above_sma"}
    # second tick vs first: return_1d should reflect the 100 -> 101 move
    assert received[-1].features["return_1d"] == pytest.approx(0.01)

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
            MarketDataEvent(symbol="AAPL", price=100.0 + i, volume=10.0, ts=datetime.now(UTC))
        )

    assert len(engine._history["AAPL"]) == 3
    await engine.stop()
