"""Audit, brief §11: the application's records against the broker's.

Read-only. Reads an IBKR activity statement's text and the data folder's
closed_trades.csv and open_position_entries.json; writes nothing.

    python ledger_vs_broker.py <statement.txt> <data_dir>

<statement.txt> is the statement PDF converted with `pdftotext -raw` into the
session's scratchpad. The statement itself is never committed (it carries
personal details, HANDOFF standing instruction 8), and neither is its text.

Sections:
  1. every execution on the statement's Trades table, checked against the
     table's own totals (so a parse slip cannot pass unnoticed);
  2. each ledger position (rows grouped by symbol and opening time) beside the
     broker executions that opened and closed it: quantity, prices, costs
     against commission, and net P&L against the broker's realised P&L;
  3. broker round trips with no ledger position, and ledger rows with no
     broker execution;
  4. the open positions: the app's entry record against the broker's buy;
  5. the blank fields in the ledger and in the open entry records.

Run from PowerShell (HANDOFF, "THE ONE RULE").
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
NUM = r"-?[\d,]+(?:\.\d+)?"
# One execution. The trade price can wrap onto the next line in the PDF text
# (COH: "135.73603305" then "8 137.5800 ..."), which joins as "135.73603305 8";
# the optional group re-attaches those digits.
EXEC = re.compile(
    rf"DUQ\d+ (?P<sym>[A-Z0-9]+) (?P<date>\d{{4}}-\d{{2}}-\d{{2}}), (?P<time>\d\d:\d\d:\d\d) "
    rf"(?P<qty>{NUM}) (?P<price>\d+\.\d+)(?: (?P<wrap>\d+)(?= \d+\.\d))? (?P<close>\d+\.\d+) "
    rf"(?P<proceeds>{NUM}) (?P<comm>{NUM}) (?P<basis>{NUM}) (?P<realized>{NUM}) "
    rf"(?P<mtm>{NUM}) (?P<code>[A-Z;]+)"
)
TOTAL = re.compile(
    rf"^Total (?P<proceeds>{NUM}) (?P<comm>{NUM}) (?P<basis>{NUM}) (?P<realized>{NUM})"
)
SYMBOL_TOTAL = re.compile(
    rf"^Total (?P<sym>[A-Z0-9]+) (?P<qty>{NUM}) (?P<proceeds>{NUM}) (?P<comm>{NUM}) "
    rf"(?P<basis>{NUM}) (?P<realized>{NUM})"
)
NOISE = ("DEMO ACCOUNT", "Activity Summary", "Trades", "Total ")


def num(text: str) -> float:
    return float(text.replace(",", ""))


def read_executions(statement: Path) -> list[dict]:
    lines = statement.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "Trades")
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("Transaction Fees"))
    section = lines[start:end]
    grand = next(TOTAL.match(line) for line in section if TOTAL.match(line))
    body = " ".join(line.strip() for line in section if not line.startswith(NOISE))
    execs = []
    for m in EXEC.finditer(body):
        price = m["price"] + (m["wrap"] or "")
        stamp = datetime.fromisoformat(f"{m['date']}T{m['time']}").replace(tzinfo=AEST)
        execs.append(
            {
                "symbol": f"{m['sym']}.AX",
                "ts": stamp,
                "qty": num(m["qty"]),
                "price": float(price),
                "comm": -num(m["comm"]),
                "realized": num(m["realized"]),
                "code": m["code"],
            }
        )
    comm, realized = sum(e["comm"] for e in execs), sum(e["realized"] for e in execs)
    print("=== 1. BROKER EXECUTIONS (statement Trades table) ===")
    table_comm, table_realized = -num(grand["comm"]), num(grand["realized"])
    print(
        f"parsed {len(execs)} executions; commission {comm:,.2f} against the table's "
        f"{table_comm:,.2f}; realised {realized:,.2f} against {table_realized:,.2f}"
    )
    # Each row is printed rounded to the cent and each total is computed from
    # unrounded values, so a sum of rows may miss a total by up to half a cent
    # per row. Anything wider is a row the parse did not find.
    ok = True
    for line in section:
        if not (t := SYMBOL_TOTAL.match(line)):
            continue
        rows = [e for e in execs if e["symbol"] == f"{t['sym']}.AX"]
        slack = 0.005 * len(rows) + 0.001
        qty_ok = abs(sum(e["qty"] for e in rows) - num(t["qty"])) < 0.5
        comm_ok = abs(sum(e["comm"] for e in rows) + num(t["comm"])) <= slack
        real_ok = abs(sum(e["realized"] for e in rows) - num(t["realized"])) <= slack
        if not (rows and qty_ok and comm_ok and real_ok):
            ok = False
            print(f"  MISMATCH against 'Total {t['sym']}': {line.strip()}")
    grand_ok = abs(comm + num(grand["comm"])) <= 0.005 * len(execs) + 0.001
    print(
        "per-symbol totals and grand total reconcile within rounding: "
        + ("YES" if ok and grand_ok else "NO - THE PARSE IS INCOMPLETE; STOP")
    )
    for e in execs:
        side = "buy " if e["qty"] > 0 else "sell"
        print(
            f"  {e['ts']:%d %b %H:%M:%S} {e['symbol']:7s} {side} {abs(e['qty']):>9,.0f} "
            f"@ {e['price']:<14} comm {e['comm']:7.2f} realised {e['realized']:10,.2f} {e['code']}"
        )
    print()
    return execs


def near(a: datetime, b: datetime, seconds: float = 90) -> bool:
    return abs((a - b).total_seconds()) <= seconds


def compare_ledger(execs: list[dict], data: Path) -> None:
    rows = list(csv.DictReader((data / "closed_trades.csv").open(encoding="utf-8", newline="")))
    positions: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        positions[(r["symbol"], r["opened_at"])].append(r)
    used: set[int] = set()
    print("=== 2. LEDGER POSITIONS AGAINST THE BROKER ===")
    print(f"closed_trades.csv: {len(rows)} rows, {len(positions)} positions")
    ledger_net = broker_net = 0.0
    for (symbol, opened), group in positions.items():
        qty = sum(float(r["quantity"]) for r in group)
        entry = sum(float(r["entry_price"]) * float(r["quantity"]) for r in group) / qty
        exit_ = sum(float(r["exit_price"]) * float(r["quantity"]) for r in group) / qty
        costs = sum(float(r["entry_cost"]) + float(r["exit_cost"]) for r in group)
        net = sum(float(r["net_pnl"]) for r in group)
        opened_at = datetime.fromisoformat(opened).astimezone(AEST)
        closed_at = max(datetime.fromisoformat(r["closed_at"]) for r in group).astimezone(AEST)
        buy = next(
            (
                (i, e)
                for i, e in enumerate(execs)
                if e["symbol"] == symbol and e["qty"] > 0 and near(e["ts"], opened_at)
            ),
            None,
        )
        sell = next(
            (
                (i, e)
                for i, e in enumerate(execs)
                if e["symbol"] == symbol and e["qty"] < 0 and near(e["ts"], closed_at, 600)
            ),
            None,
        )
        ledger_net += net
        print(
            f"{symbol:7s} ledger: {len(group)} row(s) qty {qty:,.0f} entry {entry:.6f} exit "
            f"{exit_:.6f} costs {costs:,.2f} net {net:,.2f} ({opened_at:%d %b %H:%M} -> "
            f"{closed_at:%d %b %H:%M})"
        )
        for label, hit in (("buy ", buy), ("sell", sell)):
            if hit is None:
                print(f"         broker {label}: NONE within the window")
                continue
            used.add(hit[0])
            e = hit[1]
            print(
                f"         broker {label}: qty {abs(e['qty']):,.0f} @ {e['price']:.6f} "
                f"comm {e['comm']:.2f} at {e['ts']:%d %b %H:%M:%S}"
            )
        if buy and sell:
            b, s = buy[1], sell[1]
            realised = s["realized"]
            broker_net += realised
            comm = b["comm"] + s["comm"]
            flags = []
            if abs(abs(s["qty"]) - qty) > 0.5:
                flags.append(f"QTY ledger {qty:,.0f} vs broker {abs(s['qty']):,.0f}")
            if abs(b["price"] - entry) > 0.0005:
                flags.append(f"ENTRY {entry:.6f} vs {b['price']:.6f}")
            if abs(s["price"] - exit_) > 0.0005:
                flags.append(f"EXIT {exit_:.6f} vs {s['price']:.6f}")
            flags.append(f"costs {costs:,.2f} vs commission {comm:,.2f} ({costs - comm:+,.2f})")
            flags.append(f"net {net:,.2f} vs realised {realised:,.2f} ({net - realised:+,.2f})")
            print("         -> " + "; ".join(flags))
    print(f"ledger net total {ledger_net:,.2f}; broker realised on the matched sells ", end="")
    print(f"{broker_net:,.2f}")
    print()

    print("=== 3. BROKER EXECUTIONS WITH NO LEDGER POSITION ===")
    loose = [e for i, e in enumerate(execs) if i not in used]
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for e in loose:
        by_symbol[e["symbol"]].append(e)
    for symbol, group in by_symbol.items():
        net_qty = sum(e["qty"] for e in group)
        realised = sum(e["realized"] for e in group)
        state = "still held" if net_qty else "round trip"
        print(
            f"{symbol:7s} {len(group)} execution(s), net qty {net_qty:,.0f} ({state}); "
            f"realised {realised:,.2f}; commission {sum(e['comm'] for e in group):,.2f}"
        )
    print()


def compare_open(execs: list[dict], data: Path) -> None:
    print("=== 4. OPEN POSITIONS: THE APP'S ENTRY RECORD AGAINST THE BROKER'S BUY ===")
    entries = json.loads((data / "open_position_entries.json").read_text(encoding="utf-8"))
    for symbol, rec in entries.items():
        opened = datetime.fromisoformat(rec["opened_at"]).astimezone(AEST)
        buy = next(
            (e for e in execs if e["symbol"] == symbol and e["qty"] > 0 and near(e["ts"], opened)),
            None,
        )
        broker = f"broker {buy['qty']:,.0f} @ {buy['price']:.6f}" if buy else "broker: NONE"
        diff = f" (diff {rec['price'] - buy['price']:+.6f})" if buy else ""
        print(
            f"{symbol:7s} app {rec['price']:.6f} source {rec.get('price_source')!s:9s} "
            f"ref {rec.get('reference_price')!s:18.18s} | {broker}{diff}"
        )


def blank_fields(data: Path) -> None:
    print()
    print("=== 5. BLANK FIELDS (the ledger's rows; the open entry records) ===")
    with (data / "closed_trades.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    counts = {k: sum(1 for r in rows if not (r.get(k) or "").strip()) for k in rows[0]}
    print(
        f"closed_trades.csv, {len(rows)} rows: "
        + ", ".join(f"{k} {n}" for k, n in counts.items() if n)
    )
    entries = json.loads((data / "open_position_entries.json").read_text(encoding="utf-8"))
    for field in ("price_source", "reference_price", "stop_price", "strategy"):
        missing = sorted(s for s, rec in entries.items() if rec.get(field) in (None, ""))
        print(f"open records, {len(entries)}: {field} blank on {len(missing)} {missing}")


def main(statement: Path, data: Path) -> None:
    execs = read_executions(statement)
    compare_ledger(execs, data)
    compare_open(execs, data)
    blank_fields(data)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
