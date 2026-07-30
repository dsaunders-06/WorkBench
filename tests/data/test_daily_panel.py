"""Fetching daily bars for many symbols at once, for the warm start (M27a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.data.history import SyntheticHistorySource, fetch_daily_panel


def _frame(n: int = 5) -> pd.DataFrame:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "ts": start + timedelta(days=i),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1_000.0,
            }
            for i in range(n)
        ]
    )


class _BulkSource:
    def __init__(self, available: set[str]) -> None:
        self.available = available
        self.bulk_calls = 0
        self.single_calls = 0

    async def get_daily_bars_many(self, symbols, n_bars=300):
        self.bulk_calls += 1
        return {symbol: _frame() for symbol in symbols if symbol in self.available}

    async def get_daily_bars(self, symbol, n_bars=300):
        self.single_calls += 1
        return _frame()


class _DegradingSource:
    """Both real sources answer a failed fetch with a seeded random walk and
    report it only through this flag."""

    def __init__(self, synthetic_for: set[str]) -> None:
        self.synthetic_for = synthetic_for
        self.last_was_synthetic = False

    async def get_daily_bars(self, symbol, n_bars=300):
        self.last_was_synthetic = symbol in self.synthetic_for
        return _frame()


@pytest.mark.asyncio
async def test_a_bulk_source_is_asked_once_for_everything():
    """Measured on the live account: 1.3s per symbol against 3.2s for all 101,
    so a per-symbol warm start would block startup for over two minutes."""
    source = _BulkSource(available={"SPY", "AAPL", "MSFT"})

    panel = await fetch_daily_panel(source, ["SPY", "AAPL", "MSFT"])

    assert source.bulk_calls == 1
    assert source.single_calls == 0
    assert set(panel.frames) == {"SPY", "AAPL", "MSFT"}
    assert panel.unavailable == ()


@pytest.mark.asyncio
async def test_symbols_the_vendor_did_not_return_are_reported_not_filled():
    source = _BulkSource(available={"SPY"})

    panel = await fetch_daily_panel(source, ["SPY", "DELISTED"])

    assert set(panel.frames) == {"SPY"}
    assert panel.unavailable == ("DELISTED",)


@pytest.mark.asyncio
async def test_synthetic_fallback_bars_are_never_returned_for_seeding():
    """A screen showing clearly-labelled synthetic data is a reasonable
    degradation. A buffer that positions are sized from is not."""
    source = _DegradingSource(synthetic_for={"BRK.B"})

    panel = await fetch_daily_panel(source, ["SPY", "BRK.B", "AAPL"])

    assert set(panel.frames) == {"SPY", "AAPL"}
    assert panel.unavailable == ("BRK.B",)


@pytest.mark.asyncio
async def test_the_synthetic_source_still_seeds_the_demo():
    """Synthetic history is the intended data when the whole app is synthetic -
    the flag only marks a real source that degraded."""
    panel = await fetch_daily_panel(SyntheticHistorySource(), ["SPY", "AAPL"], n_bars=30)

    assert set(panel.frames) == {"SPY", "AAPL"}
    assert len(panel.frames["SPY"]) == 30
