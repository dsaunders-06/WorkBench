"""`download()` does not raise, so our own failure warning never fired.

3 September: yfinance logged `HTTP Error 401 ... Invalid Crumb` under its OWN
logger and returned a frame. `_poll_once` wraps the call in try/except, so
nothing was caught - and `yfinance quote poll failed` appeared ZERO times while
the app had no usable quote for 25 minutes.

A partial response has to be a measured fact, not an absence.

⚠️ TWO DEFECTS FOUND WHILE BUILDING THIS, both of which made "missing" a lie:

* `normalise_frame` did not return empty for a ticker absent from a MultiIndex.
  It flattened to level 0 and handed back ANOTHER symbol's prices under the
  missing symbol's name, so a partial response MISLABELLED rather than omitted -
  and the poll counted the symbol as answered.
* A NaN close passed the `price <= 0` guard and became a tick priced `nan`.

Either one alone would let this file's central assertion pass while the feed was
silently wrong, which is why they are pinned here rather than left to Task 8.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource, to_yfinance


def _frame(symbols: list[str], close: float | None = 10.0) -> pd.DataFrame:
    """The shape `download()` returns for more than one ticker: a column
    MultiIndex, field on level 0 and ticker on the last level."""
    index = pd.to_datetime(["2026-09-04 03:00:00", "2026-09-04 03:01:00"])
    index.name = "Datetime"
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], [to_yfinance(s) for s in symbols]]
    )
    value = float("nan") if close is None else close
    return pd.DataFrame(
        [[value] * len(columns), [value] * len(columns)], index=index, columns=columns
    )


class _Client:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def download(self, tickers, **kwargs):
        return self._frame


@pytest.mark.asyncio
async def test_symbols_absent_from_the_response_are_reported() -> None:
    """⚠️ The 3 September shape: one symbol answers, the rest do not."""
    source = YFinanceMarketDataSource(client=_Client(_frame(["BHP.AX"])))

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX", "WOW.AX"])

    assert {t.symbol for t in ticks} == {"BHP.AX"}
    assert missing == {"CBA.AX", "WOW.AX"}


@pytest.mark.asyncio
async def test_an_absent_symbol_never_borrows_another_symbols_price() -> None:
    """⚠️ THE MISLABELLING GUARD. Before this, CBA came back holding BHP's
    prices - a wrong number is worse than a missing one, because the staleness
    rail and the sizer both believe it."""
    source = YFinanceMarketDataSource(client=_Client(_frame(["BHP.AX"], close=42.0)))

    ticks, _ = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert [(t.symbol, t.price) for t in ticks] == [("BHP.AX", 42.0)]


@pytest.mark.asyncio
async def test_a_nan_close_is_missing_rather_than_a_tick_priced_nan() -> None:
    """`nan <= 0` is False, so NaN sailed past the non-positive guard."""
    source = YFinanceMarketDataSource(client=_Client(_frame(["BHP.AX"], close=None)))

    ticks, missing = await source._poll_once(["BHP.AX"])

    assert all(math.isfinite(t.price) for t in ticks), "a tick priced nan was emitted"
    assert missing == {"BHP.AX"}


@pytest.mark.asyncio
async def test_a_complete_response_reports_nothing_missing() -> None:
    source = YFinanceMarketDataSource(client=_Client(_frame(["BHP.AX", "CBA.AX"])))

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert len(ticks) == 2
    assert missing == set()


@pytest.mark.asyncio
async def test_an_exception_reports_every_symbol_missing() -> None:
    class _Boom:
        def download(self, tickers, **kwargs):
            raise RuntimeError("network gone")

    source = YFinanceMarketDataSource(client=_Boom())

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert ticks == []
    assert missing == {"BHP.AX", "CBA.AX"}
