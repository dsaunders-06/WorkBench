"""Company fundamentals for the fundamentals-driven strategies (CAN SLIM,
Growth, Value, GARP, Quality, Dividend Growth - spec §F, paper §4/§8).

No real fundamentals vendor is named in the spec (unlike FRED for macro,
IBKR for market data), so this is interface + deterministic mock only,
matching the pattern used for every other external dependency in this
codebase. A real vendor integration is a future addition, not required here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from qat.data import sectors

# Re-exported from data.sectors so callers (the Screener's sector filter) have
# a single source of truth, and so the values match what sector_for() actually
# returns rather than a parallel hand-written list that can drift from it.
SECTORS = (*sectors.SECTORS, sectors.UNKNOWN_SECTOR)


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    symbol: str
    sector: str
    eps_growth_yoy: float
    eps_growth_accelerating: bool
    peg_ratio: float
    roe: float
    roic: float
    debt_to_equity: float
    book_to_market: float
    earnings_yield: float
    ev_to_ebit: float
    fcf_yield: float
    dividend_yield: float
    dividend_growth_streak_years: int
    payout_ratio: float
    institutional_ownership_pct: float
    relative_strength_rank: float  # 0-100 percentile


class FundamentalsSource(Protocol):
    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot: ...


class MockFundamentalsSource:
    """Deterministic per-symbol synthetic fundamentals: same (seed, symbol)
    always yields the same snapshot, independent of call order."""

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed
        self._cache: dict[str, FundamentalSnapshot] = {}

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        cached = self._cache.get(symbol)
        if cached is None:
            cached = self._generate(symbol)
            self._cache[symbol] = cached
        return cached

    def _generate(self, symbol: str) -> FundamentalSnapshot:
        rng = random.Random(f"{self._seed}:{symbol}")  # nosec B311 - deterministic, not crypto
        return FundamentalSnapshot(
            symbol=symbol,
            # A real classification where one exists (spec M12) - the synthetic
            # figures below are still made up, but the sector no longer is.
            sector=sectors.sector_for(symbol),
            eps_growth_yoy=round(rng.uniform(-0.10, 0.40), 4),
            eps_growth_accelerating=rng.random() > 0.5,
            peg_ratio=round(rng.uniform(0.3, 4.0), 2),
            roe=round(rng.uniform(0.02, 0.35), 4),
            roic=round(rng.uniform(0.02, 0.30), 4),
            debt_to_equity=round(rng.uniform(0.0, 2.5), 2),
            book_to_market=round(rng.uniform(0.1, 1.5), 3),
            earnings_yield=round(rng.uniform(0.01, 0.12), 4),
            ev_to_ebit=round(rng.uniform(5.0, 30.0), 2),
            fcf_yield=round(rng.uniform(-0.02, 0.10), 4),
            dividend_yield=round(rng.uniform(0.0, 0.06), 4),
            dividend_growth_streak_years=rng.randint(0, 30),
            payout_ratio=round(rng.uniform(0.0, 1.1), 3),
            institutional_ownership_pct=round(rng.uniform(0.1, 0.9), 3),
            relative_strength_rank=round(rng.uniform(0, 100), 1),
        )
