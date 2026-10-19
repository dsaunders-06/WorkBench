"""Close-only paper unwind controls; execution defaults to refusal.

This script never starts the QAT application or constructs a market, vendor,
history, news, macro, fundamentals or AI source. The dated order list is a
draft until DS separately approves its exact hash and a run window.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from qat.config import Settings

SYDNEY = ZoneInfo("Australia/Sydney")
ACCOUNT = "DUQ200898"
_HOLDINGS = (
    ("BOQ.AX", 11470910, 13586, 152, 1216552512, 153, 1216552513, "6.07"),
    ("ANZ.AX", 4109645, 640, 433, 1216558933, 434, 1216558934, "35.25"),
    ("SUN.AX", 12101107, 3192, 167, 1216552521, 168, 1216552522, "17.20"),
    ("ASX.AX", 4354508, 1314, 157, 1216552515, 158, 1216552516, "51.18"),
    ("TAH.AX", 4506346, 64229, 500, 579188642, 501, 579188643, "0.80"),
)
# The 16 October book above remains the historical offline rehearsal fixture.
# A future live run must use the post-halt 19 October BOQ stop identity.
_REVISED_HOLDINGS = (
    ("BOQ.AX", 11470910, 13586, 0, 0, 727, 255153930, "6.07"),
    *_HOLDINGS[1:],
)
_BOQ_RECOVERY_REF = "24b3e1b783ef4066b6a8329e4d3700c4"
_TARGET_PRICES = {
    "BOQ.AX": "7.05",
    "ANZ.AX": "41.24",
    "SUN.AX": "21.27",
    "ASX.AX": "65.17",
    "TAH.AX": "1.075",
}
_OCA_GROUPS = {
    "BOQ.AX": "1216552511",
    "ANZ.AX": "1216558932",
    "SUN.AX": "1216552520",
    "ASX.AX": "1216552514",
    "TAH.AX": "579188641",
}


def monday_draft_actions() -> list[dict[str, Any]]:
    """Pinned 16 October evidence, for a fresh 19 October approval decision."""
    return _draft_actions(_HOLDINGS)


def revised_draft_actions() -> list[dict[str, Any]]:
    """Post-halt draft; no execution until DS approves its exact hash."""
    return _draft_actions(_REVISED_HOLDINGS)


def _draft_actions(holdings: tuple[tuple[Any, ...], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for symbol, con_id, quantity, target, target_perm, stop, stop_perm, stop_price in holdings:
        for role, order_id, perm_id in (
            ("target", target, target_perm),
            ("stop", stop, stop_perm),
        ):
            if not perm_id:
                continue
            result.append(
                {
                    "symbol": symbol,
                    "con_id": con_id,
                    "action": "CANCEL",
                    "role": role,
                    "order_id": order_id,
                    "perm_id": perm_id,
                }
            )
        result.append(
            {
                "symbol": symbol,
                "con_id": con_id,
                "action": "SELL",
                "type": "MKT",
                "quantity": quantity,
            }
        )
        result.append(
            {
                "symbol": symbol,
                "con_id": con_id,
                "action": "RECOVERY_ONLY",
                "type": "SELL STP GTC",
                "max_quantity": quantity,
                "stop_price": stop_price,
            }
        )
    return result


def canonical_bytes(actions: list[dict[str, Any]]) -> bytes:
    return (json.dumps(actions, sort_keys=True, separators=(",", ":")) + "\n").encode()


def order_list_sha256(actions: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_bytes(actions)).hexdigest()


def require_action_list(actions: list[dict[str, Any]]) -> str:
    if actions != revised_draft_actions():
        raise ValueError("order list differs from the post-halt five-holding draft")
    return order_list_sha256(actions)


def expected_inventory(
    remaining: tuple[str, ...] | None = None, *, revised: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """The complete approved account book before the next close."""
    holdings = _REVISED_HOLDINGS if revised else _HOLDINGS
    allowed = {row[0] for row in holdings} if remaining is None else set(remaining)
    positions: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    for symbol, con_id, quantity, target, target_perm, stop, stop_perm, stop_price in holdings:
        if symbol not in allowed:
            continue
        positions.append(
            {
                "account": ACCOUNT,
                "symbol": symbol.removesuffix(".AX"),
                "con_id": con_id,
                "sec_type": "STK",
                "exchange": "ASX",
                "currency": "AUD",
                "quantity": quantity,
            }
        )
        for role, order_id, perm_id, price, status in (
            ("target", target, target_perm, _TARGET_PRICES[symbol], "Submitted"),
            ("stop", stop, stop_perm, stop_price, "PreSubmitted"),
        ):
            if not perm_id:
                continue
            orders.append(
                {
                    "account": ACCOUNT,
                    "symbol": symbol.removesuffix(".AX"),
                    "con_id": con_id,
                    "sec_type": "STK",
                    "exchange": "SMART",
                    "currency": "AUD",
                    "order_id": order_id,
                    "perm_id": perm_id,
                    "client_id": 1,
                    "order_ref": _BOQ_RECOVERY_REF if revised and symbol == "BOQ.AX" else "",
                    "action": "SELL",
                    "order_type": "LMT" if role == "target" else "STP",
                    "quantity": quantity,
                    "aux_price": "0" if role == "target" else price,
                    "limit_price": price if role == "target" else "0",
                    "tif": "GTC",
                    "oca_group": "" if revised and symbol == "BOQ.AX" else _OCA_GROUPS[symbol],
                    "parent_id": 0,
                    "status": status,
                }
            )
    return {"positions": positions, "orders": orders}


_POSITION_FIELDS = tuple(expected_inventory()["positions"][0])
_ORDER_FIELDS = tuple(expected_inventory()["orders"][0])
_NUMERIC_FIELDS = frozenset({"quantity", "aux_price", "limit_price"})


def _row_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[Any, ...]:
    result: list[Any] = []
    for field in fields:
        value = row[field]
        if field in _NUMERIC_FIELDS:
            try:
                value = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError("inventory has an invalid broker number") from exc
            if not value.is_finite():
                raise ValueError("inventory has a nonfinite broker number")
        result.append(value)
    return tuple(result)


def require_inventory(
    snapshot: dict[str, Any], remaining: tuple[str, ...], *, revised: bool = False
) -> None:
    expected = expected_inventory(remaining, revised=revised)
    try:
        for section, fields in (("positions", _POSITION_FIELDS), ("orders", _ORDER_FIELDS)):
            actual_rows = snapshot[section]
            reference_rows = expected[section]
            if len(actual_rows) != len(reference_rows) or sorted(
                (_row_key(row, fields) for row in actual_rows), key=repr
            ) != sorted((_row_key(row, fields) for row in reference_rows), key=repr):
                raise ValueError(f"inventory {section} differs from the approved book")
    except (KeyError, TypeError) as exc:
        raise ValueError("inventory is incomplete") from exc


class ApprovedBroker:
    """Permit only the one approved close currently being reconciled."""

    def __init__(
        self, broker: Any, window_check: Callable[[], None] | None = None, *, revised: bool = False
    ) -> None:
        self.broker = broker
        self.window_check = window_check
        self.holdings = _REVISED_HOLDINGS if revised else _HOLDINGS
        self.symbol: str | None = None
        self.cancel_index = 0
        self.sell_sent = False
        self.recovery_sent = False
        self.violations: list[str] = []
        self.last_market_app_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.broker, name)

    def arm(self, symbol: str) -> None:
        if self.window_check is not None:
            self.window_check()
        if self.symbol is not None or symbol not in {row[0] for row in self.holdings}:
            raise ValueError("another close is active or symbol is unapproved")
        self.symbol = symbol
        self.cancel_index = 0
        self.sell_sent = False
        self.recovery_sent = False

    def disarm(self) -> None:
        self.symbol = None

    def _deny(self, reason: str) -> None:
        self.violations.append(reason)
        raise ValueError(reason)

    async def cancel_order(self, order_id: str) -> Any:
        row = next((item for item in self.holdings if item[0] == self.symbol), None)
        if row is None or self.cancel_index >= (2 if row[4] else 1):
            self._deny("cancellation outside the approved close")
        assert row is not None
        cancel_ids = tuple(str(identity) for identity in (row[4], row[6]) if identity)
        expected = cancel_ids[self.cancel_index]
        if str(order_id) != expected:
            self._deny(f"unapproved cancellation {order_id}; expected {expected}")
        result = await self.broker.cancel_order(order_id)
        self.cancel_index += 1
        return result

    def acknowledge_oca_cancelled_leg(self, order_id: str) -> None:
        """Count a verified OCA sibling cancellation without sending a request."""
        row = next((item for item in self.holdings if item[0] == self.symbol), None)
        if row is None or not row[4] or self.cancel_index != 1 or str(order_id) != str(row[6]):
            self._deny("unapproved OCA partner acknowledgement")
        self.cancel_index += 1

    async def place_order(self, order: Any) -> Any:
        row = next((item for item in self.holdings if item[0] == self.symbol), None)
        if row is None or order.symbol != self.symbol or order.side != "sell":
            self._deny("order outside the approved close")
        assert row is not None
        if order.order_type == "market":
            required_cancels = 2 if row[4] else 1
            if self.cancel_index != required_cancels or self.sell_sent or order.quantity != row[2]:
                self._deny("market sell differs from the approved full close")
            self.sell_sent = True
            self.last_market_app_id = str(order.order_id)
            return await self.broker.place_order(order)
        if order.order_type == "stop":
            if self.cancel_index == 0 or self.recovery_sent or order.stop_price is None:
                self._deny("duplicate or unpriced recovery stop")
            if Decimal(str(order.stop_price)) != Decimal(row[7]):
                self._deny("recovery stop price differs from the approved price")
            positions = await self.broker.positions()
            held = [position for position in positions if position.symbol == self.symbol]
            if (
                len(held) != 1
                or not float(order.quantity).is_integer()
                or not (0 < order.quantity <= held[0].quantity <= row[2])
            ):
                self._deny("recovery stop exceeds the remaining broker holding")
            working = await self.broker.open_orders()
            if any(
                leg.symbol == self.symbol
                and leg.stop_price is not None
                and leg.status not in ("Cancelled", "Filled", "Inactive")
                for leg in working
            ):
                self._deny("original stop still works; recovery stop refused")
            self.recovery_sent = True
            return await self.broker.place_order(order)
        self._deny("unapproved order type")

    async def get_market_data(self, symbol: str) -> Any:
        self._deny("market-data request forbidden in close-only run")

    async def get_historical(self, symbol: str, bars: int) -> Any:
        self._deny("history request forbidden in close-only run")


class GuardedIBClient:
    """Recheck the one DU account before every post-connect Gateway method."""

    _DENIED = frozenset(
        {
            "reqAutoOpenOrders",
            "reqAutoOpenOrdersAsync",
            "reqOpenOrders",
            "reqOpenOrdersAsync",
        }
    )

    def __init__(self, client: Any) -> None:
        self.client = client

    def require_du(self) -> None:
        accounts = list(self.client.managedAccounts())
        if accounts != [ACCOUNT]:
            raise ValueError(f"Gateway account is not exactly {ACCOUNT}: {accounts}")

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.client, name)
        if not callable(target) or name in {"connectAsync", "disconnect", "managedAccounts"}:
            return target
        if name in self._DENIED or name.startswith(("reqMktData", "reqHistoricalData", "reqTick")):

            def denied(*args: Any, **kwargs: Any) -> Any:
                raise ValueError(f"Gateway method forbidden in close-only run: {name}")

            return denied
        if name.startswith("req") or name in {
            "placeOrder",
            "cancelOrder",
            "qualifyContractsAsync",
            "accountSummaryAsync",
        }:

            def checked(*args: Any, **kwargs: Any) -> Any:
                self.require_du()
                return target(*args, **kwargs)

            return checked
        return target


def position_row(position: Any) -> dict[str, Any]:
    contract = position.contract
    return {
        "account": position.account,
        "symbol": contract.symbol,
        "con_id": contract.conId,
        "sec_type": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "quantity": repr(position.position),
        "repr": repr(position),
    }


def order_row(trade: Any) -> dict[str, Any]:
    contract, order = trade.contract, trade.order
    return {
        "account": order.account,
        "symbol": contract.symbol,
        "con_id": contract.conId,
        "sec_type": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "order_id": order.orderId,
        "perm_id": order.permId,
        "client_id": order.clientId,
        "order_ref": order.orderRef,
        "action": order.action,
        "order_type": order.orderType,
        "quantity": repr(order.totalQuantity),
        "aux_price": repr(order.auxPrice),
        "limit_price": repr(order.lmtPrice),
        "tif": order.tif,
        "oca_group": order.ocaGroup,
        "parent_id": order.parentId,
        "status": trade.orderStatus.status,
    }


async def capture_live_inventory(client: GuardedIBClient) -> dict[str, Any]:
    """Use keyed positions after request callbacks, and all-client order reads."""
    await client.reqPositionsAsync()
    client.require_du()
    positions = [position_row(row) for row in client.positions()]
    orders = [order_row(row) for row in await client.reqAllOpenOrdersAsync()]
    return {"positions": positions, "orders": orders}


def match_executions(
    fills: list[Any], con_id: int, order_ref: str, quantity: int
) -> list[dict[str, Any]]:
    """Attribute a complete close by the durable application order reference."""
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = Decimal(0)
    for fill in fills:
        execution = fill.execution
        if str(getattr(execution, "orderRef", "")) != order_ref:
            continue
        if (
            str(getattr(execution, "acctNumber", "")) != ACCOUNT
            or int(getattr(fill.contract, "conId", 0)) != con_id
            or int(getattr(execution, "clientId", -1)) != 1
            or str(getattr(execution, "side", "")).upper() not in {"SLD", "SELL"}
        ):
            raise ValueError("matching order reference has wrong account or contract identity")
        exec_id = str(getattr(execution, "execId", ""))
        if not exec_id or exec_id in seen:
            raise ValueError("missing or repeated execution ID")
        seen.add(exec_id)
        shares = Decimal(repr(execution.shares))
        price = Decimal(repr(execution.price))
        if not shares.is_finite() or shares <= 0 or not price.is_finite() or price <= 0:
            raise ValueError("invalid execution quantity or price")
        total += shares
        stamp = execution.time
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            raise ValueError("execution time lacks a timezone")
        commission = getattr(getattr(fill, "commissionReport", None), "commission", None)
        matched.append(
            {
                "exec_id": exec_id,
                "quantity": str(shares),
                "price": str(price),
                "time_repr": repr(stamp),
                "time_sydney": stamp.astimezone(SYDNEY).isoformat(),
                "commission": (
                    str(Decimal(repr(commission))) if isinstance(commission, (int, float)) else None
                ),
            }
        )
    if total != quantity:
        raise ValueError(f"execution quantity {total} differs from approved {quantity}")
    return matched


class RehearsalBroker:
    """No-network IB-like account, with inherited GTC legs and delayed fills."""

    name = "close-rehearsal-broker"
    avg_price_includes_commission = True

    @staticmethod
    def _average_cost(row: dict[str, Any]) -> float:
        if "repr" not in row:
            return 1.0  # explicit synthetic test fixture only
        match = re.search(r"\bavgCost=([0-9]+(?:\.[0-9]+)?)", row["repr"])
        if match is None:
            raise ValueError("recorded broker position lacks avgCost")
        cost = Decimal(match.group(1))
        if not cost.is_finite() or cost <= 0:
            raise ValueError("invalid recorded broker cost basis")
        return float(cost)

    def __init__(self, inventory: dict[str, Any]) -> None:
        from qat.data.broker.adapter import Position, RestingOrder

        self._raw_positions = list(inventory["positions"])
        self._raw_orders = list(inventory["orders"])
        self._positions = {
            f"{row['symbol']}.AX": Position(
                symbol=f"{row['symbol']}.AX",
                quantity=float(row["quantity"]),
                avg_price=self._average_cost(row),
                account=row["account"],
                con_id=row["con_id"],
                sec_type=row["sec_type"],
                exchange=row["exchange"],
                currency=row["currency"],
                qat_holding=True,
            )
            for row in inventory["positions"]
        }
        self._orders = {
            str(row["perm_id"]): RestingOrder(
                symbol=f"{row['symbol']}.AX",
                order_id=str(row["perm_id"]),
                side=row["action"].lower(),
                order_type=row["order_type"],
                quantity=float(row["quantity"]),
                status=row["status"],
                oca_group=row["oca_group"],
                owner_client_id=row["client_id"],
                stop_price=(float(row["aux_price"]) if row["order_type"] == "STP" else None),
                limit_price=(float(row["limit_price"]) if row["order_type"] == "LMT" else None),
                total_quantity=float(row["quantity"]),
            )
            for row in inventory["orders"]
        }
        self.sent: list[Any] = []
        self.cancelled: list[str] = []
        self._fills: list[Any] = []
        self._pending_sell: Any = None
        self.cancel_effect = "terminal"
        self.fill_fraction = 1.0
        self.executions: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        active = {"Submitted", "PreSubmitted", "PendingSubmit", "PendingCancel"}
        return {
            "positions": [
                {**row, "quantity": self._positions[f"{row['symbol']}.AX"].quantity}
                for row in self._raw_positions
                if f"{row['symbol']}.AX" in self._positions
            ],
            "orders": [
                {**row, "status": self._orders[str(row["perm_id"])].status}
                for row in self._raw_orders
                if str(row["perm_id"]) in self._orders
                and self._orders[str(row["perm_id"])].status in active
            ],
        }

    def fill_pending(self) -> None:
        from dataclasses import replace

        from qat.data.broker.adapter import BrokerFill

        order = self._pending_sell
        if order is None:
            raise ValueError("no pending market sell")
        position = self._positions[order.symbol]
        shares = order.quantity * self.fill_fraction
        if shares <= 0 or shares > position.quantity:
            raise ValueError("invalid simulated fill")
        remaining = position.quantity - shares
        if remaining:
            self._positions[order.symbol] = replace(position, quantity=remaining)
        else:
            del self._positions[order.symbol]
        stamp = datetime.now(UTC)
        self._fills.append(
            BrokerFill(
                order_id=order.order_id,
                symbol=order.symbol,
                side="sell",
                quantity=shares,
                price=position.avg_price,
                filled_at=stamp,
                app_order_id=order.order_id,
            )
        )
        self.executions.append(
            {
                "exec_id": f"SIM-{len(self.executions) + 1}",
                "order_id": order.order_id,
                "symbol": order.symbol,
                "quantity": shares,
                "price": position.avg_price,
                "filled_at": stamp.isoformat(),
            }
        )
        self._pending_sell = None

    async def positions(self) -> list[Any]:
        return list(self._positions.values())

    async def open_orders(self) -> list[Any]:
        return list(self._orders.values())

    async def resting_stops(self) -> dict[str, float]:
        return {
            row.symbol: float(row.stop_price)
            for row in self._orders.values()
            if row.stop_price is not None and row.status not in ("Cancelled", "Filled", "Inactive")
        }

    async def resting_stop_orders(self) -> dict[str, Any]:
        from qat.data.broker.adapter import RestingStopOrder

        return {
            row.symbol: RestingStopOrder(
                symbol=row.symbol,
                order_id=row.order_id,
                stop_price=float(row.stop_price),
                quantity=row.quantity,
                owner_client_id=row.owner_client_id,
            )
            for row in self._orders.values()
            if row.stop_price is not None and row.status not in ("Cancelled", "Filled", "Inactive")
        }

    async def account(self) -> Any:
        from qat.data.broker.adapter import AccountSummary

        return AccountSummary(net_liquidation=999701.55, cash=681431.68, buying_power=920465.20)

    async def recent_fills(self, since: datetime, symbols: list[str] | None = None) -> list[Any]:
        return [
            row
            for row in self._fills
            if row.filled_at > since and (symbols is None or row.symbol in symbols)
        ]

    async def cancel_order(self, order_id: str) -> Any:
        from dataclasses import replace

        from qat.data.broker.adapter import Order

        row = self._orders.get(str(order_id))
        if row is None:
            raise ValueError(f"unknown inherited order {order_id}")
        self.cancelled.append(str(order_id))
        if self.cancel_effect == "terminal":
            self._orders[str(order_id)] = replace(row, status="Cancelled")
        elif self.cancel_effect == "pending":
            self._orders[str(order_id)] = replace(row, status="PendingCancel")
        return Order(symbol=row.symbol, side="sell", quantity=0, order_id=str(order_id))

    async def place_order(self, order: Any) -> Any:
        from dataclasses import replace

        from qat.data.broker.adapter import RestingOrder

        if order.order_type == "market" and self._pending_sell is not None:
            raise ValueError("a sell is already pending")
        self.sent.append(replace(order))
        order.status = "transmitted"
        if order.order_type == "market":
            self._pending_sell = order
        else:
            self._orders[order.order_id] = RestingOrder(
                symbol=order.symbol,
                order_id=order.order_id,
                side="sell",
                order_type="STP",
                quantity=order.quantity,
                status="Submitted",
                stop_price=order.stop_price,
            )
        return replace(order)

    async def get_market_data(self, symbol: str) -> Any:
        raise AssertionError("market-data request in close-only rehearsal")

    async def get_historical(self, symbol: str, bars: int) -> Any:
        raise AssertionError("history request in close-only rehearsal")


def require_settings(settings: Settings) -> None:
    expected = {
        "broker": "ibkr",
        "market": "ASX",
        "execution_mode": "recommend",
        "trading_mode": "paper",
        "delever_sweep_enabled": False,
        "ibkr_account_id": ACCOUNT,
        "ibkr_client_id": 1,
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
    }
    actual = {key: getattr(settings, key) for key in expected}
    if actual != expected or settings.autonomy_enabled:
        raise ValueError(f"unsafe settings for close-only paper run: {actual}")


def require_session(session: str | None, now: datetime) -> None:
    if session is None:
        raise ValueError("session must be supplied explicitly")
    if now.tzinfo is None:
        raise ValueError("clock must be timezone-aware")
    if now.astimezone(SYDNEY).date().isoformat() != session:
        raise ValueError("not the approved Sydney session")


def require_window(session: str | None, start: str | None, end: str | None, now: datetime) -> None:
    if start is None or end is None:
        raise ValueError("start and end must be supplied explicitly")
    require_session(session, now)
    first = time.fromisoformat(start)
    last = time.fromisoformat(end)
    if not (time(10, 30) <= first < last <= time(15, 0)):
        raise ValueError("window must be within 10:30–15:00 Sydney")
    if not (first <= now.astimezone(SYDNEY).time().replace(tzinfo=None) < last):
        raise ValueError("outside the approved Sydney window")


def require_arm_window(
    session: str | None, start: str | None, end: str | None, now: datetime
) -> None:
    """Start a new holding only inside the window and no later than 14:30."""
    require_window(session, start, end, now)
    if now.astimezone(SYDNEY).time().replace(tzinfo=None) > time(14, 30):
        raise ValueError("no holding may be armed after 14:30 Sydney")


def signoff_label(session: str, list_sha256: str) -> str:
    return f"DS-approved instruction {session}, order list {list_sha256}, executed by agent"


def load_actions(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError("order list must be a JSON array of action objects")
    require_action_list(loaded)
    return loaded


def _verify_source_copy(snapshot: Path) -> dict[str, Any]:
    manifest_path = snapshot / "manifest.json"
    recorded = (snapshot / "manifest.sha256").read_text(encoding="ascii").split()[0]
    actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if actual != recorded:
        raise ValueError("store-copy manifest SHA-256 mismatch")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_files: set[str] = set()
    for path in (snapshot / "stores").rglob("*"):
        if path.is_symlink():
            raise ValueError(f"store-copy symlink: {path}")
        if path.is_file():
            actual_files.add(path.relative_to(snapshot / "stores").as_posix())
    if actual_files != set(manifest["files"]):
        raise ValueError("store-copy file set differs from its manifest")
    for relative, evidence in manifest["files"].items():
        path = snapshot / "stores" / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"store-copy file missing or linked: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError(f"store-copy file hash mismatch: {relative}")
    return manifest


def _outside_git(path: Path) -> None:
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError(f"rehearsal output must stay outside Git: {path}")


def run_rehearsal(
    source_snapshot: Path,
    fixture: Path,
    fixture_sha256: str,
    out_dir: Path,
    *,
    fault: str | None = None,
) -> dict[str, Any]:
    """Verify recorded inputs, copy stores, and write hashed offline evidence."""
    source_snapshot = source_snapshot.resolve()
    fixture = fixture.resolve()
    out_dir = out_dir.resolve()
    _outside_git(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"rehearsal output already exists: {out_dir}")
    manifest = _verify_source_copy(source_snapshot)
    content = fixture.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != fixture_sha256:
        raise ValueError("broker fixture SHA-256 mismatch")
    raw = json.loads(content)
    inventory = {"positions": raw["positions_cache"], "orders": raw["all_open_orders"]}
    require_inventory(inventory, tuple(row[0] for row in _HOLDINGS))
    out_dir.mkdir(parents=True)
    shutil.copytree(source_snapshot / "stores", out_dir / "stores")
    report = asyncio.run(rehearse_in_place(out_dir / "stores", inventory, fault=fault))
    report["fault_injection"] = fault
    report["evidence"] = {
        "source_manifest_sha256": hashlib.sha256(
            (source_snapshot / "manifest.json").read_bytes()
        ).hexdigest(),
        "source_file_count": len(manifest["files"]),
        "broker_fixture_sha256": actual,
    }
    output = out_dir / "rehearsal.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "rehearsal.sha256").write_text(
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  rehearsal.json\n", encoding="ascii"
    )
    return report


def _entry_evidence(data_dir: Path) -> dict[str, Any]:
    source = data_dir / "open_position_entries.json"
    loaded: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    return loaded


def require_boq_recovery_identity(data_dir: Path) -> None:
    """Refuse a future close until the durable 727 record has its broker permId."""
    pending = json.loads((data_dir / "ib_pending_legs.json").read_text(encoding="utf-8"))
    matches = [leg for leg in pending["legs"] if leg["order_ref"] == _BOQ_RECOVERY_REF]
    if len(matches) != 1 or any(
        matches[0].get(key) != value
        for key, value in {
            "symbol": "BOQ.AX",
            "account": ACCOUNT,
            "con_id": 11470910,
            "client_id": 1,
            "broker_order_id": 727,
            "perm_id": 255153930,
            "resolved": True,
        }.items()
    ):
        raise ValueError("BOQ recovery stop identity did not resolve to permId 255153930")


async def execute_live(
    settings: Settings,
    actions: list[dict[str, Any]],
    *,
    session: str,
    start: str,
    end: str,
    approval_date: str,
    out_dir: Path,
) -> dict[str, Any]:
    """Run only a separately approved, exact paper close list through Phase 1."""
    from ib_async import IB, ExecutionFilter

    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.pending_legs import leg_order_ref
    from qat.domain.bus import EventBus

    require_settings(settings)
    digest = require_action_list(actions)
    require_session(session, datetime.now(SYDNEY))
    if not start or not end:
        raise ValueError("start and end must be supplied explicitly")
    out_dir = out_dir.resolve()
    _outside_git(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"live evidence directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    client = GuardedIBClient(IB())
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=settings, read_only=False)
    guard = ApprovedBroker(
        adapter,
        window_check=lambda: require_arm_window(session, start, end, datetime.now(SYDNEY)),
        revised=True,
    )
    report: dict[str, Any] = {
        "status": "halted",
        "session": session,
        "approval_date": approval_date,
        "order_list_sha256": digest,
        "closes": [],
        "snapshots": [],
    }
    parts: dict[str, Any] | None = None
    try:
        await adapter.connect()
        client.require_du()
        # A restart alone does not resolve the durable 727 record. Reconcile
        # it against IBKR's orderRef/account/contract/client/permId identity
        # before adopting or cancelling any order.
        reason = await adapter.pending_identity_reason("BOQ.AX")
        if reason is not None:
            raise ValueError(reason)
        require_boq_recovery_identity(Path(settings.data_dir))
        remaining = tuple(row[0] for row in _REVISED_HOLDINGS)
        inventory = await capture_live_inventory(client)
        report["snapshots"].append({"stage": "before_start", "inventory": inventory})
        require_inventory(inventory, remaining, revised=True)
        before_entries = _entry_evidence(Path(settings.data_dir))
        before_stores = _store_hashes(Path(settings.data_dir))
        parts = build_close_components(guard, settings, bus=bus)
        await start_close_components(parts)
        if guard.violations:
            raise ValueError(f"startup attempted an unapproved broker action: {guard.violations}")
        after_entries = _entry_evidence(Path(settings.data_dir))
        for symbol in remaining:
            original = before_entries.get(symbol)
            current = after_entries.get(symbol)
            if original is None or current is None:
                raise ValueError(f"startup lost entry evidence for {symbol}")
            if any(current.get(key) != original.get(key) for key in original):
                raise ValueError(f"startup changed existing entry evidence for {symbol}")
        if set(after_entries) != set(remaining):
            raise ValueError("startup did not retire exactly the four stale entry records")
        if set(parts["reconciliation"].adopted) != set(remaining):
            raise ValueError("startup adoption differs from the approved book")
        if any(
            parts["bridge"].position_entries()[row[0]].quantity != row[2]
            for row in _REVISED_HOLDINGS
        ):
            raise ValueError("startup legacy quantity migration differs from the approved book")
        require_inventory(await capture_live_inventory(client), remaining, revised=True)
        report["startup_store_diff"] = _changed(
            before_stores, _store_hashes(Path(settings.data_dir))
        )
        for symbol, con_id, quantity, _, _, _, _, _ in _REVISED_HOLDINGS:
            inventory = await capture_live_inventory(client)
            report["snapshots"].append({"stage": f"before_{symbol}", "inventory": inventory})
            require_inventory(inventory, remaining, revised=True)
            if parts["kill_switch"].tripped or guard.violations:
                raise ValueError(f"safety gate active before {symbol}")
            prior_closed = len(parts["ledger"].closed_trades())
            guard.arm(symbol)
            outcome = await parts["closer"].close_position(
                symbol, operator=signoff_label(approval_date, digest)
            )
            if outcome.outcome.value != "closed" or not guard.sell_sent:
                raise ValueError(f"{symbol} close did not transmit: {outcome.detail}")
            app_id = guard.last_market_app_id
            if not app_id:
                raise ValueError(f"{symbol} application order identity is missing")
            order_ref = leg_order_ref(app_id, "primary")
            deadline = datetime.now(UTC).timestamp() + 120
            evidence: list[dict[str, Any]] | None = None
            while datetime.now(UTC).timestamp() < deadline:
                inventory = await capture_live_inventory(client)
                other = {
                    "positions": [
                        row
                        for row in inventory["positions"]
                        if row["symbol"] != symbol.removesuffix(".AX")
                    ],
                    "orders": [
                        row
                        for row in inventory["orders"]
                        if row["symbol"] != symbol.removesuffix(".AX")
                    ],
                }
                require_inventory(
                    other, tuple(item for item in remaining if item != symbol), revised=True
                )
                current_positions = [
                    row
                    for row in inventory["positions"]
                    if row["symbol"] == symbol.removesuffix(".AX")
                ]
                current_orders = [
                    row
                    for row in inventory["orders"]
                    if row["symbol"] == symbol.removesuffix(".AX")
                ]
                if len(current_positions) > 1 or any(
                    row["account"] != ACCOUNT
                    or row["con_id"] != con_id
                    or Decimal(str(row["quantity"])) < 0
                    or Decimal(str(row["quantity"])) > quantity
                    for row in current_positions
                ):
                    raise ValueError(f"{symbol} broker position changed unexpectedly")
                if any(
                    row["account"] != ACCOUNT
                    or row["con_id"] != con_id
                    or row["action"] != "SELL"
                    or row["order_type"] != "MKT"
                    or row["order_ref"] != order_ref
                    for row in current_orders
                ):
                    raise ValueError(f"{symbol} has an unexpected working order")
                if not current_positions and not current_orders:
                    client.require_du()
                    fills = await client.reqExecutionsAsync(ExecutionFilter(acctCode=ACCOUNT))
                    try:
                        evidence = match_executions(fills, con_id, order_ref, quantity)
                    except ValueError as exc:
                        if "execution quantity" not in str(exc):
                            raise
                    if evidence is not None:
                        break
                elif current_positions and not current_orders:
                    await parts["oms"].recover_exit_protection()
                    raise ValueError(f"{symbol} market sell ended with residual shares")
                await asyncio.sleep(1)
            if evidence is None:
                raise ValueError(f"{symbol} full fill and execution attribution timed out")
            if await parts["oms"].check_reconciliation():
                raise ValueError(f"{symbol} reconciliation mismatch")
            if await parts["oms"].check_resting_orders():
                raise ValueError(f"{symbol} resting-order scan is not clean")
            if parts["kill_switch"].tripped or parts["oms"].exit_protection_pending(symbol):
                raise ValueError(f"{symbol} has a safety halt or pending protection recovery")
            if symbol in parts["bridge"].position_entries():
                raise ValueError(f"{symbol} entry record remains after the full exit")
            if len(parts["ledger"].closed_trades()) <= prior_closed:
                raise ValueError(f"{symbol} has no closed-trade row")
            remaining = tuple(item for item in remaining if item != symbol)
            require_inventory(inventory, remaining, revised=True)
            report["closes"].append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "application_order_id": app_id,
                    "order_ref": order_ref,
                    "execution_evidence": evidence,
                    "cancelled": list(outcome.cancelled_legs),
                    "detail": outcome.detail,
                }
            )
            guard.disarm()
        report["status"] = "completed"
    except Exception as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        if parts is not None:
            await stop_close_components(parts)
        await adapter.disconnect()
        report["finished_sydney"] = datetime.now(SYDNEY).isoformat()
        output = out_dir / "run.json"
        output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (out_dir / "run.sha256").write_text(
            f"{hashlib.sha256(output.read_bytes()).hexdigest()}  run.json\n", encoding="ascii"
        )
    return report


class _LiveEntries(Mapping[str, Any]):
    """A read-through view, as the Phase 1 runtime supplies to PositionCloser."""

    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def __getitem__(self, symbol: str) -> Any:
        return self.bridge.position_entries()[symbol]

    def __iter__(self) -> Iterator[str]:
        return iter(self.bridge.position_entries())

    def __len__(self) -> int:
        return len(self.bridge.position_entries())


def build_close_components(broker: Any, settings: Settings, *, bus: Any = None) -> dict[str, Any]:
    """Use the existing Phase 1 close path without starting any signal source."""
    require_settings(settings)
    from qat.data.earnings import NullEarningsCalendar
    from qat.domain.bus import EventBus
    from qat.domain.decision_journal import DecisionJournal
    from qat.domain.oms.oms import OMS
    from qat.domain.oms.position_closer import PositionCloser
    from qat.domain.oms.reconciliation import ReconciliationMonitor
    from qat.domain.oms.signal_bridge import SignalToOrderBridge
    from qat.domain.performance.trades import TradeLedger
    from qat.domain.risk_engine.engine import RiskEngine
    from qat.domain.risk_engine.kill_switch import KillSwitch

    bus = bus or EventBus()
    kill_switch = KillSwitch(settings.data_dir)
    risk_engine = RiskEngine(bus, kill_switch, settings=settings)
    journal = DecisionJournal(settings.data_dir)
    oms = OMS(broker, risk_engine, kill_switch, bus=bus, journal=journal, settings=settings)
    ledger = TradeLedger(bus, settings.data_dir, settings=settings)
    bridge = SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        earnings_calendar=NullEarningsCalendar(),
        warm_symbols=(),
    )
    reconciliation = ReconciliationMonitor(oms, settings=settings, bus=bus)
    closer = PositionCloser(oms, broker, kill_switch, _LiveEntries(bridge))
    return {
        "bus": bus,
        "kill_switch": kill_switch,
        "risk_engine": risk_engine,
        "oms": oms,
        "journal": journal,
        "ledger": ledger,
        "bridge": bridge,
        "reconciliation": reconciliation,
        "closer": closer,
    }


async def start_close_components(components: dict[str, Any]) -> None:
    """Start only the adopted-book, fill and close machinery."""
    await components["risk_engine"].start()
    await components["ledger"].start()
    await components["reconciliation"].start()
    await components["bridge"].start()
    if components["kill_switch"].tripped:
        raise RuntimeError(f"startup kill switch: {components['kill_switch'].reason}")


async def stop_close_components(components: dict[str, Any]) -> None:
    await components["bridge"].stop()
    await components["reconciliation"].stop()
    await components["ledger"].stop()
    await components["risk_engine"].stop()


def _store_hashes(data_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(data_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data_dir.rglob("*")
        if path.is_file()
    }


def _changed(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(after.keys() - before.keys()),
        "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        "removed": sorted(before.keys() - after.keys()),
    }


async def _remaining_book(broker: RehearsalBroker) -> dict[str, Any]:
    positions = await broker.positions()
    working = [
        row
        for row in await broker.open_orders()
        if row.status not in ("Cancelled", "Filled", "Inactive")
    ]
    return {
        "remaining_positions": [row.symbol for row in positions],
        "remaining_working_orders": [row.order_id for row in working],
        "remaining_position_details": [asdict(row) for row in positions],
        "remaining_order_details": [asdict(row) for row in working],
    }


async def rehearse_in_place(
    data_dir: Path, inventory: dict[str, Any], *, fault: str | None = None
) -> dict[str, Any]:
    """Exercise the real close components on a copied store and no-network fake."""
    require_inventory(inventory, tuple(row[0] for row in _HOLDINGS))
    broker = RehearsalBroker(inventory)
    if fault == "cancel_refused":
        broker.cancel_effect = "rejected"
    elif fault == "leg_filled":
        from dataclasses import replace

        key = str(_HOLDINGS[0][4])
        broker._orders[key] = replace(broker._orders[key], status="Filled")
    elif fault == "quantity_mismatch":
        from dataclasses import replace

        broker._positions["BOQ.AX"] = replace(
            broker._positions["BOQ.AX"], quantity=_HOLDINGS[0][2] - 1
        )
    elif fault == "partial_fill":
        broker.fill_fraction = 0.5
    elif fault == "unknown_order":
        from qat.data.broker.adapter import RestingOrder

        unknown = dict(inventory["orders"][0])
        unknown.update(symbol="BHP", con_id=123, order_id=999, perm_id=999)
        broker._raw_orders.append(unknown)
        broker._orders["999"] = RestingOrder(
            symbol="BHP.AX",
            order_id="999",
            side="sell",
            order_type="LMT",
            quantity=1,
            status="Submitted",
            limit_price=1,
        )
    elif fault is not None:
        raise ValueError(f"unknown rehearsal fault {fault}")
    guard = ApprovedBroker(broker)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id=ACCOUNT,
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(data_dir),
    )
    before = _store_hashes(data_dir)
    report: dict[str, Any] = {"status": "halted", "startup": {}, "closes": []}
    try:
        require_inventory(broker.snapshot(), tuple(row[0] for row in _HOLDINGS))
    except ValueError as exc:
        report["reason"] = f"ValueError: {exc}"
        report.update(await _remaining_book(broker))
        report["final_store_diff"] = _changed(before, _store_hashes(data_dir))
        return report
    parts = build_close_components(guard, settings)
    try:
        await start_close_components(parts)
        if guard.violations or broker.sent or broker.cancelled:
            raise ValueError("startup attempted an order or cancellation")
        adopted = parts["reconciliation"].adopted
        expected_symbols = {row[0] for row in _HOLDINGS}
        if set(adopted) != expected_symbols:
            raise ValueError("startup adoption differs from the five approved holdings")
        entries = parts["bridge"].position_entries()
        if set(entries) != expected_symbols or any(
            entries[row[0]].quantity != row[2] for row in _HOLDINGS
        ):
            raise ValueError("legacy migration did not leave exactly the five held entries")
        current = _store_hashes(data_dir)
        report["startup"] = {
            "adopted": adopted,
            "entries": sorted(entries),
            "store_diff": _changed(before, current),
        }
        remaining = tuple(row[0] for row in _HOLDINGS)
        for symbol, _, quantity, _, target_perm, _, stop_perm, _ in _HOLDINGS:
            require_inventory(broker.snapshot(), remaining)
            if parts["kill_switch"].tripped:
                raise ValueError(f"kill switch before {symbol}")
            prior_closed = len(parts["ledger"].closed_trades())
            prior_executions = len(broker.executions)
            guard.arm(symbol)
            outcome = await parts["closer"].close_position(
                symbol, operator="OFFLINE REHEARSAL — no DS order approval"
            )
            if outcome.outcome.value != "closed" or len(broker.sent) != len(report["closes"]) + 1:
                raise ValueError(
                    f"{symbol} close did not transmit exactly one sell: {outcome.detail}"
                )
            if broker.cancelled[-2:] != [str(target_perm), str(stop_perm)]:
                raise ValueError(f"{symbol} protective legs were not cancelled target first")
            broker.fill_pending()
            if await parts["oms"].check_reconciliation():
                raise ValueError(f"{symbol} reconciliation mismatch after simulated fill")
            if await parts["oms"].check_resting_orders():
                raise ValueError(f"{symbol} resting-order scan is not clean")
            if parts["kill_switch"].tripped or parts["oms"].exit_protection_pending(symbol):
                raise ValueError(f"{symbol} remains halted or has pending protection recovery")
            if symbol in parts["bridge"].position_entries():
                raise ValueError(f"{symbol} entry record remains after full fill")
            if len(parts["ledger"].closed_trades()) <= prior_closed:
                raise ValueError(f"{symbol} closed-trade row was not written")
            if len(broker.executions) != prior_executions + 1:
                raise ValueError(f"{symbol} has no unique execution evidence")
            remaining = tuple(item for item in remaining if item != symbol)
            require_inventory(broker.snapshot(), remaining)
            next_hashes = _store_hashes(data_dir)
            report["closes"].append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "cancelled": [str(target_perm), str(stop_perm)],
                    "execution_id": broker.executions[-1]["exec_id"],
                    "execution_time": broker.executions[-1]["filled_at"],
                    "store_diff": _changed(current, next_hashes),
                }
            )
            current = next_hashes
            guard.disarm()
        report["status"] = "completed"
    except Exception as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
        report.update(await _remaining_book(broker))
    finally:
        await stop_close_components(parts)
    report["final_store_diff"] = _changed(before, _store_hashes(data_dir))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-draft", action="store_true")
    parser.add_argument("--rehearse", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source-snapshot", type=Path)
    parser.add_argument("--broker-fixture", type=Path)
    parser.add_argument("--fixture-sha256")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument(
        "--fault",
        choices=(
            "cancel_refused",
            "leg_filled",
            "quantity_mismatch",
            "partial_fill",
            "unknown_order",
        ),
    )
    parser.add_argument("--order-list", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--approved-sha256")
    parser.add_argument("--approval-date")
    arguments = parser.parse_args()
    if arguments.print_draft:
        actions = revised_draft_actions()
        print(json.dumps(actions, indent=2))
        print(f"SHA-256: {order_list_sha256(actions)}")
        return 0
    if arguments.rehearse:
        if not all(
            (
                arguments.source_snapshot,
                arguments.broker_fixture,
                arguments.fixture_sha256,
                arguments.out_dir,
            )
        ):
            parser.error("rehearsal needs source snapshot, broker fixture, hash and output")
        report = run_rehearsal(
            arguments.source_snapshot,
            arguments.broker_fixture,
            arguments.fixture_sha256,
            arguments.out_dir,
            fault=arguments.fault,
        )
        print(f"Rehearsal {report['status']}: {report.get('reason', 'all five closes checked')}")
        return int(report["status"] != "completed")
    if not arguments.execute or arguments.order_list is None:
        parser.error("execution refused: supply --execute and an approved order list")
    actions = load_actions(arguments.order_list)
    digest = order_list_sha256(actions)
    if arguments.approved_sha256 != digest:
        parser.error("execution refused: approved order-list hash does not match")
    require_settings(Settings())
    require_session(arguments.session, datetime.now(SYDNEY))
    if not arguments.start or not arguments.end:
        parser.error("execution refused: start and end must be supplied explicitly")
    if arguments.approval_date is None or arguments.out_dir is None:
        parser.error("execution refused: approval date and outside-Git evidence directory required")
    if date.fromisoformat(arguments.approval_date) > date.fromisoformat(arguments.session):
        parser.error("approval date cannot follow the session")
    report = asyncio.run(
        execute_live(
            Settings(),
            actions,
            session=arguments.session,
            start=arguments.start,
            end=arguments.end,
            approval_date=arguments.approval_date,
            out_dir=arguments.out_dir,
        )
    )
    print(f"Close-only run {report['status']}: {report.get('reason', 'all five verified')}")
    return int(report["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
