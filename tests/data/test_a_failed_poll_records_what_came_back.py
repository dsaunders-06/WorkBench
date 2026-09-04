"""Three hypotheses were tested on 3 September and all three failed.

NOT the batch size: in a fresh process 100, 75, 50, 30, 20 and 10 symbols all
returned complete data, 100/100 in 3.7s. NOT the crumb on the price path: a
deliberately poisoned `_crumb` still returned 295 rows, because `download()` does
not use it. NOT an ongoing 401 storm: the burst was 13 errors between 14:51:28 and
14:52:15, then nothing, while the outage ran twenty-five minutes longer.

So the mechanism is UNKNOWN, and this records what a failing poll actually saw
rather than shipping a remedy for a guess.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource, to_yfinance


def _multi_index_frame(symbols: list[str]) -> pd.DataFrame:
    """The shape `download()` returns for MORE THAN ONE ticker.

    A column MultiIndex, field on level 0 and ticker on the last level. Built
    here because single-symbol fixtures return plain columns and would never
    exercise the `xs(..., level=-1)` path `normalise_frame` relies on.
    """
    index = pd.to_datetime(["2026-09-04 03:00:00", "2026-09-04 03:01:00"])
    index.name = "Datetime"
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], [to_yfinance(s) for s in symbols]]
    )
    return pd.DataFrame(
        [[10.0] * len(columns), [11.0] * len(columns)], index=index, columns=columns
    )


class _EmptyClient:
    def download(self, tickers, **kwargs):
        return pd.DataFrame()


class _CompleteClient:
    """Returns every symbol it was asked for."""

    def download(self, tickers, **kwargs):
        return _multi_index_frame(list(tickers))


@pytest.mark.asyncio
async def test_a_partial_poll_records_requested_against_returned(caplog):
    source = YFinanceMarketDataSource(client=_EmptyClient())

    with caplog.at_level(logging.WARNING):
        await source._poll_once(["BHP.AX", "CBA.AX", "WOW.AX"])

    assert "3" in caplog.text, "the number REQUESTED must be recorded"
    assert "0" in caplog.text, "the number RETURNED must be recorded"


@pytest.mark.asyncio
async def test_the_probe_records_whether_a_session_was_cached(caplog):
    """The one fact that separates a poisoned process from a poisoned account."""
    source = YFinanceMarketDataSource(client=_EmptyClient())

    with caplog.at_level(logging.WARNING):
        await source._poll_once(["BHP.AX"])

    lowered = caplog.text.lower()
    assert "crumb" in lowered and "cookie" in lowered


@pytest.mark.asyncio
async def test_a_complete_poll_records_nothing(caplog):
    """The probe must not add a line to every healthy poll - 60 a minute of
    them would bury the one that matters."""
    source = YFinanceMarketDataSource(client=_CompleteClient())

    with caplog.at_level(logging.WARNING):
        ticks = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert len(ticks) == 2, "the fixture must actually produce ticks, or this proves nothing"
    assert "requested symbol" not in caplog.text


@pytest.mark.asyncio
async def test_the_probe_never_breaks_the_poll(caplog, monkeypatch):
    """A diagnostic must never break the feed it is diagnosing. If reading
    yfinance's cached session state raises, the poll still completes and the
    counts - the part that matters - are still recorded.

    A MIXED response would be the sharper fixture, and it cannot be built
    against `normalise_frame` as it stands: given a MultiIndex that lacks the
    requested ticker it does not return empty, it flattens to level 0 and hands
    back ANOTHER symbol's prices under the missing symbol's name. That belongs
    to Task 7, which validates what came back; recorded, not fixed here.
    """
    from qat.data import yfinance_source

    def _explode() -> str:
        raise RuntimeError("yfinance moved its internals")

    monkeypatch.setattr(yfinance_source, "_cached_session_state", _explode)
    source = YFinanceMarketDataSource(client=_EmptyClient())

    with caplog.at_level(logging.WARNING):
        ticks = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert ticks == [], "the poll must return, not raise"
    lowered = caplog.text.lower()
    assert "cookie" in lowered and "crumb" in lowered, "and the counts must still be recorded"
