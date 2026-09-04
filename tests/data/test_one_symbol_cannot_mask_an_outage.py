"""One symbol answering hid a ninety-nine symbol outage.

`stream_ticks` held ONE counter and reset it whenever a poll produced any tick:

    if ticks:
        consecutive_failures = 0

On 3 September exactly one of 100 symbols answered, for 25 minutes. There was no
`poll produced no ticks` line, no `MARKET DATA DOWN`, and the app placed an order
whose price-drift check was skipped for want of a quote.

⚠️ AND THE OPEN MUST NOT TRIP IT. Yahoo publishes ASX intraday ~20 minutes late,
so at every open EVERY symbol is legitimately absent. On 21 August that shape
ended the stream at 10:04 waiting for data that arrived at 10:22, and the account
sat flat and blind on an open market. That is the M119 regression this test set
exists to prevent as much as the outage itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource, to_yfinance
from qat.logging import BLIND_WINDOW_FILTER

SYMBOLS = [f"S{i}.AX" for i in range(100)]


def _frame(symbols: list[str]) -> pd.DataFrame:
    """The multi-index shape `normalise_frame` expects for many tickers.

    ⚠️ Built to that function's real contract - field on level 0, ticker on the
    LAST level - because a frame of the wrong shape would make every test in
    this file pass for the wrong reason.
    """
    if not symbols:
        return pd.DataFrame()
    index = pd.to_datetime(["2026-09-04 03:00:00", "2026-09-04 03:01:00"])
    index.name = "Datetime"
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], [to_yfinance(s) for s in symbols]]
    )
    return pd.DataFrame(
        [[10.0] * len(columns), [11.0] * len(columns)], index=index, columns=columns
    )


class _PartialClient:
    """Answers for `answering` and returns nothing for the rest, every poll."""

    def __init__(self, answering: list[str]) -> None:
        self.answering = answering
        self.calls = 0

    def download(self, tickers, **kwargs):
        self.calls += 1
        return _frame(self.answering)


class _RecoveringClient(_PartialClient):
    """Silent for `silent_polls`, then answers for everything."""

    def __init__(self, silent_polls: int) -> None:
        super().__init__(answering=[])
        self._silent_polls = silent_polls

    def download(self, tickers, **kwargs):
        self.calls += 1
        if self.calls <= self._silent_polls:
            return _frame([])
        return _frame(SYMBOLS)


def _source(client: _PartialClient) -> YFinanceMarketDataSource:
    # Zero delays rather than a patched `asyncio.sleep`: `_delay_after` returns
    # `poll_seconds` while healthy and a capped backoff once failing, so zeroing
    # both drives the real loop at full speed with no monkeypatching at all.
    return YFinanceMarketDataSource(
        client=client,
        poll_seconds=0.0,
        max_backoff_seconds=0.0,
        max_consecutive_failures=5,
    )


async def _drain(source: YFinanceMarketDataSource, client: _PartialClient, polls: int) -> None:
    """Drive `stream_ticks` for `polls` polls, then stop it.

    The generator only yields when a poll produced ticks, so awaiting it
    directly would hang on the silent cases this file is about. Consuming it in
    a task and watching the client's own call count is what makes the stop
    condition the number of POLLS rather than the number of ticks.
    """
    agen = source.stream_ticks(SYMBOLS)

    async def consume() -> None:
        async for _ in agen:
            pass

    task = asyncio.create_task(consume())
    try:
        deadline = time.monotonic() + 5.0
        while client.calls < polls and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        assert client.calls >= polls, f"only {client.calls} polls ran - the loop stalled"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await agen.aclose()


@pytest.fixture(autouse=True)
def _reset_blind_window():
    """`BLIND_WINDOW_FILTER` is module-level global state, so one test leaving it
    set would decide the next one's result."""
    BLIND_WINDOW_FILTER.blind = False
    yield
    BLIND_WINDOW_FILTER.blind = False


@pytest.mark.asyncio
async def test_one_answering_symbol_does_not_mask_the_other_ninety_nine(caplog) -> None:
    """⚠️ THE 3 SEPTEMBER CASE, and the test this task exists for."""
    client = _PartialClient(answering=[SYMBOLS[0]])
    with caplog.at_level(logging.ERROR):
        await _drain(_source(client), client, polls=6)

    assert "market data is down" in caplog.text.lower()
    assert "S1.AX" in caplog.text, "the DOWN line must NAME the failing symbols"


@pytest.mark.asyncio
async def test_a_single_absent_symbol_never_reports_down(caplog) -> None:
    """One delisted or thinly-traded name is not an outage."""
    client = _PartialClient(answering=SYMBOLS[1:])
    with caplog.at_level(logging.ERROR):
        await _drain(_source(client), client, polls=6)

    assert "market data is down" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_open_does_not_report_down(caplog) -> None:
    """⚠️ THE M119 REGRESSION, ASSERTED DIRECTLY. At the open Yahoo has published
    nothing yet, so ALL symbols are absent - legitimately, for ~20 minutes. On
    21 August that shape ended the stream and the account sat blind on an open
    market for two hours.

    ⚠️ Captured at WARNING, not ERROR. Found by sabotage: at ERROR this passed
    even with the open's line reworded to say "market data is down", because the
    call is `logger.warning`. A guard that only sees one severity does not guard
    the phrase.
    """
    client = _PartialClient(answering=[])
    with caplog.at_level(logging.WARNING):
        await _drain(_source(client), client, polls=6)

    assert "market data is down" not in caplog.text.lower()
    assert "no symbol has answered yet" in caplog.text, (
        "the open must still SAY something - going silent would trade a false alarm "
        "for no signal at all"
    )


@pytest.mark.asyncio
async def test_coverage_returning_resets_the_counters(caplog) -> None:
    """After the delay window clears, a full response must clear the state -
    otherwise every session reports DOWN for the rest of the day."""
    client = _RecoveringClient(silent_polls=6)
    source = _source(client)
    await _drain(source, client, polls=6)
    caplog.clear()

    with caplog.at_level(logging.ERROR):
        await _drain(source, client, polls=14)

    assert "market data is down" not in caplog.text.lower()
    assert BLIND_WINDOW_FILTER.blind is False
