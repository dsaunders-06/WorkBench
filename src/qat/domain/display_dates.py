"""How a date reads on screen, for a human, in one place (the ASX move).

The system is moving from a US Alpaca paper account to the ASX: the US period
ends 19 August 2026, after which the operator trades this book against an
Australian broker with Australian eyes reading the screen every day.
`18/08/2026` is unambiguous to that reader; `2026-08-18` is not wrong, but it
is the wrong convention for where this is going - and a US reader could at
least misread `08/18/2026` as day-first, where an Australian reader has no
such fallback at all.

**This is a DISPLAY concern only.** Nothing written to disk, logged, or
handed back to another system should route through this module - ISO-8601
remains correct for a record, and stays correct after the move, because
nothing that re-reads a record cares what country issued the exchange. If a
future change finds this function's output flowing into a CSV row, a JSON
payload, or a log line, that is the change to revert, not this docstring.

One function, so a fix or a future convention change (locale-driven
formatting, for instance) happens once rather than being re-typed at every
call site that shows a date. Before this module existed, the same
`%Y-%m-%d` format string was typed out independently at half a dozen call
sites across the presentation layer and the positions panel - eight chances
for one of them to drift from the rest, and no way to tell from any single
site that it had.

Domain, not presentation: `qat.domain.oms.position_view` needs this and must
not import from `qat.presentation` (that layering is deliberate), so the
formatter lives somewhere both layers can reach.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

# DD/MM/YYYY - the Australian convention, and the reason this module exists.
# `datetime` is accepted as well as `date` because `strftime` does not care,
# and the callers with a timestamp (a fill time, an audit entry) want only
# its date component formatted this way - they format the time-of-day
# themselves, alongside this, in whatever precision that call site needs.
_AU_DATE_FORMAT = "%d/%m/%Y"


def format_display_date(value: date | datetime) -> str:
    """The Australian-convention rendering of `value`'s date, for a screen.

    `datetime` is accepted because most of what this app has on hand already
    carries a time-of-day; only the date component is formatted here. A
    caller that also wants the time shows it separately, e.g.
    `f"{format_display_date(ts)} {ts:%H:%M}"`.
    """
    return value.strftime(_AU_DATE_FORMAT)


__all__ = ["format_display_date"]


def format_session_time(value: datetime, market: str = "ASX") -> str:
    """`HH:MM:SS ZONE` in the MARKET's timezone (item 40).

    Times shown to a human must not be silent UTC. On 25 August four surfaces
    rendered UTC among fields that were session-local, the worst being
    `watch_session.py`'s live console line, which carried no zone label at all
    - read 03:21:34 off it at 13:21 AEST and a ten-hour error lands in the
    middle of an incident, which is the only time anyone reads it.

    The zone is ALWAYS named. Converting without saying so just moves the
    ambiguity; the Risk Console's anomaly rows were never confusing precisely
    because they said "UTC" out loud.

    A naive timestamp is treated as UTC rather than as local. Records written
    before this existed carry naive UTC, and guessing local would shift every
    one of them by ten hours.

    This is for DISPLAY only. The log's own `ts` field stays UTC-with-offset:
    machine records want a single zone.
    """
    from qat.domain.market_calendar import MARKET_TIMEZONES

    # Widened to str keys deliberately: `market` arrives from settings and from
    # display code, and an unknown value must fall back rather than raise. A
    # clock that throws is worse than one showing the wrong exchange's zone,
    # because this is only ever rendering a label.
    zones: dict[str, ZoneInfo] = {str(k): v for k, v in MARKET_TIMEZONES.items()}
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local = value.astimezone(zones.get(market, zones["ASX"]))
    return f"{local:%H:%M:%S} {local:%Z}"
