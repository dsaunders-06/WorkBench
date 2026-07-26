"""Strategy interface (spec §F): strategies consume feature/price snapshots
and emit SignalEvent - they never size positions or place orders.

SignalEvent (declared in domain.events since M1) already has exactly the
fields the spec's pseudocode Signal type describes, so strategies return
list[SignalEvent] directly rather than introducing a redundant Signal type.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import pandas as pd

from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.events import SignalEvent
from qat.domain.regime import Regime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SymbolContext:
    symbol: str
    bars: pd.DataFrame  # columns: ts, open, high, low, close, volume; ascending
    technical: dict[str, float]  # from qat.data.features.FeatureBuilder
    fundamentals: FundamentalSnapshot


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    symbol: str
    as_of: datetime
    context: SymbolContext
    universe: Mapping[str, SymbolContext]  # every tracked symbol, including self
    # Current holdings by symbol (M14). Strategies need this to emit *exits*:
    # "the trend that justified holding this has broken" is a different
    # question from "is this a good entry", and cannot be asked without
    # knowing whether anything is held. Empty when positions are unavailable,
    # which correctly reads as "hold nothing, so no exit applies".
    positions: Mapping[str, float] = field(default_factory=dict)

    def held_quantity(self, symbol: str | None = None) -> float:
        return float(self.positions.get(symbol or self.symbol, 0.0))


def unavailable(strategy: str, context: SymbolContext, *names: str) -> tuple[str, ...]:
    """The fields `strategy` needs that this symbol cannot supply (M18).

    Truthy means abstain. Every fundamentals-driven strategy calls this before
    reading a figure, because a real vendor genuinely cannot answer for every
    symbol - an index ETF has no ROE or EPS growth - and the alternative to
    abstaining is scoring it on a substitute nobody can distinguish from a
    measurement afterwards.

    Logged at DEBUG: with a watchlist of ETFs this fires on every symbol on
    every tick, and an abstention is the system working, not an error.
    """
    absent = context.fundamentals.missing(*names)
    if absent:
        logger.debug(
            "%s abstains on %s: no %s", strategy, context.symbol, ", ".join(sorted(absent))
        )
    return absent


class Strategy(Protocol):
    name: str

    def suitable_regimes(self) -> set[Regime]: ...

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]: ...

    def params(self) -> dict[str, Any]: ...
