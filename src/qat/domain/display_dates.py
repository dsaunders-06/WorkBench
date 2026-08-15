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

from datetime import date, datetime

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
