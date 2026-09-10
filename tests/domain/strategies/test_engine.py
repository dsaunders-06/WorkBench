"""Engine-level tests for the two spec-mandated assertions: Multi-Factor is
always active across every regime, and Mean Reversion is disabled outside
Sideways (engine-level gating) as well as internally during a strong trend
(covered separately in test_mean_reversion.py - defense in depth)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
async def test_NO_ENTRY_SIGNAL_before_any_regime_event():
    """⚠️ REVERSED 10 September 2026 - this asserted `len(...) > 0`.

    It pinned the fail-open: with no RegimeEvent the engine defaulted to
    SIDEWAYS and mean reversion, which is a sideways strategy, was free to open
    positions. Twenty minutes every open, on no reading of the market.

    Reversed because a blind entry commits the book for at least the minimum
    hold - `QAT_MIN_HOLDING_TRADING_DAYS=10`, against a 30-day time stop - sized
    under a label nobody read, while a twenty-minute wait costs a signal that is
    still there at 10:21.

    ⚠️ An earlier version of this docstring justified the reversal on a "60-day
    hold". **That is an aspiration and NOT a parameter** - the operator ruled it
    out of decision-making the same day. The 10/30-day rails are what govern and
    the argument stands on them. **Exits are unaffected** - see
    `test_an_exit_still_flows_while_the_regime_is_unread`.
    """
    bus = EventBus()
    received: list[SignalEvent] = []

    async def handler(event: SignalEvent) -> None:
        received.append(event)

    bus.subscribe(SignalEvent, handler)
    engine = StrategyEngine(
        bus, [MeanReversionStrategy(rsi_window=3)], MockFundamentalsSource(seed=1)
    )
    await engine.start()
    # no RegimeEvent published - nothing has read the market, so nothing enters

    prices = [100.0] * 30 + [90.0, 80.0, 70.0]
    await _feed_ticks(bus, "AAA", prices)

    mean_reversion_signals = [s for s in received if s.strategy == "mean_reversion"]
    assert mean_reversion_signals == [], "an entry was taken on an unread market"

    await engine.stop()


# --- The blind window at the open (10 September 2026) -------------------------


def _engine_with_no_regime(bus) -> StrategyEngine:
    return StrategyEngine(
        bus, [MultiFactorStrategy(top_quintile=1.0)], MockFundamentalsSource(seed=1)
    )


@pytest.mark.asyncio
async def test_no_strategy_is_eligible_before_a_regime_is_published():
    """⚠️ MEASURED 10 September 2026. From session activation at 10:00:05 until
    the first classification at 10:20:33 - twenty minutes, EVERY open - gating
    ran on a hardcoded `sideways` DEFAULT:

        Gating 1 strategies on the sideways DEFAULT - the regime engine has
        published nothing. Strategies are being permitted or refused without
        any reading of the market

    It was harmless that day only because the same vendor delay that opens the
    window also starved it of prices, so there were no signals to gate. **Two
    causes, one event - harmless by coincidence rather than by design**, which
    is item 33's finding about the seven-minute margin nobody enforces.

    `multi_factor` is the sharpest case: it is eligible in EVERY regime, so
    under the default it was permitted unconditionally.
    """
    engine = _engine_with_no_regime(EventBus())

    assert not any(engine.is_eligible(s) for s in engine.strategies)


@pytest.mark.asyncio
async def test_eligibility_returns_once_a_regime_arrives():
    """⚠️ THE CONTROL. A refusal that never lifts is not conservatism, it is an
    outage - and it would pass the test above on its own."""
    bus = EventBus()
    engine = _engine_with_no_regime(bus)
    await engine.start()

    await bus.publish(RegimeEvent(label=Regime.BULL.value, probs={}, exposure_scalar=1.0))
    try:
        assert any(engine.is_eligible(s) for s in engine.strategies)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_an_exit_still_flows_while_the_regime_is_unread():
    """⚠️ M56c IS NOT BEING UNDONE. Eligibility gates ENTRIES, never exits.

    A blind window that also blocked exits would be the 9 September deadlock in
    a new place: a halt that prevents de-risking is not a conservative halt.
    """
    bus = EventBus()
    engine = _engine_with_no_regime(bus)

    held = SimpleNamespace(held_quantity=lambda symbol: 100.0)
    sell = SignalEvent(symbol="AAA", side="sell", strategy="multi_factor", conviction=1.0)

    assert engine._closes_an_open_position(sell, held)
