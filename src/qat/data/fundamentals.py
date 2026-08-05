"""Company fundamentals for the fundamentals-driven strategies (CAN SLIM,
Growth, Value, GARP, Quality, Dividend Growth - spec §F, paper §4/§8).

Every numeric field is optional (M18). A real vendor cannot always answer:
an index ETF has no return on equity or EPS growth, and some listings have no
published PEG. Before M18 the mock invented all sixteen figures for every
symbol, so the value, quality and GARP strategies were ranking SPY on a
fabricated ROE and could not tell you they were doing it.

None means "not available", and it is the strategies' job to abstain rather
than guess - see missing(). A neutral substitute would be worse than the gap:
a real company silently out-ranked by a placeholder is indistinguishable from
one out-ranked on merit.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, fields
from typing import Protocol

from qat.data import sectors

# Re-exported from data.sectors so callers (the Screener's sector filter) have
# a single source of truth, and so the values match what sector_for() actually
# returns rather than a parallel hand-written list that can drift from it.
SECTORS = (*sectors.SECTORS, sectors.UNKNOWN_SECTOR)


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    symbol: str
    # Always present: taken from the curated map, which answers for every
    # symbol (UNKNOWN_SECTOR when it does not know) rather than guessing.
    sector: str
    eps_growth_yoy: float | None
    eps_growth_accelerating: bool | None
    peg_ratio: float | None
    roe: float | None
    roic: float | None
    debt_to_equity: float | None
    book_to_market: float | None
    earnings_yield: float | None
    ev_to_ebit: float | None
    fcf_yield: float | None
    dividend_yield: float | None
    dividend_growth_streak_years: int | None
    payout_ratio: float | None
    institutional_ownership_pct: float | None
    relative_strength_rank: float | None  # 0-100 percentile
    # True only for figures a source invented. Carried on the snapshot rather
    # than inferred from the source's type, so anything downstream that
    # displays or reasons about a number can say where it came from.
    is_synthetic: bool = False

    def missing(self, *names: str) -> tuple[str, ...]:
        """Which of the named fields this snapshot cannot answer.

        The single place strategies ask "can I evaluate this symbol?". Returns
        names rather than a bool so the abstention can say what was missing -
        "no signal" with no reason is indistinguishable from a bug.
        """
        return tuple(name for name in names if getattr(self, name) is None)

    def available_fields(self) -> tuple[str, ...]:
        return tuple(
            field.name
            for field in fields(self)
            if field.name not in ("symbol", "sector", "is_synthetic")
            and getattr(self, field.name) is not None
        )

    def available_figures(self) -> dict[str, object]:
        """The figures this snapshot can actually answer, as a plain dict (M40).

        Absent fields are OMITTED rather than rendered as null. A reader given
        `"roe": null` has to know that means "the vendor does not publish it"
        and not "it is zero"; a reader given nothing at all cannot make that
        mistake. It is the same reasoning `missing()` exists for, applied to a
        consumer that is a language model rather than a strategy.

        `sector` is always present by construction, and `is_synthetic` rides
        along because a figure's provenance matters at least as much as its
        value to anything reasoning about it.
        """
        figures: dict[str, object] = {"sector": self.sector, "is_synthetic": self.is_synthetic}
        figures.update({name: getattr(self, name) for name in self.available_fields()})
        return figures


class FundamentalsSource(Protocol):
    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot: ...


class MockFundamentalsSource:
    """Deterministic per-symbol synthetic fundamentals: same (seed, symbol)
    always yields the same snapshot, independent of call order.

    Deliberately still answers every field, so the offline default and the
    existing tests behave exactly as before. What changed at M18 is that it
    says so: is_synthetic=True on every snapshot it produces.
    """

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
            is_synthetic=True,
        )
