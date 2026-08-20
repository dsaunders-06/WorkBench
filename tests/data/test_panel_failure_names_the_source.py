"""M118: "no real daily bars" read as a rate limit when it was the wrong source.

On the evening of 20 August a measurement harness reported

    No real daily bars for 7 of 7 symbols - they are left unseeded rather than
    filled: STW.AX, RIO.AX, APA.AX, ...

seven times over four hours. It was read as a yfinance rate limit, waited out,
retried, and written into the handover as the next session's top risk. It was
none of those things: the harness was resolving an ALPACA history source and
asking it for ASX symbols, which it cannot serve at all.

The message is identical in both cases. A vendor throttling us and a source that
could never answer produce the same line, and the difference is the whole
diagnosis - one clears on its own and the other never will.

M106 already made this argument for the pre-flight's feed check: a source that
prices NONE of what it was asked is a SOURCE failure, not N delistings. The same
line of reasoning was missing one layer down, in the panel every warm start uses.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.history import fetch_daily_panel


class _Empty:
    """A source that answers nothing - a throttle, an outage, or a source that
    was never able to serve these symbols. Indistinguishable from here, which
    is exactly why the message must name which source it was."""

    async def get_daily_bars(self, symbol: str, n_bars: int) -> pd.DataFrame | None:
        return None


class _PartiallyBlind:
    async def get_daily_bars(self, symbol: str, n_bars: int) -> pd.DataFrame | None:
        if symbol == "GOOD.AX":
            return pd.DataFrame({"ts": pd.to_datetime(["2026-08-20"]), "close": [1.0]})
        return None


@pytest.mark.asyncio
async def test_a_total_failure_names_the_source_and_calls_it_a_source_failure(caplog) -> None:
    """The line that misled: it named the symbols and never the source."""
    import logging

    with caplog.at_level(logging.WARNING):
        await fetch_daily_panel(_Empty(), ["RIO.AX", "APA.AX"], 300)

    message = " ".join(caplog.messages)
    assert "_Empty" in message, "the source that failed must be named"
    assert "SOURCE" in message
    # and it must NOT invite the reader to go and check the symbols
    assert "delisted" not in message.lower()


@pytest.mark.asyncio
async def test_a_partial_failure_still_names_the_symbols(caplog) -> None:
    """When SOME priced, the source plainly works and the symbols are the story.
    That is the case the original message was written for and it stays."""
    import logging

    with caplog.at_level(logging.WARNING):
        await fetch_daily_panel(_PartiallyBlind(), ["GOOD.AX", "BAD.AX"], 300)

    message = " ".join(caplog.messages)
    assert "BAD.AX" in message
    assert "1 of 2" in message or "1 of the 2" in message


@pytest.mark.asyncio
async def test_everything_priced_says_nothing(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        panel = await fetch_daily_panel(_PartiallyBlind(), ["GOOD.AX"], 300)

    assert len(panel.frames) == 1
    assert not caplog.messages
