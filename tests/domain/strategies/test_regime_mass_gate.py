"""Gating on probability mass rather than the argmax label (M27b).

On 30 July the regime engine published `high_vol=0.31, bull=0.29,
recovery=0.20`. Swing is eligible under bull and recovery and excluded under
high_vol, so 0.49 of the distribution sat where it could trade against 0.31
where it could not - and a 0.02 gap between the top two labels decided that it
did not trade at all, for the whole session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from qat.data.fundamentals import MockFundamentalsSource
from qat.domain.bus import EventBus
from qat.domain.events import RegimeEvent
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
