"""Bars reach the strategy, and orders reach the broker (W2 step 2).

One symbol, no rails, no regime. A session loop that works for one symbol and
lies about ten is worse than one that only claims one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _trending_bars(days: int = 160) -> pd.DataFrame:
    """An uptrend containing exactly one pullback-and-reclaim.

    The dip depth is COMPUTED, not tuned. Swing needs `prior_close <=
    prior_fast` then `last_close > last_fast`, and an EMA20 lags a +0.5/day
    trend by about (20-1)/2 * 0.5 = 4.75 - so a shallower dip never reaches the
    average and the thesis cannot fire however long the series runs. A first
    version of this fixture dipped 5 and left the close at 173.50 against a
    fast EMA of 173.27, still above it, and the strategy was right to be
    silent. Ten clears the lag without inventing a crash.

    Placed ten bars from the end so there is room for the entry to fill and the
    position to live, rather than resting on the final bar.
    """
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[days - 10] -= 10.0
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


@pytest.mark.asyncio
async def test_the_strategy_sees_true_daily_bars_not_flattened_ones(tmp_path):
    """If a tick flattened the bar, high == low == close and ATR collapses -
    which would silently break every stop distance in the system."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
    )

    await session.run()

    frame = session.engine.bars.frame("AAA")
    assert not frame.empty
    assert (frame["high"] > frame["low"]).all(), "a flattened bar means ATR is zero"


@pytest.mark.asyncio
async def test_the_session_advances_the_broker_to_the_end_of_the_series(tmp_path):
    bars = _trending_bars()
    session = ReplaySession(
        bars={"AAA": bars},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
    )

    await session.run()

    assert session.broker.current_date == bars.index[-1]


@pytest.mark.asyncio
async def test_a_signal_becomes_an_order_at_the_broker(tmp_path):
    """The claim the harness rests on: the production path, driven by history,
    produces an order without a single rule being re-implemented."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
    )

    await session.run()

    submitted = list(session.broker._orders.values())
    assert submitted, "the production path produced no order at all"
    assert all(o.symbol == "AAA" for o in submitted)


@pytest.mark.asyncio
async def test_the_buffers_are_warm_before_the_first_replayed_day(tmp_path):
    """Without a warm start the first ~50 days are blind, so the front of every
    measured window is systematically quiet - an artefact of the instrument
    rather than anything the market did."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=60,
    )

    assert len(session.engine.bars.frame("AAA")) >= 60, "seeded before day one"
    assert len(session.bridge.bars.frame("AAA")) >= 60
