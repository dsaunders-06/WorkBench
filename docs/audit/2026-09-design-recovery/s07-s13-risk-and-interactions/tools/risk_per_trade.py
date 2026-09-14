"""Audit, brief §7: how much risk each entry actually took, and which trim set it.

Read-only. Reads risk_decisions.csv and decision_journal.csv; writes nothing.

    python risk_per_trade.py <data_dir>

For every BUY the OMS proposed (journal outcome "proposed"), it finds the risk
engine's approval for the same symbol just before it and reports:

* the per-trade budget, 1% of equity (settings.per_trade_risk_pct);
* the sizer's three terms, rebuilt from the recorded inputs:
    Kelly   = 0.5 x (W - (1-W)/R) x equity / price, at W=0.55 R=1.5
              (placeholders until 20 closed trades - edge.py; the estimate
              in force is not recorded, so a measured edge would show here
              as a mismatch against the approved share count)
    ATR cap = 1% x equity / (2.5 x ATR)
    budget  = 1% x equity / stop_distance (engine.py:229-232)
  For swing the strategy stop IS 2.5 x ATR (swing.py:164), so the ATR cap and
  the budget coincide and ATR is recovered as stop_distance / 2.5;
* the regime scalar and earnings scalar applied (engine.py:234);
* the engine's approved shares (after cash rule and governor);
* the OMS's proposed quantity, after flooring and the 10%-of-spendable-cash
  cap (oms.py:430-519), which is recorded only in the journal and the log;
* risk taken = proposed quantity x stop_distance, as a % of equity.

Run it from PowerShell (HANDOFF, "THE ONE RULE").
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
W, R, KELLY_FRACTION = 0.55, 1.5, 0.5
PCT = 0.01
MATCH_WINDOW = timedelta(seconds=10)


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def main(data_dir: Path) -> None:
    risk = list(
        csv.DictReader((data_dir / "risk_decisions.csv").open(newline="", encoding="utf-8"))
    )
    journal = list(
        csv.DictReader((data_dir / "decision_journal.csv").open(newline="", encoding="utf-8"))
    )
    approved = [
        r for r in risk if r["approved"] == "True" and json.loads(r["inputs"]).get("side") == "buy"
    ]

    kelly_f = KELLY_FRACTION * max(0.0, W - (1 - W) / R)
    head = (
        "AEST time        symbol   price   equity    stopD  kellySh  budgetSh  bind   regime earn "
        "engineSh  omsQty  eng%   oms%   of1%  gov  aggBefore cnt  outcome"
    )
    print(head)
    print("-" * len(head))
    summary = []
    for j in journal:
        if j["outcome"] != "proposed" or j["side"] != "buy":
            continue
        t = ts(j["timestamp"])
        cands = [
            r
            for r in approved
            if r["symbol"] == j["symbol"] and timedelta(0) <= t - ts(r["timestamp"]) <= MATCH_WINDOW
        ]
        if not cands:
            print(f"{t.astimezone(AEST):%m-%d %H:%M:%S}  {j['symbol']:8s} NO MATCHING APPROVAL")
            continue
        r = max(cands, key=lambda x: x["timestamp"])
        inp = json.loads(r["inputs"])
        price, equity = float(inp["price"]), float(inp["equity"])
        stop_d = float(inp["stop_distance"])
        kelly_sh = kelly_f * equity / price
        budget_sh = PCT * equity / stop_d
        bind = "kelly" if kelly_sh < budget_sh else "1%"
        regime = inp.get("regime_scalar")
        earn = inp.get("earnings_event_scalar")
        eng_sh = float(r["final_shares"])
        oms_qty = float(j["quantity"])
        eng_pct = eng_sh * stop_d / equity
        oms_pct = oms_qty * stop_d / equity
        gov = inp.get("governor", {})
        agg = gov.get("aggregate_risk_pct")
        cnt = gov.get("position_count")
        # NOT by order_id: once IBKR assigns its own id, the OMS re-keys the
        # order (oms.py:1102-1103) and the journal's sign-off rows carry the
        # BROKER's id, not the proposal's. Joining on the id reported five
        # transmitted entries as never signed (CE-029). Match instead on the
        # same symbol, side and quantity, after this proposal and before the
        # symbol's next one.
        nxt = min(
            (
                ts(k["timestamp"])
                for k in journal
                if k["symbol"] == j["symbol"]
                and k["outcome"] == "proposed"
                and ts(k["timestamp"]) > t
            ),
            default=datetime.max.replace(tzinfo=UTC),
        )
        later = [
            k["outcome"]
            for k in journal
            if k["symbol"] == j["symbol"]
            and k["side"] == "buy"
            and k["quantity"] == j["quantity"]
            and t <= ts(k["timestamp"]) < nxt
            and k["outcome"] != "proposed"
        ]
        flags = "".join(
            c
            for c, k in (
                ("S", "resized_for_stop_budget"),
                ("C", "resized_for_cash"),
                ("G", "resized_by_governor"),
            )
            if inp.get(k)
        )
        print(
            f"{t.astimezone(AEST):%m-%d %H:%M:%S}  {j['symbol']:8s} {price:7.3f} {equity:9.0f} "
            f"{stop_d:7.4f} {kelly_sh:8.0f} {budget_sh:9.0f}  {bind:5s}  {regime!s:6s} {earn!s:4s} "
            f"{eng_sh:8.0f} {oms_qty:7.0f} {eng_pct:5.2%} {oms_pct:6.2%} "
            f"{oms_pct / PCT:5.0%}  {flags or '-':3s} "
            f"{'' if agg is None else f'{agg:6.2%}':>9s} "
            f"{'' if cnt is None else int(cnt):>3}  {','.join(later) or '-'}"
        )
        summary.append((j["symbol"], t, oms_pct, eng_pct, bind, "signed_off" in later))

    sent = [s for s in summary if s[5]]
    symbol_days = {(s[0], s[1].astimezone(AEST).date()) for s in summary}
    print(f"\nproposed buys: {len(summary)} ({len(symbol_days)} symbol-days)")
    print(f"transmitted (signed_off at least once): {len(sent)} proposals")
    if sent:
        vals = sorted(s[2] for s in sent)
        print(
            f"risk taken at the OMS quantity, transmitted proposals: min {vals[0]:.2%}  "
            f"median {vals[len(vals) // 2]:.2%}  max {vals[-1]:.2%}  (budget 1.00%)"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
