"""Gating on probability mass rather than the argmax label (M27b).

On 30 July the regime engine published `high_vol=0.31, bull=0.29,
recovery=0.20`. Swing is eligible under bull and recovery and excluded under
high_vol, so 0.49 of the distribution sat where it could trade against 0.31
where it could not - and a 0.02 gap between the top two labels decided that it
did not trade at all, for the whole session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from qat.data.fundamentals import MockFundamentalsSource
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, RegimeEvent, SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.engine import StrategyEngine
from qat.domain.strategies.swing import SwingStrategy
from qat.domain.strategies.trend_following import TrendFollowingStrategy

# The distribution as published, filled out across all seven regimes.
_30_JULY = {
    "high_vol": 0.31,
    "bull": 0.29,
    "recovery": 0.20,
    "sideways": 0.08,
    "low_vol": 0.06,
    "bear": 0.05,
    "recession": 0.01,
}


def _engine(mass: float = 0.5, strategies=None) -> StrategyEngine:
    return StrategyEngine(
        EventBus(),
        strategies if strategies is not None else [SwingStrategy()],
        MockFundamentalsSource(seed=1),
        regime_eligibility_mass=mass,
    )


async def _publish(engine: StrategyEngine, probs: dict[str, float], label: str) -> None:
    await engine._on_regime(
        RegimeEvent(label=label, probs=probs, exposure_scalar=1.0, ts=datetime.now(UTC))
    )


async def _feed_a_bar(engine: StrategyEngine, symbol: str = "AAA", held: float = 0.0) -> None:
    """Enough ticks to get past the warm-up and reach the dispatch loop."""
    if held:
        engine._current_positions = lambda: _positions({symbol: held})  # type: ignore[method-assign]
    start = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
    for n in range(60):
        await engine._on_market_data(
            MarketDataEvent(
                symbol=symbol,
                price=100.0 + n * 0.1,
                volume=1_000.0,
                ts=start + timedelta(minutes=n),
            )
        )


async def _positions(holdings: dict[str, float]) -> dict[str, float]:
    return holdings


class _AlwaysSignals:
    """Emits whichever side it is told to, so the gate can be tested without
    also depending on whether a real setup happens to be present."""

    def __init__(self, side: str) -> None:
        self.name = f"always-{side}"
        self.side = side
        self.asked = 0

    def suitable_regimes(self):
        return {Regime.SIDEWAYS}  # a minority of _30_JULY, so ineligible

    def params(self):
        return {}

    def on_features(self, snapshot):
        self.asked += 1
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side=self.side,
                conviction=1.0,
                strategy=self.name,
                meta={},
                ts=snapshot.as_of,
            )
        ]


@pytest.mark.asyncio
async def test_an_ineligible_strategy_is_still_asked_to_exit_what_it_holds():
    """M56c. The gate sat above on_features, and on_features is the only route
    to an exit signal - so an ineligible strategy was not asked to sell, it was
    not asked anything.

    That is why 29 entries produced zero signal exits in 1.19 years. Swing's
    exit condition IS a broken trend, and broken trends are what the excluded
    regimes are, so the strategy was reliably switched off exactly when it had
    something to say about a position it was still holding.
    """
    seller = _AlwaysSignals("sell")
    engine = _engine(strategies=[seller])
    await _publish(engine, _30_JULY, "high_vol")
    assert engine.is_eligible(seller) is False

    published: list[SignalEvent] = []

    async def collect(event: SignalEvent) -> None:
        published.append(event)

    engine.bus.subscribe(SignalEvent, collect)

    await _feed_a_bar(engine, held=100.0)

    assert seller.asked > 0, "an ineligible strategy must still be asked about its holdings"
    assert published, "and its exit must actually reach the bus"
    assert {s.side for s in published} == {"sell"}


@pytest.mark.asyncio
async def test_an_ineligible_strategy_cannot_sell_what_is_not_held():
    """The narrowing that matters. Mean reversion emits a sell on overbought
    RSI whether or not anything is held, so permitting sells outright would let
    an excluded strategy OPEN short exposure - the opposite of the gate's
    purpose."""
    seller = _AlwaysSignals("sell")
    engine = _engine(strategies=[seller])
    await _publish(engine, _30_JULY, "high_vol")

    published: list[SignalEvent] = []

    async def collect(event: SignalEvent) -> None:
        published.append(event)

    engine.bus.subscribe(SignalEvent, collect)

    await _feed_a_bar(engine, held=0.0)

    assert published == [], "nothing is held, so this sell would open a position"


@pytest.mark.asyncio
async def test_an_ineligible_strategy_still_cannot_open_anything():
    """The other half, and the half that must not regress: the gate exists to
    stop entries in regimes a strategy was not built for."""
    buyer = _AlwaysSignals("buy")
    engine = _engine(strategies=[buyer])
    await _publish(engine, _30_JULY, "high_vol")
    assert engine.is_eligible(buyer) is False

    published: list[SignalEvent] = []

    async def collect(event: SignalEvent) -> None:
        published.append(event)

    engine.bus.subscribe(SignalEvent, collect)

    await _feed_a_bar(engine)

    assert published == [], "an ineligible strategy must not be able to buy"


@pytest.mark.asyncio
async def test_the_thirtieth_of_july_would_have_traded():
    """The whole reason for the change. The argmax said high_vol and swing sat
    out; the distribution says 63% of the mass was in regimes it trades."""
    engine = _engine()
    swing = engine.strategies[0]

    await _publish(engine, _30_JULY, "high_vol")

    assert engine._eligible_mass(swing) == pytest.approx(0.63)
    assert engine.is_eligible(swing) is True


@pytest.mark.asyncio
async def test_a_strategy_whose_regimes_hold_a_minority_still_sits_out():
    """The gate still gates - this is not a way of switching it off."""
    engine = _engine(strategies=[TrendFollowingStrategy()])
    trend = engine.strategies[0]  # bear, high_vol, recession

    await _publish(engine, _30_JULY, "high_vol")

    assert engine._eligible_mass(trend) == pytest.approx(0.37)
    assert engine.is_eligible(trend) is False


@pytest.mark.asyncio
async def test_a_confident_hostile_regime_blocks_even_a_broad_strategy():
    engine = _engine()
    swing = engine.strategies[0]

    await _publish(engine, {"bear": 0.9, "high_vol": 0.1}, "bear")

    assert engine.is_eligible(swing) is False


@pytest.mark.asyncio
async def test_an_uninformative_classifier_lets_breadth_decide():
    """Seven regimes, flat. A four-regime strategy sits at 0.57 and trades; a
    three-regime one at 0.43 and does not. When the model knows nothing, the
    breadth of the mandate decides rather than an arbitrary argmax."""
    flat = dict.fromkeys((r.value for r in Regime), 1 / 7)
    engine = _engine(strategies=[SwingStrategy(), TrendFollowingStrategy()])
    swing, trend = engine.strategies

    await _publish(engine, flat, "sideways")

    assert engine.is_eligible(swing) is True
    assert engine.is_eligible(trend) is False


@pytest.mark.asyncio
async def test_without_a_regime_event_it_falls_back_to_the_default_label():
    """There is no distribution to read before the engine has classified
    anything, so the old membership test still applies - and SIDEWAYS is inside
    swing's set, which is the documented fail-open."""
    engine = _engine()
    swing = engine.strategies[0]

    assert engine._eligible_mass(swing) is None
    assert engine.is_eligible(swing) is True


@pytest.mark.asyncio
async def test_the_threshold_is_configurable_and_binding():
    engine = _engine(mass=0.7)
    swing = engine.strategies[0]

    await _publish(engine, _30_JULY, "high_vol")

    assert engine._eligible_mass(swing) == pytest.approx(0.63)
    assert engine.is_eligible(swing) is False, "0.63 is below a 0.70 bar"


@pytest.mark.asyncio
async def test_a_change_in_eligibility_is_logged_with_the_numbers(caplog):
    """A strategy silently ineligible for a session looks exactly like one that
    found no setup. That ambiguity cost four sessions."""
    engine = _engine()

    await _publish(engine, _30_JULY, "high_vol")  # eligible
    with caplog.at_level(logging.INFO, logger="qat.domain.strategies.engine"):
        await _publish(engine, {"bear": 0.95, "bull": 0.05}, "bear")  # now not

    assert "swing is now SKIPPED" in caplog.text
    assert "5%" in caplog.text  # the mass that remained
