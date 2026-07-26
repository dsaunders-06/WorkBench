"""Shared builders for strategy tests. Not collected by pytest (no test_
prefix)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from qat.data.features import FeatureBuilder
from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.strategies.base import FeatureSnapshot, SymbolContext

_DEFAULT_FUNDAMENTALS: dict[str, object] = {
    "sector": "Technology",
    "eps_growth_yoy": 0.05,
    "eps_growth_accelerating": False,
    "peg_ratio": 2.0,
    "roe": 0.10,
    "roic": 0.08,
    "debt_to_equity": 0.5,
    "book_to_market": 0.5,
    "earnings_yield": 0.05,
    "ev_to_ebit": 15.0,
    "fcf_yield": 0.03,
    "dividend_yield": 0.01,
    "dividend_growth_streak_years": 3,
    "payout_ratio": 0.4,
    "institutional_ownership_pct": 0.5,
    "relative_strength_rank": 50.0,
}


def make_fundamentals(symbol: str = "AAA", **overrides: object) -> FundamentalSnapshot:
    kwargs = dict(_DEFAULT_FUNDAMENTALS)
    kwargs.update(overrides)
    return FundamentalSnapshot(symbol=symbol, **kwargs)  # type: ignore[arg-type]


def make_bars(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    start: datetime = datetime(2022, 1, 1),
) -> pd.DataFrame:
    n = len(closes)
    ts = [start + timedelta(days=i) for i in range(n)]
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    volumes = volumes or [1_000_000.0] * n
    return pd.DataFrame(
        {"ts": ts, "open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes}
    )


def make_context(
    symbol: str,
    closes: list[float],
    fundamentals: FundamentalSnapshot | None = None,
    **bar_kwargs: object,
) -> SymbolContext:
    bars = make_bars(closes, **bar_kwargs)  # type: ignore[arg-type]
    technical = FeatureBuilder().build(bars)
    return SymbolContext(
        symbol=symbol,
        bars=bars,
        technical=technical,
        fundamentals=fundamentals or make_fundamentals(symbol),
    )


def make_snapshot(
    symbol: str,
    universe: dict[str, SymbolContext],
    as_of: datetime | None = None,
    positions: dict[str, float] | None = None,
) -> FeatureSnapshot:
    context = universe[symbol]
    as_of = as_of or context.bars["ts"].iloc[-1]
    return FeatureSnapshot(
        symbol=symbol,
        as_of=as_of,
        context=context,
        universe=universe,
        positions=positions or {},
    )
