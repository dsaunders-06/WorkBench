"""Audit, brief §13: the evidence chain - closed trades, Kelly inputs, promotion.

Read-only. Reads closed_trades.csv; writes nothing.

    python evidence_chain.py <data_dir>

Applies the EdgeEstimator's own arithmetic (performance/edge.py:34-41,
102-132; metrics.py:128-147) to the positions closed so far, to show what the
sizer would use if measurement were switched on now, beside the placeholder it
uses until 20 closed positions (settings.edge_min_trades).

The ledger is collapsed to positions by order_id here, as the promotion
scorecard's count of 8 on 11 Sep implies. The rate and "trades still needed"
lines are arithmetic on the record, not a forecast.

Run it from PowerShell (HANDOFF, "THE ONE RULE").
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean

AEST = timezone(timedelta(hours=10))
KELLY_FRACTION = 0.5
PLACEHOLDER_W, PLACEHOLDER_R = 0.55, 1.5
EDGE_MIN_TRADES, PROMOTION_TRADES = 20, 30


def kelly(w: float, r: float) -> float:
    return KELLY_FRACTION * max(0.0, w - (1 - w) / r)


def weekdays(start: date, end: date) -> int:
    return sum(1 for n in range((end - start).days + 1) if (start + timedelta(n)).weekday() < 5)


def main(data_dir: Path) -> None:
    rows = list(csv.DictReader((data_dir / "closed_trades.csv").open(newline="", encoding="utf-8")))
    positions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        positions[r["order_id"]].append(r)
    print(f"ledger rows {len(rows)} -> positions {len(positions)}")
    pnls: list[float] = []
    symbols: list[str] = []
    closes = []
    for oid, fills in positions.items():
        pnl = sum(float(f["net_pnl"]) for f in fills)
        closed = max(datetime.fromisoformat(f["closed_at"]) for f in fills).astimezone(AEST)
        pnls.append(pnl)
        symbols.append(fills[0]["symbol"])
        closes.append(closed)
        print(
            f"  {fills[0]['symbol']:7s} closed {closed:%d %b} {fills[-1]['exit_reason'][:28]:28s} "
            f"net {pnl:10,.2f}  ({len(fills)} row(s), order {oid})"
        )

    placeholder = kelly(PLACEHOLDER_W, PLACEHOLDER_R)
    print(f"\nhalf-Kelly on the placeholders (W=0.55 R=1.5): {placeholder:.3f}")
    edge_report("all closed positions", pnls)
    # The 60-share TNE row is the remnant of the 24 Aug duplicate-transmission
    # unwind (CE-003), not a swing outcome. Shown without it so the result does
    # not rest on an artefact.
    tne = [p for p, s in zip(pnls, symbols, strict=True) if s != "TNE.AX"]
    edge_report("without the TNE remnant", tne)

    last = max(closes).date()
    days = weekdays(date(2026, 8, 25), last)
    rate = len(positions) / days
    print(f"\nclosed positions {len(positions)} over {days} weekdays (25 Aug - {last:%d %b})")
    print(f"first close {min(closes):%d %b}; {rate:.2f} a day")
    for need, label in (
        (EDGE_MIN_TRADES, "measured Kelly inputs"),
        (PROMOTION_TRADES, "promotion bar"),
    ):
        more = need - len(positions)
        days_more = more / rate
        print(f"{label}: {need} needed, {more} more; ~{days_more:.0f} trading days at that rate")


def edge_report(label: str, pnls: list[float]) -> None:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    w = len(wins) / len(pnls)
    avg_win, avg_loss = fmean(wins), abs(fmean(losses))
    r = avg_win / avg_loss
    w_c, r_c = min(max(w, 0.25), 0.75), min(max(r, 0.5), 4.0)
    f_now = kelly(w_c, r_c)
    print(f"-- {label}: {len(wins)} wins of {len(pnls)} ({w:.1%})")
    print(f"   avg win {avg_win:,.2f}, avg loss {avg_loss:,.2f}, ratio {r:.2f}")
    print(f"   clamped W={w_c:.3f} R={r_c:.2f}; half-Kelly {f_now:.3f} of equity")
    print(f"   half-Kelly turns positive above a {1 / (1 + r_c):.1%} win rate at this ratio")
    if f_now == 0:
        print(
            "   -> zero: entries would be refused 'Sizing produced zero shares' (engine.py:205-208)"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
