"""Strategy interface (spec §F): strategies consume feature/price snapshots
and emit SignalEvent - they never size positions or place orders.

SignalEvent (declared in domain.events since M1) already has exactly the
fields the spec's pseudocode Signal type describes, so strategies return
list[SignalEvent] directly rather than introducing a redundant Signal type.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import pandas as pd

from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.events import SignalEvent
from qat.domain.regime import Regime


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


class Strategy(Protocol):
    name: str

    def suitable_regimes(self) -> set[Regime]: ...

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]: ...

    def params(self) -> dict[str, Any]: ...
