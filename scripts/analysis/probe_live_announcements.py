r"""Does the deployed announcements path actually reach Alpaca? (M39)

The monitor logs nothing when a query succeeds and returns no announcements -
deliberately, because a line per symbol per sweep is noise. That means "working
and nothing pending" and "quietly returning nothing" look identical in the log,
which is the failure mode this project has already named: quiet looks exactly
like healthy.

So this calls the adapter's OWN method - the same code the deployed build runs -
against the live account, over the same window the monitor uses, and prints what
comes back. Read-only. Places nothing, modifies nothing.

    ./.venv/Scripts/python.exe scripts/analysis/probe_live_announcements.py
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from qat.config import Settings
from qat.data.broker.alpaca_adapter import AlpacaAdapter
from qat.domain.corporate_actions.monitor import _LOOKAHEAD_DAYS, _LOOKBACK_DAYS

HELD = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]


async def main() -> None:
    adapter = AlpacaAdapter(settings=Settings(_env_file=None))
    today = datetime.now(UTC).date()
    since = today - timedelta(days=_LOOKBACK_DAYS)
    until = today + timedelta(days=_LOOKAHEAD_DAYS)
    print(f"Window the monitor uses: {since} to {until}")
    print(f"  (_LOOKBACK_DAYS={_LOOKBACK_DAYS}, _LOOKAHEAD_DAYS={_LOOKAHEAD_DAYS})")
    print()

    total = 0
    for symbol in HELD:
        found = await adapter.announcements(symbol, since, until)
        total += len(found)
        detail = ", ".join(f"ex {a.ex_date} ratio {a.ratio:g}" for a in found) if found else "none"
        print(f"  {symbol:<6} {len(found)} - {detail}")
    print()
    print(f"total in the monitor's window: {total}")

    # The call itself proven live, against a window wide enough to contain a
    # known real announcement. CRWD split 4-for-1 with ex-date 2 July, so a
    # window reaching back that far MUST return it - if this comes back empty
    # too, the path is broken rather than the market being quiet.
    print()
    print("=== control: CRWD over a window that must contain its 2 July split ===")
    control = await adapter.announcements("CRWD", date(2026, 6, 1), date(2026, 8, 1))
    if not control:
        print("  EMPTY - the announcements path is NOT working, and the silence above")
        print("  means nothing at all. This is the finding.")
    for a in control:
        print(f"  CRWD ex {a.ex_date} ratio {a.ratio:g} payable {a.payable_date} id {a.action_id}")


if __name__ == "__main__":
    asyncio.run(main())
