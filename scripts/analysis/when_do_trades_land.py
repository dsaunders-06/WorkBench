"""When can the current book actually produce closed trades?

Reads the real open positions and the real configured rails, then walks the
real trading calendar. No new evidence can arrive before these dates unless a
stop fires.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from qat.config import Settings
from qat.domain import market_calendar as mc

entries = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
settings = Settings(_env_file=None)

print(f"min hold  : {settings.min_holding_trading_days} trading days")
print(f"time stop : {settings.time_stop_trading_days} trading days")
print(f"positions : {len(entries)}\n")


def add_trading_days(start: date, count: int) -> date:
    day = start
    remaining = count
    while remaining > 0:
        day += timedelta(days=1)
        if mc.is_trading_day("US", day):
            remaining -= 1
    return day


rows = []
for symbol, detail in entries.items():
    opened = date.fromisoformat(detail["opened_at"][:10])
    rows.append(
        (
            symbol,
            opened,
            add_trading_days(opened, settings.min_holding_trading_days),
            add_trading_days(opened, settings.time_stop_trading_days),
        )
    )

rows.sort(key=lambda r: r[3])
print(f"{'symbol':<7}{'opened':<13}{'min hold ends':<16}{'time stop':<13}")
for symbol, opened, hold, stop in rows:
    print(f"{symbol:<7}{opened.isoformat():<13}{hold.isoformat():<16}{stop.isoformat():<13}")

first, last = rows[0][3], rows[-1][3]
print(f"\nfirst time stop : {first:%A %d %B %Y}")
print(f"last time stop  : {last:%A %d %B %Y}")
print(f"whole book exits within {(last - first).days} days of itself")
print(f"days from today ({date.today()}) to the first: {(first - date.today()).days}")
