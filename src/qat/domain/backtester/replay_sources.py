"""In-memory warm-start ports for the replay harness (W2 step 4).

The production `WarmStart` seeds every aggregator and the regime engine from a
HistoricalBarSource and a MacroDataSource. The harness already holds its bars,
so rather than a second warm-start path it supplies those two ports - which is
what keeps there being exactly one implementation of "fill the buffers".

Both are bounded at the replay boundary. A simulator holds the whole series in
memory, and nothing except the bound stops the warm start handing the strategy
and the regime engine data from the future.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from qat.data.bars import BAR_COLUMNS
from qat.data.history import DEFAULT_BARS
from qat.data.macro_fred import MacroObservation


class ReplayHistorySource:
    """Daily bars up to the replay boundary, in BAR_COLUMNS shape."""

    def __init__(self, bars: dict[str, pd.DataFrame], until_index: int) -> None:
        self._bars = bars
        self._until_index = max(0, until_index)

    async def get_daily_bars(self, symbol: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
        frame = self._bars.get(symbol)
        if frame is None:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        prefix = frame.iloc[: self._until_index]
        if prefix.empty:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        window = prefix.iloc[-n_bars:] if n_bars > 0 else prefix
        out = window.reset_index()
        out = out.rename(columns={out.columns[0]: "ts"})
        if "volume" not in out.columns:
            out["volume"] = 0.0
        return out[list(BAR_COLUMNS)]


class ReplayMacroSource:
    """Macro observations that had already been published at the boundary.

    `<=` rather than `<`: a series publishing on the boundary date was genuinely
    available that day, and excluding it would understate what the warm start
    could have known.
    """

    def __init__(self, observations: dict[str, list[MacroObservation]], until: datetime) -> None:
        self._observations = observations
        self._until = until

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        return [o for o in self._observations.get(series_id, []) if o.ts <= self._until]
