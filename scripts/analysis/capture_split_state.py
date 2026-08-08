"""Capture one symbol's position and resting orders, so before and after a
corporate action can be compared.

Read-only: places, cancels and modifies nothing.

The measurement M39 is blocked on is what Alpaca does to a HELD QUANTITY and to
a RESTING OCO through a split. Neither is recoverable after the fact - once the
split has happened, the pre-split state is gone unless something wrote it down.
So run this before the ex-date and again after, and diff the two.

    python scripts/analysis/capture_split_state.py MNST before
    python scripts/analysis/capture_split_state.py MNST after

Writes a timestamped JSON beside itself and prints a human summary.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from alpaca.trading.client import TradingClient  # noqa: E402
from alpaca.trading.enums import CorporateActionType  # noqa: E402
from alpaca.trading.requests import (  # noqa: E402
    GetCorporateAnnouncementsRequest,
    GetOrdersRequest,
)

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "split-captures"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    symbol = sys.argv[1].upper()
    label = sys.argv[2]

    client = TradingClient(
        api_key=get_secret(API_KEY_SECRET_NAME),
        secret_key=get_secret(SECRET_KEY_SECRET_NAME),
        paper=True,
    )

    position = None
    for pos in client.get_all_positions():
        if pos.symbol == symbol:
            position = {
                "qty": float(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
            }

    # status=all with nested=True, per ROADMAP: a protective leg is only
    # returned when its parent is, and `status=open` drops a filled parent's
    # still-live legs entirely.
    orders = []
    for order in client.get_orders(
        GetOrdersRequest(status="all", nested=True, symbols=[symbol], limit=100)
    ):
        orders.append(
            {
                "id": str(order.id),
                "side": order.side.value,
                "type": order.order_type.value,
                "qty": None if order.qty is None else float(order.qty),
                "stop_price": None if order.stop_price is None else float(order.stop_price),
                "limit_price": None if order.limit_price is None else float(order.limit_price),
                "status": order.status.value,
                "time_in_force": order.time_in_force.value,
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
                "legs": [
                    {
                        "id": str(leg.id),
                        "side": leg.side.value,
                        "type": leg.order_type.value,
                        "qty": None if leg.qty is None else float(leg.qty),
                        "stop_price": None if leg.stop_price is None else float(leg.stop_price),
                        "limit_price": None if leg.limit_price is None else float(leg.limit_price),
                        "status": leg.status.value,
                    }
                    for leg in (getattr(order, "legs", None) or [])
                ],
            }
        )

    announcements = []
    today = datetime.now(UTC).date()
    from datetime import timedelta

    # Windows reach FORWARD as well as back. The announcement for an upcoming
    # split carries a future ex_date and falls outside a backward-only window -
    # a capture taken before the event would then show no split at all, which is
    # exactly the moment the record matters most. Found by running this against
    # MNST, whose 11 August ex-date the first version silently missed.
    for until in (today + timedelta(days=60), today, today - timedelta(weeks=12)):
        try:
            found = client.get_corporate_announcements(
                GetCorporateAnnouncementsRequest(
                    ca_types=[CorporateActionType.SPLIT],
                    since=until - timedelta(days=88),
                    until=until,
                    symbol=symbol,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a capture reports its failures
            announcements.append({"query_failed": f"{type(exc).__name__}: {exc}"})
            continue
        for ann in found:
            announcements.append(
                {
                    "sub_type": getattr(ann.ca_sub_type, "value", str(ann.ca_sub_type)),
                    "old_rate": float(ann.old_rate),
                    "new_rate": float(ann.new_rate),
                    "ratio": float(ann.new_rate) / float(ann.old_rate),
                    "ex_date": str(ann.ex_date),
                    "record_date": str(ann.record_date),
                    "payable_date": str(ann.payable_date),
                }
            )

    payload = {
        "symbol": symbol,
        "label": label,
        "captured_at": datetime.now(UTC).isoformat(),
        "position": position,
        "orders": orders,
        "split_announcements": announcements,
    }

    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = OUT_DIR / f"{symbol}-{label}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"{symbol}  ({label})   -> {path.name}")
    print("-" * 68)
    if position is None:
        print("  POSITION: none held")
    else:
        print(
            f"  POSITION: qty={position['qty']:g}  avg_entry={position['avg_entry_price']:.4f}"
            f"  current={position['current_price']:.4f}"
            f"  value={position['market_value']:.2f}"
        )
    live = [o for o in orders if o["status"] in {"new", "held", "accepted", "partially_filled"}]
    print(f"  ORDERS: {len(orders)} total, {len(live)} live")
    for order in live:
        print(
            f"    {order['side']:<4} {order['type']:<6} qty={order['qty']} "
            f"stop={order['stop_price']} limit={order['limit_price']} "
            f"status={order['status']} tif={order['time_in_force']}"
        )
        for leg in order["legs"]:
            print(
                f"      leg: {leg['side']:<4} {leg['type']:<6} qty={leg['qty']} "
                f"stop={leg['stop_price']} limit={leg['limit_price']} status={leg['status']}"
            )
    for ann in announcements:
        print(f"  SPLIT: {ann}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
