"""Engine-level tests for the two spec-mandated assertions: Multi-Factor is
always active across every regime, and Mean Reversion is disabled outside
Sideways (engine-level gating) as well as internally during a strong trend
(covered separately in test_mean_reversion.py - defense in depth)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.data.fundamentals import MockFundamentalsSource
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, RegimeEvent, SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.engine import StrategyEngine
from qat.domain.strategies.mean_reversion import MeanReversionStrategy
from qat.domain.strategies.multi_factor import MultiFactorStrategy


async def _feed_ticks(bus: EventBus, symbol: str, prices: list[float]) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i, price in enumerate(prices):
        await bus.publish(
            MarketDataEvent(
                symbol=symbol, price=price, volume=1_000_000.0, ts=start + timedelta(days=i)
            )
        )


async def _multi_factor_fired_in(regime: Regime) -> bool:
    bus = EventBus()
    received: list[SignalEvent] = []

    async def handler(event: SignalEvent) -> None:
        received.append(event)

    bus.subscribe(SignalEvent, handler)
    engine = StrategyEngine(
        bus, [MultiFactorStrategy(top_quintile=1.0)], MockFundamentalsSource(seed=1)
    )
    await engine.start()
    await bus.publish(RegimeEvent(label=regime.value, probs={}, exposure_scalar=1.0))

    await _feed_ticks(bus, "AAA", [100.0, 101.0, 102.0])
    await _feed_ticks(bus, "BBB", [50.0, 49.0, 48.0])

    await engine.stop()
    return any(s.strategy == "multi_factor" for s in received)


@pytest.mark.asyncio
async def test_multi_factor_is_always_active_across_all_regimes():
    for regime in Regime:
        assert await _multi_factor_fired_in(regime), f"multi_factor produced no signals in {regime}"


@pytest.mark.asyncio
async def test_mean_reversion_disabled_outside_sideways_regime():
    bus = EventBus()
    received: list[SignalEvent] = []

    async def handler(event: SignalEvent) -> None:
        received.append(event)

    bus.subscribe(SignalEvent, handler)
    engine = StrategyEngine(
        bus, [MeanReversionStrategy(rsi_window=3)], MockFundamentalsSource(seed=1)
    )
    await engine.start()
    await bus.publish(RegimeEvent(label=Regime.BULL.value, probs={}, exposure_scalar=1.0))

    prices = [100.0] * 30 + [90.0, 80.0, 70.0]  # would trigger mean reversion in Sideways
    await _feed_ticks(bus, "AAA", prices)

    mean_reversion_signals = [s for s in received if s.strategy == "mean_reversion"]
    assert mean_reversion_signals == []

    await engine.stop()


@pytest.mark.asyncio
async def test_mean_reversion_active_in_sideways_regime_on_oversold_drop():
    bus = EventBus()
    received: list[SignalEvent] = []

    async def handler(event: SignalEvent) -> None:
        received.append(event)

    bus.subscribe(SignalEvent, handler)
    engine = StrategyEngine(
        bus, [MeanReversionStrategy(rsi_window=3)], MockFundamentalsSource(seed=1)
    )
    await engine.start()
    await bus.publish(RegimeEvent(label=Regime.SIDEWAYS.value, probs={}, exposure_scalar=1.0))

    prices = [100.0] * 30 + [90.0, 80.0, 70.0]
    await _feed_ticks(bus, "AAA", prices)

    mean_reversion_signals = [s for s in received if s.strategy == "mean_reversion"]
    assert len(mean_reversion_signals) > 0

    await engine.stop()


@pytest.mark.asyncio
async def test_default_regime_is_sideways_before_any_regime_event():
    bus = EventBus()
    received: list[SignalEvent] = []

    async def handler(event: SignalEvent) -> None:
        received.append(event)

    bus.subscribe(SignalEvent, handler)
    engine = StrategyEngine(
        bus, [MeanReversionStrategy(rsi_window=3)], MockFundamentalsSource(seed=1)
    )
    await engine.start()
    # no RegimeEvent published - engine should default to Sideways

    prices = [100.0] * 30 + [90.0, 80.0, 70.0]
    await _feed_ticks(bus, "AAA", prices)

    mean_reversion_signals = [s for s in received if s.strategy == "mean_reversion"]
    assert len(mean_reversion_signals) > 0

    await engine.stop()
