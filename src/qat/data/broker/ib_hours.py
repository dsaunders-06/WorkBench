"""IBKR's trading-hours strings, parsed.

`ContractDetails.tradingHours` and `.liquidHours` are the exchange's own
statement of its session, per contract and per day, holidays and half-days
included. **`liquidHours` is continuous trading and `tradingHours` spans the
auctions**, so the difference between them is the auction windows.

Measured 21 August 2026 and RE-MEASURED 9 September (`scripts/asx_session_probe.py`,
raw reports beside this repo's specs). The ASX answers with an eleven-minute
tail - 1600 against 1611 - and an identical open on both strings. That is what
settles that the closing auction is derivable from this feed and the staggered
opening auction is not: all fourteen contracts probed, spanning A2M to XRO,
returned byte-identical hours.

Lives at the vendor boundary rather than in `market_calendar` on purpose: the
domain module is imported by the replay harness and must not acquire a vendor's
string format. This module knows IBKR's shape and nothing about sessions.

Pure. No ib_async import, no I/O, no clock.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# "20260910:0959-20260910:1611" or "20260912:CLOSED", semicolon-separated, and
# a single day may carry comma-separated windows.
_CLOSED = "CLOSED"


def _parse_stamp(stamp: str, tz: ZoneInfo) -> datetime:
    """One `YYYYMMDD:HHMM` stamp, in the exchange's own zone.

    Constructed with `tzinfo=` directly, which is correct for `zoneinfo` (and
    would not be for `pytz`). An ambiguous local time at a DST fall-back
    resolves with `fold=0`; no ASX session boundary reaches one, because
    Australia's transitions land on Sundays, which the exchange reports CLOSED.
    """
    day, clock = stamp.split(":")
    return datetime(
        int(day[0:4]),
        int(day[4:6]),
        int(day[6:8]),
        int(clock[0:2]),
        int(clock[2:4]),
        tzinfo=tz,
    )


def parse_ib_hours(text: str, tz: ZoneInfo) -> dict[date, tuple[tuple[datetime, datetime], ...]]:
    """Windows per exchange-local date. A CLOSED day maps to an empty tuple.

    Returns `{}` on anything it cannot read, rather than raising. This is
    consumed by pre-flight, where a vendor string in an unexpected shape must
    degrade to "no comparison available" and never take down the checks that
    surround it. A parser that raised here would convert a cosmetic surprise
    into a session that will not start.

    ⚠️ ONE BAD SEGMENT DISCARDS THE WHOLE STRING, deliberately. Half a calendar
    is worse than none: the consumer compares IBKR's CLOSED days against a
    hand-maintained holiday table, so a silently truncated answer would report
    every dropped day as a disagreement, and the check exists to be believed.

    A CLOSED day is RECORDED rather than omitted, because "IBKR says closed"
    and "IBKR did not mention that day" are different facts and the holiday
    comparison needs to tell them apart.
    """
    if not text:
        return {}

    windows: dict[date, list[tuple[datetime, datetime]]] = {}
    try:
        for raw in text.split(";"):
            segment = raw.strip()
            if not segment:
                continue
            if segment.upper().endswith(_CLOSED):
                day = segment.split(":")[0]
                windows.setdefault(date(int(day[0:4]), int(day[4:6]), int(day[6:8])), [])
                continue
            for window in segment.split(","):
                start_stamp, end_stamp = window.split("-")
                start = _parse_stamp(start_stamp, tz)
                end = _parse_stamp(end_stamp, tz)
                # Keyed on the START date: a window spanning midnight belongs
                # to the session that opened it, not to the date it ends on.
                windows.setdefault(start.date(), []).append((start, end))
    except (ValueError, IndexError):
        return {}
    return {day: tuple(spans) for day, spans in windows.items()}
