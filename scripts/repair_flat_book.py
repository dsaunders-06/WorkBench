"""Evidence-bound flat-book store repair; dry run unless --apply is supplied.

Private inventory, plan and report files must stay outside Git. This script
never contacts a broker; a separate read-only client proves the flat book.
Live-store application requires a separate DS instruction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from qat.domain.performance.trades import _FIELDS, ClosedTrade  # noqa: E402

STORE_FILES = (
    "open_position_entries.json",
    "exit_recovery.json",
    "inflight_orders.json",
    "closed_trades.csv",
    "ib_pending_legs.json",
)
COMMISSION = re.compile(r"commission=([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
REALIZED_PNL = re.compile(r"realizedPNL=([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
SYDNEY = ZoneInfo("Australia/Sydney")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()


def object_from(data: bytes) -> dict[str, Any]:
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("store must be a JSON object")
    return result


def require_outside_git(path: Path) -> None:
    target = path.expanduser().resolve()
    if any((parent / ".git").exists() for parent in (target, *target.parents)):
        raise ValueError(f"private evidence must stay outside Git: {target}")


def require_flat(inventory: dict[str, Any], account: str) -> None:
    if inventory.get("error") or inventory.get("read_only") is not True:
        raise ValueError("independent read-only inventory unavailable")
    if inventory.get("account") != account or not account.startswith("DU"):
        raise ValueError("independent inventory account differs from paper account")
    methods = {row.get("method") for row in inventory.get("requests", [])}
    if not {"reqPositionsAsync", "reqAllOpenOrdersAsync", "reqExecutionsAsync"} <= methods:
        raise ValueError("independent inventory omitted a required broker request")
    for key in ("positions_callbacks", "positions_cache"):
        rows = inventory.get(key)
        if not isinstance(rows, list):
            raise ValueError(f"independent broker book is not flat: {key}")
        for row in rows:
            if not isinstance(row, dict) or row.get("account") != account:
                raise ValueError(f"independent broker book is not flat: {key}")
            quantity = float(row.get("quantity", float("nan")))
            if not math.isfinite(quantity) or abs(quantity) > 1e-6:
                raise ValueError(f"independent broker book is not flat: {key}")
    if inventory.get("all_open_orders") != []:
        raise ValueError("independent broker book is not flat: all_open_orders")


def manual_sell(
    inventory: dict[str, Any], spec: dict[str, Any], quantity: float
) -> tuple[float, float, float, datetime]:
    selected = [
        row
        for row in inventory.get("executions", [])
        if int(row.get("perm_id", 0)) == int(spec["manual_sell_perm_id"])
    ]
    expected = set(spec["execution_ids"])
    if (
        not selected
        or len(selected) != len(expected)
        or {row.get("exec_id") for row in selected} != expected
    ):
        raise ValueError("manual sell execution identities differ from private plan")
    total = notional = commission = realized_pnl = 0.0
    latest: datetime | None = None
    symbol = spec["close_symbol"].removesuffix(".AX")
    for row in selected:
        if (
            row.get("account") != spec["account"]
            or row.get("symbol") not in {symbol, spec["close_symbol"]}
            or row.get("side") not in {"SLD", "SELL"}
        ):
            raise ValueError("manual sell account, symbol or side differs")
        shares, price = float(row["quantity"]), float(row["price"])
        if not all(math.isfinite(x) and x > 0 for x in (shares, price)):
            raise ValueError("manual sell quantity or price invalid")
        stamp = datetime.fromisoformat(row["execution_time_utc"])
        if (
            stamp.tzinfo is None
            or stamp.astimezone(SYDNEY).date().isoformat() != spec["session_date"]
        ):
            raise ValueError("manual sell is outside the planned Sydney session")
        match = COMMISSION.search(str(row.get("commission", "")))
        pnl_match = REALIZED_PNL.search(str(row.get("commission", "")))
        if match is None or pnl_match is None:
            raise ValueError("manual sell commission or broker realized P&L unavailable")
        charge = float(match.group(1))
        pnl = float(pnl_match.group(1))
        if (
            not math.isfinite(charge)
            or charge < 0
            or charge > shares * price
            or not math.isfinite(pnl)
        ):
            raise ValueError("manual sell commission invalid")
        total += shares
        notional += shares * price
        commission += charge
        realized_pnl += pnl
        latest = stamp if latest is None or stamp > latest else latest
    if not math.isclose(total, quantity, abs_tol=1e-6):
        raise ValueError("manual sell does not close the recorded lot")
    assert latest is not None
    return notional / total, commission, realized_pnl, latest


@dataclass(frozen=True)
class PlannedRepair:
    data_dir: Path
    updates: dict[str, bytes]
    before_hashes: dict[str, str]
    after_hashes: dict[str, str]
    before_records: dict[str, Any]
    after_records: dict[str, Any]


def plan_repair(data_dir: Path, inventory: dict[str, Any], spec: dict[str, Any]) -> PlannedRepair:
    """Prove all preconditions and derive the exact new bytes without writing."""
    data_dir = data_dir.expanduser().resolve()
    require_flat(inventory, str(spec["account"]))
    if set(spec.get("expected_sha256", {})) != set(STORE_FILES):
        raise ValueError("private plan must pin every source store hash")
    source: dict[str, bytes] = {}
    before: dict[str, str] = {}
    for name in STORE_FILES:
        path = data_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"store missing or linked: {name}")
        content = path.read_bytes()
        if sha(content) != spec["expected_sha256"][name]:
            raise ValueError(f"store hash differs from private plan: {name}")
        source[name], before[name] = content, sha(content)
    entries = object_from(source["open_position_entries.json"])
    recovery = object_from(source["exit_recovery.json"])
    inflight = object_from(source["inflight_orders.json"])
    pending = object_from(source["ib_pending_legs.json"])
    symbol = str(spec["close_symbol"])
    old_symbol = str(spec["existing_closed_symbol"])
    old_id = str(spec["stale_inflight_app_order_id"])
    orders = inflight.get("orders")
    if set(entries) != {symbol} or set(recovery) != {symbol}:
        raise ValueError("entry or recovery set differs from private plan")
    if not isinstance(orders, dict) or set(orders) != {old_id}:
        raise ValueError("in-flight set differs from private plan")
    entry, plan, stale = entries[symbol], recovery[symbol], orders[old_id]
    quantity = float(entry["quantity"])
    if (
        quantity <= 0
        or plan.get("symbol") != symbol
        or plan.get("stage") != "prepared"
        or float(plan.get("quantity", 0)) != quantity
        or stale.get("stage") != "accepted"
        or stale.get("order", {}).get("symbol") != old_symbol
        or stale.get("order", {}).get("side") != "sell"
        or stale.get("order", {}).get("order_type") != "stop"
        or stale.get("order", {}).get("status") != "transmitted"
    ):
        raise ValueError("entry, prepared recovery or stale stop differs")
    legs = [
        leg
        for leg in pending.get("legs", [])
        if leg.get("app_order_id") == old_id
        and leg.get("symbol") == old_symbol
        and leg.get("broker_order_id") == spec["stale_broker_order_id"]
        and leg.get("perm_id") == spec["stale_perm_id"]
        and leg.get("resolved") is True
    ]
    if len(legs) != 1:
        raise ValueError("stale stop identity is not proved by pending legs")
    with io.StringIO(source["closed_trades.csv"].decode(), newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(_FIELDS):
            raise ValueError("closed-trade ledger schema differs")
        rows = list(reader)
    old_close = [
        row
        for row in rows
        if row["symbol"] == old_symbol and row["order_id"] == spec["existing_close_order_id"]
    ]
    if len(old_close) != 1:
        raise ValueError("existing close must be preserved exactly once")
    if not math.isclose(
        float(stale["order"]["quantity"]), float(old_close[0]["quantity"]), abs_tol=1e-6
    ):
        raise ValueError("stale stop does not match existing close quantity")
    if any(row["order_id"] == str(spec["manual_sell_perm_id"]) for row in rows):
        raise ValueError("manual close already recorded")
    price, exit_cost, broker_realized_pnl, closed_at = manual_sell(inventory, spec, quantity)
    entry_cost = float(spec["entry_cost"])
    derived_entry_cost = (
        quantity * (price - float(entry["price"])) - exit_cost - broker_realized_pnl
    )
    opened_at = datetime.fromisoformat(entry["opened_at"])
    if (
        not math.isfinite(entry_cost)
        or entry_cost < 0
        or not math.isclose(entry_cost, derived_entry_cost, abs_tol=0.01)
        or opened_at.tzinfo is None
        or closed_at <= opened_at
    ):
        raise ValueError("entry cost or chronology invalid")
    receipt = "manual-outside-qat:" + sha("|".join(sorted(spec["execution_ids"])).encode())[:24]
    trade = ClosedTrade(
        symbol=symbol,
        strategy=entry.get("strategy"),
        quantity=quantity,
        entry_price=float(entry["price"]),
        exit_price=price,
        stop_price=entry.get("stop_price"),
        opened_at=opened_at,
        closed_at=closed_at,
        entry_cost=entry_cost,
        exit_cost=exit_cost,
        exit_reason="manual sale outside QAT",
        reference_price=entry.get("reference_price"),
        market="ASX",
        currency="AUD",
        order_id=str(spec["manual_sell_perm_id"]),
        fill_id=receipt,
    )
    new_row = trade.as_row()
    with io.StringIO(newline="") as handle:
        csv.DictWriter(handle, fieldnames=_FIELDS).writerow(new_row)
        append = handle.getvalue().encode()
    if not source["closed_trades.csv"].endswith(b"\n"):
        raise ValueError("closed-trade ledger lacks a final newline")
    updates = {
        "open_position_entries.json": json_bytes({}),
        "exit_recovery.json": json_bytes({}),
        "inflight_orders.json": json_bytes({"orders": {}}),
        "closed_trades.csv": source["closed_trades.csv"] + append,
    }
    return PlannedRepair(
        data_dir,
        updates,
        before,
        {name: sha(updates.get(name, content)) for name, content in source.items()},
        {"entry": entry, "recovery": plan, "stale_inflight": stale, "existing_close": old_close[0]},
        {
            "entry": None,
            "recovery": None,
            "stale_inflight": None,
            "existing_close": old_close[0],
            "manual_close": new_row,
        },
    )


def apply_repair(data_dir: Path, planned: PlannedRepair) -> Path:
    """Back up, replace and verify only the four planned store files."""
    data_dir = data_dir.expanduser().resolve()
    if data_dir != planned.data_dir:
        raise ValueError("repair directory differs from plan")
    for name, expected in planned.before_hashes.items():
        if sha((data_dir / name).read_bytes()) != expected:
            raise ValueError(f"store hash changed before apply: {name}")
    backup = Path(tempfile.mkdtemp(prefix="flat-book-backup-", dir=data_dir.parent))
    staged: dict[str, Path] = {}
    for name, content in planned.updates.items():
        (backup / name).write_bytes((data_dir / name).read_bytes())
        fd, temporary_name = tempfile.mkstemp(prefix=f"{name}.tmp-", dir=data_dir)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        staged[name] = Path(temporary_name)
    for name, temporary in staged.items():
        os.replace(temporary, data_dir / name)
        if sha((data_dir / name).read_bytes()) != planned.after_hashes[name]:
            raise OSError(f"post-write hash mismatch: {name}; restore from {backup}")
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    for path in (args.inventory, args.plan, args.report):
        require_outside_git(path)
    inventory_bytes, spec_bytes = args.inventory.read_bytes(), args.plan.read_bytes()
    if sha(inventory_bytes) != args.inventory_sha256 or sha(spec_bytes) != args.plan_sha256:
        raise ValueError("private inventory or repair plan hash mismatch")
    planned = plan_repair(args.data_dir, json.loads(inventory_bytes), json.loads(spec_bytes))
    backup = apply_repair(args.data_dir, planned) if args.apply else None
    report = {
        "mode": "applied" if args.apply else "dry_run",
        "operator": args.operator,
        "inventory_sha256": args.inventory_sha256,
        "plan_sha256": args.plan_sha256,
        "before_hashes": planned.before_hashes,
        "after_hashes": planned.after_hashes,
        "before_records": planned.before_records,
        "after_records": planned.after_records,
        "backup": str(backup) if backup else None,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['mode']}: {args.report} SHA-256 {sha(args.report.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
