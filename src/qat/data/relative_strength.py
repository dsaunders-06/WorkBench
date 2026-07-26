"""Relative strength rank: a symbol's trailing return as a percentile of its
universe (spec M18).

CAN SLIM's "L" gates on this, and it is the one field on FundamentalSnapshot
that no fundamentals vendor supplies - it is not a property of the company at
all, but of the company measured against everything else you might have bought
instead. Before M18 it was a seeded random number, which made the gate
meaningless.

The rank is only as honest as the universe it is measured against. Ranking
against three symbols would produce a confident-looking 100.0 that means
"best of three", so below a minimum universe size this returns None and CAN
SLIM abstains rather than acting on a number that does not carry the meaning
its name implies.
"""

from __future__ import annotations

import logging
from typing import Protocol

from qat.data.history import DEFAULT_BARS, HistoricalBarSource

logger = logging.getLogger(__name__)

# Roughly six months of trading days - the window CAN SLIM's relative-strength
# screen is conventionally run over.
DEFAULT_LOOKBACK_BARS = 126

# Fewer than this and a percentile is arithmetic rather than information.
MIN_UNIVERSE_SIZE = 10


class RelativeStrengthSource(Protocol):
    async def rank_for(self, symbol: str) -> float | None: ...


class UniverseRelativeStrength:
    """Percentile rank of trailing return across a fixed universe.

    Ranks are computed once for the whole universe and cached, not per symbol
    on demand: the rank of one symbol depends on every other, so computing them
    independently would mean re-reading the universe's history N times to
    produce N answers that must agree anyway.
    """

    def __init__(
        self,
        history_source: HistoricalBarSource,
        universe: tuple[str, ...],
        lookback_bars: int = DEFAULT_LOOKBACK_BARS,
        min_universe_size: int = MIN_UNIVERSE_SIZE,
    ) -> None:
        self.history_source = history_source
        self.universe = universe
        self.lookback_bars = lookback_bars
        self.min_universe_size = min_universe_size
        self._ranks: dict[str, float] | None = None

    async def rank_for(self, symbol: str) -> float | None:
        ranks = await self._ensure_ranks()
        return ranks.get(symbol)

    async def _ensure_ranks(self) -> dict[str, float]:
        if self._ranks is None:
            self._ranks = await self._compute_ranks()
        return self._ranks

    async def _compute_ranks(self) -> dict[str, float]:
        returns = {}
        for symbol in self.universe:
            trailing = await self._trailing_return(symbol)
            if trailing is not None:
                returns[symbol] = trailing

        if len(returns) < self.min_universe_size:
            logger.info(
                "Relative strength needs at least %d symbols with usable history; got %d - "
                "the rank is unavailable and strategies gating on it will abstain",
                self.min_universe_size,
                len(returns),
            )
            return {}

        return _percentile_ranks(returns)

    async def _trailing_return(self, symbol: str) -> float | None:
        try:
            bars = await self.history_source.get_daily_bars(
                symbol, n_bars=max(self.lookback_bars, DEFAULT_BARS // 2)
            )
        except Exception:  # noqa: BLE001 - one bad symbol must not void the universe
            logger.warning("No history for %s while ranking relative strength", symbol)
            return None

        if bars is None or bars.empty or "close" not in bars:
            return None

        closes = bars["close"].dropna()
        if len(closes) < 2:
            return None

        window = closes.iloc[-self.lookback_bars :] if len(closes) > self.lookback_bars else closes
        first = float(window.iloc[0])
        last = float(window.iloc[-1])
        if first <= 0:
            return None
        return (last - first) / first


def _percentile_ranks(returns: dict[str, float]) -> dict[str, float]:
    """0-100 percentile, where 100 is the strongest performer.

    Ties share the average of the positions they span, so two identical
    returns cannot be ordered by an accident of dictionary insertion order.
    """
    ordered = sorted(returns.items(), key=lambda item: item[1])
    count = len(ordered)

    positions: dict[str, float] = {}
    index = 0
    while index < count:
        end = index
        while end + 1 < count and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_position = (index + end) / 2.0
        for tied in range(index, end + 1):
            positions[ordered[tied][0]] = average_position
        index = end + 1

    if count == 1:
        return {symbol: 100.0 for symbol in positions}
    return {
        symbol: round(position / (count - 1) * 100.0, 1) for symbol, position in positions.items()
    }
