"""Several symbols, one book, and the governor live (W2 step 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _bars_with_pullback_at(dip_index: int, days: int = 200) -> pd.DataFrame:
    """The dip depth is computed, not tuned - an EMA20 lags a +0.5/day trend by
    about (20-1)/2 * 0.5 = 4.75, so 10 clears it. See the step-2 fixture for
    the derivation and for the shallower version that never fired."""
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[dip_index] -= 10.0
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
async def test_several_symbols_share_one_book(tmp_path):
    """Each symbol pulls back on a different day, so entries arrive spread out
    rather than all at once - which is what a portfolio actually looks like."""
    bars = {
        "AAA": _bars_with_pullback_at(120),
        "BBB": _bars_with_pullback_at(140),
        "CCC": _bars_with_pullback_at(160),
    }
    session = ReplaySession(bars=bars, strategies=[SwingStrategy()], settings=_settings(tmp_path))

    await session.run()

    held = {p.symbol for p in await session.broker.positions()}
    orders = {o.symbol for o in session.broker._orders.values()}
    assert orders, "the production path produced no order across three symbols"
    assert held <= {"AAA", "BBB", "CCC"}
