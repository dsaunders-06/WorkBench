"""Relative strength percentile (spec M18).

The rank only means what its name implies if the universe behind it is big
enough, so the size floor is as much the subject here as the arithmetic.
"""

from __future__ import annotations

import pandas as pd

from qat.data.relative_strength import UniverseRelativeStrength


class FakeHistory:
    """Daily closes per symbol; a symbol absent from the map has no history."""

    def __init__(self, closes: dict[str, list[float]]) -> None:
        self.closes = closes

    async def get_daily_bars(self, symbol: str, n_bars: int = 300) -> pd.DataFrame:
        series = self.closes.get(symbol)
        if series is None:
            raise KeyError(symbol)
        return pd.DataFrame({"close": series})


def _rising(start: float, pct: float, n: int = 130) -> list[float]:
    """A straight line from `start` to `start * (1 + pct)`."""
    return [start * (1.0 + pct * i / (n - 1)) for i in range(n)]


def _universe(returns: dict[str, float]) -> tuple[FakeHistory, tuple[str, ...]]:
    closes = {symbol: _rising(100.0, pct) for symbol, pct in returns.items()}
    return FakeHistory(closes), tuple(returns)


async def test_the_strongest_performer_ranks_100_and_the_weakest_0():
    returns = {f"S{i}": i / 100.0 for i in range(10)}  # S0 flat ... S9 +9%
    history, universe = _universe(returns)
    ranker = UniverseRelativeStrength(history, universe, min_universe_size=10)

    assert await ranker.rank_for("S9") == 100.0
    assert await ranker.rank_for("S0") == 0.0


async def test_the_middle_of_the_pack_ranks_near_fifty():
    returns = {f"S{i}": i / 100.0 for i in range(11)}
    history, universe = _universe(returns)
    ranker = UniverseRelativeStrength(history, universe, min_universe_size=10)

    assert await ranker.rank_for("S5") == 50.0


async def test_ties_share_a_rank_rather_than_being_ordered_by_luck():
    returns = {f"S{i}": 0.05 for i in range(10)}
    history, universe = _universe(returns)
    ranker = UniverseRelativeStrength(history, universe, min_universe_size=10)

    ranks = {symbol: await ranker.rank_for(symbol) for symbol in universe}

    assert set(ranks.values()) == {50.0}


async def test_a_universe_below_the_floor_yields_no_rank_at_all():
    """A confident-looking 100.0 that means "best of three" is worse than
    admitting the number is not available."""
    history, universe = _universe({"A": 0.1, "B": 0.2, "C": 0.3})
    ranker = UniverseRelativeStrength(history, universe, min_universe_size=10)

    assert await ranker.rank_for("C") is None


async def test_a_symbol_with_no_history_does_not_void_the_whole_universe():
    returns = {f"S{i}": i / 100.0 for i in range(10)}
    history, universe = _universe(returns)
    ranker = UniverseRelativeStrength(history, (*universe, "BROKEN"), min_universe_size=10)

    assert await ranker.rank_for("S9") == 100.0
    assert await ranker.rank_for("BROKEN") is None


async def test_ranks_are_computed_once_for_the_whole_universe():
    """Per-symbol computation would re-read every symbol's history N times to
    produce N answers that have to agree anyway."""

    class CountingHistory(FakeHistory):
        def __init__(self, closes):
            super().__init__(closes)
            self.reads = 0

        async def get_daily_bars(self, symbol: str, n_bars: int = 300) -> pd.DataFrame:
            self.reads += 1
            return await super().get_daily_bars(symbol, n_bars)

    returns = {f"S{i}": i / 100.0 for i in range(10)}
    history = CountingHistory({s: _rising(100.0, p) for s, p in returns.items()})
    ranker = UniverseRelativeStrength(history, tuple(returns), min_universe_size=10)

    for symbol in returns:
        await ranker.rank_for(symbol)

    assert history.reads == len(returns)


async def test_a_flat_series_is_ranked_not_discarded():
    returns = {f"S{i}": (0.0 if i == 0 else i / 100.0) for i in range(10)}
    history, universe = _universe(returns)
    ranker = UniverseRelativeStrength(history, universe, min_universe_size=10)

    assert await ranker.rank_for("S0") == 0.0
