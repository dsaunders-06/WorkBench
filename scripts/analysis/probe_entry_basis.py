"""Does the entry record match what we actually paid? Read-only.

The slippage measurement showed AMD sized against a reference of 503.16 and
filled at 510.27. If the recorded entry price is the REFERENCE rather than the
FILL, then the ledger's cost basis is wrong, P&L is wrong by the drift, and the
R-multiple is wrong too - because R's denominator is entry minus stop.

That would be the same class as M42, where partial fills were counted at what
was assumed rather than at what the broker filled.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.trading.client import TradingClient  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

ENTRIES = Path.home() / "AppData/Local/QuantAdvisoryTerminal/data/open_position_entries.json"
entries = json.loads(ENTRIES.read_text(encoding="utf-8"))

client = TradingClient(
    api_key=get_secret(API_KEY_SECRET_NAME),
    secret_key=get_secret(SECRET_KEY_SECRET_NAME),
    paper=True,
)

print(f"{'sym':<7}{'recorded':>11}{'broker paid':>13}{'diff bps':>11}{'stop':>10}" f"{'R err':>9}")
print("-" * 61)
rows = []
for position in sorted(client.get_all_positions(), key=lambda p: p.symbol):
    entry = entries.get(position.symbol)
    if entry is None:
        continue
    recorded = float(entry["price"])
    paid = float(position.avg_entry_price)
    stop = entry.get("stop_price")
    bps = (paid - recorded) / recorded * 10_000
    # R is (exit - entry) / (entry - stop). Getting `entry` wrong distorts the
    # denominator, so every R-multiple on this trade is wrong by that ratio.
    if stop:
        r_recorded = recorded - float(stop)
        r_actual = paid - float(stop)
        r_err = (r_actual / r_recorded - 1) * 100 if r_recorded else 0.0
    else:
        r_err = 0.0
    rows.append((position.symbol, recorded, paid, bps, stop, r_err))
    print(
        f"{position.symbol:<7}{recorded:>11.2f}{paid:>13.2f}{bps:>11.1f}"
        f"{float(stop) if stop else 0:>10.2f}{r_err:>8.1f}%"
    )

drifted = [r for r in rows if abs(r[3]) > 1.0]
print("-" * 61)
print(f"  {len(rows)} positions, {len(drifted)} where the record differs from what was paid")
if drifted:
    worst = max(drifted, key=lambda r: abs(r[3]))
    print(
        f"  worst: {worst[0]} recorded {worst[1]:.2f}, paid {worst[2]:.2f} "
        f"({worst[3]:+.0f} bps, R denominator off by {worst[5]:+.1f}%)"
    )
