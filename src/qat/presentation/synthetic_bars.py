"""Synthetic daily bar generation shared by the Strategy Workbench and
Screener (spec §G/M10): reuses SyntheticMarketDataSource's per-symbol random
walk with re-labelled daily timestamps, since no historical data vendor is
wired into this app - matches the mock-everywhere stance used throughout.

A per-symbol seed is derived from the symbol string itself (not Python's
hash(), which is randomised per-process) so results are reproducible run to
run - moved here from workbench.py (M9) unchanged so Screener can reuse the
same bars without duplicating the logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from qat.data.market_data import SyntheticMarketDataSource

_DEFAULT_N_BARS = 300


def seed_for_symbol(symbol: str) -> int:
    return sum(ord(char) for char in symbol) + 1


async def generate_daily_bars(symbol: str, n_bars: int = _DEFAULT_N_BARS) -> pd.DataFrame:
    source = SyntheticMarketDataSource(seed=seed_for_symbol(symbol), interval_seconds=0.0)
    start = datetime.now(UTC) - timedelta(days=n_bars)
    rows: list[dict[str, object]] = []
    async for tick in source.stream_ticks([symbol]):
        ts = start + timedelta(days=len(rows))
        rows.append(
            {
                "ts": ts,
                "open": tick.price,
                "high": tick.price,
                "low": tick.price,
                "close": tick.price,
                "volume": tick.volume,
            }
        )
        if len(rows) >= n_bars:
            break
    return pd.DataFrame(rows)
