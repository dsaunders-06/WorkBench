"""The two numbers that decide whether anything trades. Read-only.

1. AGGREGATE RISK-AT-STOP. Reported at 5.02% against a 5.00% cap, which is why
   the book is currently refusing every new entry. It is computed from position
   quantities, current prices and stop levels - and today has shown that both
   the price inputs (IEX vs consolidated) and the recorded basis (M65) can be
   wrong. If this figure is wrong the book is either wrongly frozen or wrongly
   permissive, and no screen would say so.

   Recomputed here straight from the broker, following the governor's own rule:
   risk per share is price minus stop, or the WHOLE price when no stop is known,
   because unknown protection is treated as no protection.

2. RECORDED STOPS versus RESTING STOPS. M59 now detects a broker stop that has
   drifted from what the app believes, but that check has only ever run on a
   book where the two agreed. This is the same shape as M65 - record against
   reality - asked of the levels that protect the money.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.trading.client import TradingClient  # noqa: E402
from alpaca.trading.requests import GetOrdersRequest  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

DATA = Path.home() / "AppData/Local/QuantAdvisoryTerminal/data"
CAP_PCT = 0.05

client = TradingClient(
    api_key=get_secret(API_KEY_SECRET_NAME),
    secret_key=get_secret(SECRET_KEY_SECRET_NAME),
    paper=True,
)


def resting_stops() -> dict[str, float]:
    """Live protective legs, read the way ROADMAP says they must be.

    status=all with nested=True, and legs filtered on their OWN status: a
    protective leg is only returned when its parent is, and status=open drops a
    filled parent's still-live legs entirely.
    """
    stops: dict[str, float] = {}
    orders = client.get_orders(GetOrdersRequest(status="all", nested=True, limit=500))
    for order in orders:
        candidates = [order, *(getattr(order, "legs", None) or [])]
        for candidate in candidates:
            if candidate.side.value != "sell" or candidate.stop_price is None:
                continue
            if candidate.status.value not in {"new", "held", "accepted", "partially_filled"}:
                continue
            stops[candidate.symbol] = float(candidate.stop_price)
    return stops


account = client.get_account()
equity = float(account.equity)
positions = client.get_all_positions()
stops = resting_stops()

print("=" * 72)
print("1. AGGREGATE RISK-AT-STOP, recomputed from the broker")
print("=" * 72)
print(f"  {'sym':<7}{'qty':>6}{'price':>10}{'stop':>10}{'risk/share':>12}{'risk $':>12}")
total_risk = 0.0
unprotected: list[str] = []
for position in sorted(positions, key=lambda p: p.symbol):
    quantity = abs(float(position.qty))
    price = float(position.current_price)
    stop = stops.get(position.symbol)
    if stop is None or stop >= price:
        # The governor's rule: unknown protection is no protection.
        per_share = price
        unprotected.append(position.symbol)
        shown_stop = "none"
    else:
        per_share = price - stop
        shown_stop = f"{stop:.2f}"
    risk = quantity * per_share
    total_risk += risk
    print(
        f"  {position.symbol:<7}{quantity:>6.0f}{price:>10.2f}{shown_stop:>10}"
        f"{per_share:>12.2f}{risk:>12.2f}"
    )

pct = total_risk / equity if equity else 0.0
print("-" * 72)
print(f"  equity                 ${equity:,.2f}")
print(f"  risk at stop           ${total_risk:,.2f}")
print(f"  as a percentage         {pct:.2%}   (cap {CAP_PCT:.2%})")
print(f"  headroom               ${CAP_PCT * equity - total_risk:,.2f}")
print(f"  verdict                 {'AT OR OVER the cap' if pct >= CAP_PCT else 'under the cap'}")
if unprotected:
    print(f"  counted at FULL VALUE   {', '.join(unprotected)}")

print()
print("=" * 72)
print("2. RECORDED STOP versus RESTING STOP")
print("=" * 72)
entries = json.loads((DATA / "open_position_entries.json").read_text(encoding="utf-8"))
print(f"  {'sym':<7}{'recorded':>11}{'resting':>11}{'diff':>10}{'':>4}")
mismatches = 0
for position in sorted(positions, key=lambda p: p.symbol):
    entry = entries.get(position.symbol)
    recorded = entry.get("stop_price") if entry else None
    resting = stops.get(position.symbol)
    if recorded is None or resting is None:
        print(
            f"  {position.symbol:<7}{'—' if recorded is None else f'{recorded:.2f}':>11}"
            f"{'—' if resting is None else f'{resting:.2f}':>11}{'n/a':>10}"
        )
        continue
    diff = resting - float(recorded)
    # The same relative tolerance M59 uses, so this asks exactly what the
    # running application now asks.
    flag = "  <-- DIFFERS" if abs(diff) > 1e-4 * abs(float(recorded)) else ""
    mismatches += bool(flag)
    print(f"  {position.symbol:<7}{float(recorded):>11.4f}{resting:>11.2f}{diff:>10.4f}{flag}")

print("-" * 72)
print(f"  {mismatches} position(s) where the recorded stop differs from what rests")
