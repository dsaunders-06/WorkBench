"""The known blind window must not drown the log (item 54).

Yahoo publishes ASX intraday about 20 minutes late, so every poll from the bell
lands inside a window the app ALREADY KNOWS it is blind in - and yfinance logs
one ERROR per symbol per poll:

    $PMV.AX: possibly delisted; no price data found  (period=1d)

95 symbols x roughly five polls. On 27 August that produced ~475 ERROR lines in
four minutes and **buried a real `BROKER-SIDE FILL absorbed` line for RHC.AX
under about three hundred of them**. The volume is not a cosmetic problem: the
log is the diagnostic surface, and rotation evicts real evidence to make room.

⚠️ **NOT a blanket silence, and that is the whole design.** A genuinely
delisted symbol is a real event and must stay visible. What is redundant is the
per-symbol repetition during a window the app already reports once. So the
filter suppresses only while the feed says it is blind, counts what it dropped,
and the count is surfaced rather than discarded.

⚠️ `NOISY_LIBRARY_LOGGERS` cannot do this job - it raises a logger to WARNING
and yfinance logs these at ERROR, so the mechanism that already exists for
`ib_async` would let every one of them through.
"""

from __future__ import annotations

import logging

import pytest

from qat.logging import BlindWindowFilter


@pytest.fixture
def blind_filter() -> BlindWindowFilter:
    return BlindWindowFilter()


def _record(message: str, level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord("yfinance", level, __file__, 1, message, None, None)


_DELISTED = "$PMV.AX: possibly delisted; no price data found  (period=1d)"


def test_it_passes_everything_through_when_the_feed_is_not_blind(blind_filter) -> None:
    """The default. A delisting error outside the blind window is a real event
    about a real symbol and must reach the log."""
    assert blind_filter.filter(_record(_DELISTED)) is True


def test_it_suppresses_the_delisting_storm_while_the_feed_is_blind(blind_filter) -> None:
    blind_filter.blind = True

    assert blind_filter.filter(_record(_DELISTED)) is False


def test_it_counts_what_it_dropped(blind_filter) -> None:
    """Suppressed, not discarded. A count nobody can read is a silence."""
    blind_filter.blind = True
    for _ in range(95):
        blind_filter.filter(_record(_DELISTED))

    assert blind_filter.suppressed == 95


def test_the_count_resets_when_it_is_taken(blind_filter) -> None:
    blind_filter.blind = True
    blind_filter.filter(_record(_DELISTED))

    assert blind_filter.take_suppressed() == 1
    assert blind_filter.take_suppressed() == 0


def test_an_unrelated_yfinance_error_survives_the_blind_window(blind_filter) -> None:
    """⚠️ The line this design must not cross. Suppressing by LOGGER would hide
    a real failure - a 401, a rate limit, a schema change - inside the very
    window where the feed is already struggling. Only the known-redundant
    message is dropped."""
    blind_filter.blind = True

    assert blind_filter.filter(_record("HTTP Error 401: Invalid Crumb")) is True


def test_a_genuine_delisting_outside_the_window_is_never_lost(blind_filter) -> None:
    """COL.AX and GQG.AX really did log this on 26 August with the feed healthy.
    That is a symbol to investigate, not noise."""
    blind_filter.blind = True
    blind_filter.blind = False

    assert blind_filter.filter(_record("$COL.AX: possibly delisted; no price data found")) is True
