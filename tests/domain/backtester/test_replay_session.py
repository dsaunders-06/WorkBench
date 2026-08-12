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
    """A clean uptrend with a late pullback, so swing's thesis can fire."""
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[-3] -= 5.0  # the pullback below the fast EMA
    closes[-2] -= 4.0
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
