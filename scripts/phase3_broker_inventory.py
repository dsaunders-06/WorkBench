"""Read-only paper Gateway inventory; never bind or change orders."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ib_async import IB, ExecutionFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase1_exit_readiness_du_check import (  # noqa: E402
    GuardedReadOnlyClient,
    _position_row,
)
from phase3_daily_history_probe import _checked_account, _safe_output_dir, _write_raw  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from qat.data.broker.ib_translate import from_ib_fill  # noqa: E402

EXPECTED_ACCOUNT = "DUQ200898"
CLIENT_ID = 99


class InventoryReadOnlyClient(GuardedReadOnlyClient):
    """Deny every binding and trading method even when asked accidentally."""

    _DENIED = GuardedReadOnlyClient._DENIED | frozenset(
        {"reqOpenOrders", "reqOpenOrdersAsync", "reqAutoOpenOrders", "reqAutoOpenOrdersAsync"}
    )


def _account(ib: Any) -> str:
    accounts = ib.managedAccounts()
    if accounts != [EXPECTED_ACCOUNT]:
        raise ValueError(f"expected exact DU account {EXPECTED_ACCOUNT}, got {accounts!r}")
    _checked_account(ib)
    return EXPECTED_ACCOUNT


def _time_row(value: Any) -> dict[str, Any]:
    row = {
        "repr": repr(value),
        "type": type(value).__name__,
        "tzinfo": repr(getattr(value, "tzinfo", None)),
    }
    if isinstance(value, datetime):
        row["as_delivered"] = value.isoformat()
        row["utc"] = value.astimezone(UTC).isoformat() if value.tzinfo else None
    return row


def _order_row(trade: Any) -> dict[str, Any]:
    contract, order = trade.contract, trade.order
    return {
        "repr": repr(trade),
        "account": str(getattr(order, "account", "")),
        "order_id": int(getattr(order, "orderId", 0) or 0),
        "perm_id": int(getattr(order, "permId", 0) or 0),
        "client_id": int(getattr(order, "clientId", 0) or 0),
        "order_ref": str(getattr(order, "orderRef", "")),
        "symbol": str(getattr(contract, "symbol", "")),
        "con_id": int(getattr(contract, "conId", 0) or 0),
        "sec_type": str(getattr(contract, "secType", "")),
        "exchange": str(getattr(contract, "exchange", "")),
        "primary_exchange": str(getattr(contract, "primaryExchange", "")),
        "currency": str(getattr(contract, "currency", "")),
        "action": str(getattr(order, "action", "")),
        "order_type": str(getattr(order, "orderType", "")),
        "quantity": str(getattr(order, "totalQuantity", "")),
        "aux_price": str(getattr(order, "auxPrice", "")),
        "limit_price": str(getattr(order, "lmtPrice", "")),
        "tif": str(getattr(order, "tif", "")),
        "oca_group": str(getattr(order, "ocaGroup", "")),
        "parent_id": int(getattr(order, "parentId", 0) or 0),
        "status": str(getattr(getattr(trade, "orderStatus", None), "status", "")),
        "status_log": [
            {
                "status": str(getattr(item, "status", "")),
                "time": _time_row(getattr(item, "time", None)),
            }
            for item in getattr(trade, "log", ())
        ],
    }


def _execution_row(fill: Any) -> dict[str, Any]:
    execution, contract = fill.execution, fill.contract
    delivered = _time_row(getattr(execution, "time", None))
    normalized = from_ib_fill(fill, "ASX")
    return {
        "repr": repr(fill),
        "account": str(getattr(execution, "acctNumber", "")),
        "exec_id": str(getattr(execution, "execId", "")),
        "order_id": int(getattr(execution, "orderId", 0) or 0),
        "perm_id": int(getattr(execution, "permId", 0) or 0),
        "order_ref": str(getattr(execution, "orderRef", "")),
        "symbol": str(getattr(contract, "symbol", "")),
        "con_id": int(getattr(contract, "conId", 0) or 0),
        "side": str(getattr(execution, "side", "")),
        "quantity": str(getattr(execution, "shares", "")),
        "price": str(getattr(execution, "price", "")),
        "commission": repr(getattr(fill, "commissionReport", None)),
        "execution_time_repr": delivered["repr"],
        "execution_time_type": delivered["type"],
        "execution_time_tzinfo": delivered["tzinfo"],
        "execution_time_utc": delivered.get("utc"),
        "execution_time": delivered,
        "normalized": (
            {**asdict(normalized), "filled_at": normalized.filled_at.isoformat()}
            if normalized is not None
            else None
        ),
    }


async def _connect(ib: Any) -> None:
    # IB.connectAsync issues startup requests before a DU account can be checked.
    # The low-level handshake does not; all subsequent requests pass the guard.
    ib.wrapper.clientId = CLIENT_ID
    await ib.client.connectAsync("127.0.0.1", 4002, CLIENT_ID, 15)


async def _capture(ib: Any, payload: dict[str, Any]) -> None:
    account = _account(ib)
    guarded = InventoryReadOnlyClient(ib, expected_account=account)
    payload["account"] = account
    payload["requests"] = guarded.requests
    callbacks = await guarded.reqPositionsAsync()
    payload["positions_callbacks"] = [_position_row(row) for row in callbacks]
    payload["positions_cache"] = [_position_row(row) for row in ib.positions()]
    summary = await guarded.accountSummaryAsync(account)
    payload["account_summary"] = [
        {
            "repr": repr(row),
            "account": str(getattr(row, "account", "")),
            "tag": str(getattr(row, "tag", "")),
            "value": str(getattr(row, "value", "")),
            "currency": str(getattr(row, "currency", "")),
        }
        for row in summary
    ]
    payload["all_open_orders"] = [_order_row(row) for row in await guarded.reqAllOpenOrdersAsync()]
    payload["completed_orders"] = [
        _order_row(row) for row in await guarded.reqCompletedOrdersAsync(False)
    ]
    payload["executions"] = [
        _execution_row(row)
        for row in await guarded.reqExecutionsAsync(ExecutionFilter(acctCode=account))
    ]
    payload["finished_utc"] = datetime.now(UTC).isoformat()


async def _run(out_dir: Path) -> int:
    safe_dir = _safe_output_dir(out_dir)
    payload: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "host": "127.0.0.1",
        "port": 4002,
        "client_id": CLIENT_ID,
        "read_only": True,
    }
    ib = IB()
    try:
        await _connect(ib)
        await _capture(ib, payload)
    except Exception as exc:  # noqa: BLE001 - preserve partial read-only evidence
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ib.disconnect()
    payload["finished_utc"] = datetime.now(UTC).isoformat()
    path, digest = _write_raw(safe_dir, "phase3-broker-inventory", payload)
    print(f"{path} SHA-256 {digest}")
    return int("error" in payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
