"""Friday paper unwind preflight: read only and compare with the approved snapshot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ib_async import IB

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase1_exit_readiness_du_check import _position_row
from phase3_broker_inventory import (
    CLIENT_ID,
    EXPECTED_ACCOUNT,
    InventoryReadOnlyClient,
    _account,
    _connect,
    _order_row,
)
from phase3_daily_history_probe import _safe_output_dir, _write_raw

BASELINE_SHA256 = "e02a19420fb82601f9dc6778e467c78cb541f3be3ad90e2975fa2150bd033967"
APPROVED_POSITIONS = {
    ("BOQ", 11470910): 13586,
    ("ANZ", 4109645): 640,
    ("SUN", 12101107): 3192,
    ("ASX", 4354508): 1314,
    ("TAH", 4506346): 64229,
}
APPROVED_ORDER_IDS = {
    "BOQ": (152, 153),
    "ANZ": (433, 434),
    "SUN": (167, 168),
    "ASX": (157, 158),
    "TAH": (500, 501),
}
POSITION_FIELDS = (
    "account",
    "symbol",
    "con_id",
    "sec_type",
    "exchange",
    "primary_exchange",
    "currency",
    "quantity",
)
ORDER_FIELDS = (
    "account",
    "symbol",
    "con_id",
    "sec_type",
    "exchange",
    "primary_exchange",
    "currency",
    "order_id",
    "perm_id",
    "client_id",
    "order_ref",
    "action",
    "order_type",
    "quantity",
    "aux_price",
    "limit_price",
    "tif",
    "oca_group",
    "parent_id",
    "status",
)
DECIMAL_FIELDS = frozenset({"quantity", "aux_price", "limit_price"})


def _number(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid broker number {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"nonfinite broker number {value!r}")
    return number


def _identity_rows(
    payload: dict[str, Any], section: str, fields: tuple[str, ...]
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for row in payload[section]:
        values = tuple(
            _number(row[field]) if field in DECIMAL_FIELDS else row[field] for field in fields
        )
        rows.append(values)
    return sorted(rows, key=repr)


def _load_baseline(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != BASELINE_SHA256:
        raise ValueError(f"baseline SHA-256 mismatch: {digest}")
    payload: dict[str, Any] = json.loads(content)
    if payload.get("account") != EXPECTED_ACCOUNT:
        raise ValueError("baseline account differs from approved DU account")
    positions = payload.get("positions_cache", [])
    expected_positions = APPROVED_POSITIONS
    actual_positions = {
        (row["symbol"], row["con_id"]): int(_number(row["quantity"])) for row in positions
    }
    if len(positions) != len(expected_positions) or actual_positions != expected_positions:
        raise ValueError("baseline positions differ from approved table")
    orders = payload.get("all_open_orders", [])
    actual_orders = {
        symbol: tuple(sorted(row["order_id"] for row in orders if row["symbol"] == symbol))
        for symbol in APPROVED_ORDER_IDS
    }
    if len(orders) != 10 or actual_orders != {
        symbol: tuple(sorted(ids)) for symbol, ids in APPROVED_ORDER_IDS.items()
    }:
        raise ValueError("baseline orders differ from approved table")
    return payload


def _compare(baseline: dict[str, Any], live: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if live.get("account") != baseline.get("account"):
        reasons.append("account_changed")
    for section, fields in (
        ("positions_cache", POSITION_FIELDS),
        ("all_open_orders", ORDER_FIELDS),
    ):
        try:
            expected = _identity_rows(baseline, section, fields)
            observed = _identity_rows(live, section, fields)
        except (KeyError, TypeError, ValueError) as exc:
            reasons.append(f"{section}_invalid:{exc}")
            continue
        if expected != observed:
            reasons.append(f"{section}_changed")
    return reasons


async def _capture(ib: Any, payload: dict[str, Any]) -> None:
    account = _account(ib)
    guarded = InventoryReadOnlyClient(ib, expected_account=account)
    payload["account"] = account
    payload["requests"] = guarded.requests
    callbacks = await guarded.reqPositionsAsync()
    payload["positions_callbacks"] = [_position_row(row) for row in callbacks]
    payload["positions_cache"] = [_position_row(row) for row in ib.positions()]
    payload["all_open_orders"] = [_order_row(row) for row in await guarded.reqAllOpenOrdersAsync()]


async def _run(out_dir: Path, baseline_path: Path) -> int:
    safe_dir = _safe_output_dir(out_dir)
    payload: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "host": "127.0.0.1",
        "port": 4002,
        "client_id": CLIENT_ID,
        "read_only": True,
        "baseline_path": str(baseline_path.resolve()),
        "baseline_sha256": BASELINE_SHA256,
    }
    ib = IB()
    try:
        baseline = _load_baseline(baseline_path)
        await _connect(ib)
        await _capture(ib, payload)
        payload["mismatches"] = _compare(baseline, payload)
        payload["approved_to_start"] = not payload["mismatches"]
    except Exception as exc:  # noqa: BLE001 - retain failed preflight evidence
        payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["approved_to_start"] = False
    finally:
        ib.disconnect()
    payload["finished_utc"] = datetime.now(UTC).isoformat()
    path, digest = _write_raw(safe_dir, "phase3-unwind-preflight", payload)
    print(f"{path} SHA-256 {digest}")
    if not payload["approved_to_start"]:
        print(f"STOP: {payload.get('error') or payload.get('mismatches')}")
    return int(not payload["approved_to_start"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.out_dir, arguments.baseline))


if __name__ == "__main__":
    raise SystemExit(main())
