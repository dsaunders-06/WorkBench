"""Is the flat 5 bps slippage assumption right? Read-only.

M44 plans to answer this from `entry_slippage` once there are enough closed
trades, which means September. But entry slippage does not need a trade to
CLOSE - it needs one to OPEN. The decision journal records the reference price
at sign-off, the broker records what actually filled, and both carry the order
id. That is measurable today.

It matters because the cost rail is the tightest constraint on trade quality in
this system - the largest non-capacity refusal and the tightest binding rail on
trades that pass - and it is calibrated on this constant. If realised slippage
runs above 5 bps, that rail is permissive in the direction that lets uneconomic
trades through.

Sign convention: POSITIVE bps is adverse. A buy that filled above its reference
price and a sell that filled below it both cost money.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import requests

sys.path.insert(0, r"C:\Claude Programming\src")

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

# The ARCHIVE, not the live directory (21 August 2026). Every transmitted order
# this script measures happened on Alpaca, and those journal rows were retired
# out of the app's live record that evening - the live file now holds six ASX
# rows, all rejected, and will never again contain an Alpaca fill. Pointing at
# the live path would return an empty result that looks like "no slippage"
# rather than "no data", which is the distinction this project keeps having to
# relearn.
#
# ⚠️ THE OTHER HALF OF THIS SCRIPT IS ALREADY DEAD. `broker_fills()` calls the
# Alpaca paper API live, and that account is finished. Re-running this needs the
# fills captured alongside the journal, or the comparison rebuilt against IBKR
# executions once M44 has ASX trades to measure.
JOURNAL = (
    Path(__file__).resolve().parents[2] / "docs" / "archive" / "alpaca-era" / "decision_journal.csv"
)
TRANSMITTED = {"signed_off", "auto_signed"}
ASSUMED_BPS = 5.0


def journal_reference_prices() -> dict[str, dict[str, str]]:
    """Reference price per order id, at the moment it was signed off."""
    with JOURNAL.open(newline="", encoding="utf-8") as handle:
        return {
            row["order_id"]: row
            for row in csv.DictReader(handle)
            if row.get("outcome") in TRANSMITTED and row.get("price")
        }


def broker_fills() -> list[dict]:
    headers = {
        "APCA-API-KEY-ID": get_secret(API_KEY_SECRET_NAME),
        "APCA-API-SECRET-KEY": get_secret(SECRET_KEY_SECRET_NAME),
    }
    response = requests.get(
        "https://paper-api.alpaca.markets/v2/account/activities/FILL",
        headers=headers,
        params={"page_size": 100},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    references = journal_reference_prices()
    fills = broker_fills()
    print(f"journal rows transmitted: {len(references)}    broker fills: {len(fills)}\n")

    # Aggregate by ORDER, not by fill. A partially filling order reports one
    # activity row per piece, so counting rows would weight a single order that
    # filled in four pieces four times over - which is exactly what CVS and AMD
    # do here. One order is one decision and therefore one observation, and its
    # price is the volume-weighted average of its pieces.
    per_order: dict[str, dict] = {}
    for fill in fills:
        order_id = fill.get("order_id", "")
        row = references.get(order_id)
        if row is None:
            continue
        try:
            reference = float(row["price"])
            price, qty = float(fill["price"]), float(fill["qty"])
        except (TypeError, ValueError):
            continue
        if reference <= 0 or qty <= 0:
            continue
        agg = per_order.setdefault(
            order_id,
            {
                "symbol": fill["symbol"],
                "side": fill["side"],
                "reference": reference,
                "value": 0.0,
                "qty": 0.0,
                "pieces": 0,
            },
        )
        agg["value"] += price * qty
        agg["qty"] += qty
        agg["pieces"] += 1
        stamp = fill.get("transaction_time", "")
        if stamp and (agg.get("at") is None or stamp < agg["at"]):
            agg["at"] = stamp

    matched: list[tuple[str, str, float, float, float, int, float]] = []
    for agg in per_order.values():
        filled = agg["value"] / agg["qty"]
        reference = agg["reference"]
        raw_bps = (filled - reference) / reference * 10_000
        # Adverse is positive for both sides: a buy pays more, a sell receives
        # less. Without this the two halves cancel and the mean reads ~0.
        adverse = raw_bps if agg["side"].startswith("buy") else -raw_bps
        matched.append(
            (agg["symbol"], agg["side"], reference, filled, adverse, agg["pieces"], agg["value"])
        )

    if not matched:
        print("No fills matched a journal reference price.")
        print("The journal records the broker's order id only once an order is")
        print("transmitted - if these do not line up, that is the finding.")
        return 1

    print(
        f"{'sym':<7}{'side':<6}{'reference':>11}{'vwap fill':>11}{'adverse bps':>13}{'pieces':>8}"
    )
    print("-" * 56)
    for symbol, side, reference, filled, adverse, pieces, _value in sorted(
        matched, key=lambda m: -m[4]
    ):
        print(
            f"{symbol:<7}{side:<6}{reference:>11.2f}{filled:>11.2f}" f"{adverse:>13.1f}{pieces:>8}"
        )

    values = sorted(m[4] for m in matched)
    notional = sum(m[6] for m in matched)
    # The cost model charges bps ON NOTIONAL, so this is what slippage actually
    # cost - as distinct from what a typical trade experienced.
    weighted = sum(m[4] * m[6] for m in matched) / notional if notional else 0.0
    print("-" * 56)
    print(f"  orders                    {len(values)}")
    print(f"  median adverse bps        {statistics.median(values):+.2f}   <- typical trade")
    print(f"  notional-weighted bps     {weighted:+.2f}   <- what it cost")
    print(f"  mean adverse bps          {statistics.fmean(values):+.2f}")
    print(f"  worst / best              {max(values):+.2f} / {min(values):+.2f}")
    print(f"  assumed by the cost model {ASSUMED_BPS:+.2f}")
    print()
    print(
        f"  Typical trade: {'ABOVE' if statistics.median(values) > ASSUMED_BPS else 'at or below'}"
        f" the {ASSUMED_BPS:g} bps charged."
    )
    print(
        f"  Cost-weighted: {'ABOVE' if weighted > ASSUMED_BPS else 'at or below'}"
        f" the {ASSUMED_BPS:g} bps charged."
    )
    if len(values) < 20:
        print()
        print(f"  {len(values)} orders is a small sample - enough to see a gross error,")
        print("  not enough to re-tune a constant on.")

    # M44's stated suspicion: "market orders in the opening minutes are exactly
    # where that assumption is weakest". The fills carry timestamps, so it is
    # checkable rather than merely plausible.
    print()
    print("=" * 56)
    print("BY MINUTES AFTER THE OPEN (US regular session opens 13:30 UTC)")
    print("=" * 56)
    print(f"  {'sym':<7}{'minutes in':>12}{'adverse bps':>14}")
    timed = []
    for symbol, _side, _ref, _fill, adverse, _pieces, _value in matched:
        agg = next(a for a in per_order.values() if a["symbol"] == symbol and a.get("at"))
        stamp = agg["at"]
        try:
            hh, mm = int(stamp[11:13]), int(stamp[14:16])
        except (ValueError, IndexError):
            continue
        minutes = (hh * 60 + mm) - (13 * 60 + 30)
        timed.append((minutes, symbol, adverse))
    for minutes, symbol, adverse in sorted(timed):
        marker = "  <- opening 30 min" if 0 <= minutes <= 30 else ""
        print(f"  {symbol:<7}{minutes:>12}{adverse:>14.1f}{marker}")

    opening = [a for m, _s, a in timed if 0 <= m <= 30]
    later = [a for m, _s, a in timed if m > 30]
    if opening and later:
        print()
        print(
            f"  first 30 minutes : median {statistics.median(opening):+.1f} bps  (n={len(opening)})"
        )
        print(f"  after that       : median {statistics.median(later):+.1f} bps  (n={len(later)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
