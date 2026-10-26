"""One 27 October 2026 BHP.AX paper probe of pre-open LMT/GTD entries.

The two orders have separate A$800 reference-price caps. This is an isolated
paper experiment, not a production entry path. Raw evidence stays outside Git.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime, time
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB, ExecutionFilter, LimitOrder, MarketOrder, Stock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phase3_daily_history_probe import _safe_output_dir, _write_raw  # noqa: E402

from qat.data.broker.ticks import round_to_tick  # noqa: E402

SESSION = date(2026, 10, 27)
PRIOR_SESSION = date(2026, 10, 26)
SYDNEY = ZoneInfo("Australia/Sydney")
SYMBOL = "BHP.AX"
CAP = Decimal("800")
# IBKR's order reference permits yyyyMMdd-HH:mm:ss in UTC for goodTillDate:
# https://ibkrcampus.com/docs/tws-api/ref/order
GTD_UTC = "20261026-23:15:00"  # 10:15:00 Australia/Sydney on 27 October.
# DS's bounded fill threshold. Current ASX cash-market OSPA/normal-trading
# schedule: https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours
EARLIEST_FILL = time(9, 59, 45)
EVIDENCE_TIMEOUT_SECONDS = 10.0
LIVE = frozenset({"PendingSubmit", "PreSubmitted", "Submitted"})
CANCELLED = frozenset({"Cancelled", "ApiCancelled"})
TERMINAL = CANCELLED | {"Filled"}


def _now() -> datetime:
    return datetime.now(SYDNEY)


def _session_window(session: date, now: datetime | None = None) -> None:
    current = now or _now()
    if current.tzinfo is None:
        raise ValueError("session clock must include a timezone")
    local = current.astimezone(SYDNEY)
    if (
        session != SESSION
        or local.date() != SESSION
        or not time(9, 40) <= local.time() < time(9, 50)
    ):
        raise ValueError("GTD auction probe starts only 27 October 2026, 09:40–09:50 AEDT")


def _prior_close(bars: Any) -> Decimal:
    matching = [bar for bar in bars if str(bar.date)[:10] == PRIOR_SESSION.isoformat()]
    if len(matching) != 1:
        raise ValueError("the prior ASX session's IBKR close is unavailable or ambiguous")
    close = Decimal(repr(matching[0].close))
    if not close.is_finite() or close <= 0:
        raise ValueError("invalid prior IBKR close")
    return close


def _orders_from_close(close: Decimal) -> tuple[tuple[Decimal, int], tuple[Decimal, int]]:
    if not close.is_finite() or close <= 0:
        raise ValueError("invalid prior IBKR close")
    result: list[tuple[Decimal, int]] = []
    for factor in (Decimal("1.02"), Decimal("0.95")):
        raw = close * factor
        limit = Decimal(str(round_to_tick(float(raw), "ASX", "buy")))
        if limit <= 0 or limit > raw:
            raise ValueError("buy limit cannot be represented safely on the ASX tick grid")
        quantity = int((CAP / limit).to_integral_value(rounding=ROUND_FLOOR))
        if quantity <= 0 or limit * quantity > CAP:
            raise ValueError("the A$800 per-order cap cannot size a valid parcel")
        result.append((limit, quantity))
    return result[0], result[1]


def _buy_order(quantity: int, limit: Decimal, account: str, ref: str) -> LimitOrder:
    order = LimitOrder("BUY", quantity, float(limit), tif="GTD", goodTillDate=GTD_UTC)
    order.account = account
    order.orderRef = ref
    order.outsideRth = False
    order.transmit = True
    if order.orderType != "LMT" or order.tif != "GTD" or order.goodTillDate != GTD_UTC:
        raise AssertionError("GTD order construction changed")
    return order


def _cancel_required(status: str, remaining: float) -> bool:
    if status == "Inactive" or status == "PendingCancel":
        raise RuntimeError(f"probe buy is {status}; cancellation cannot be confirmed")
    if status in TERMINAL:
        return False
    if status in LIVE and remaining > 0:
        return True
    raise RuntimeError(f"unexpected buy status or remainder: {status}/{remaining}")


def _exit_quantity(a_filled: int, b_filled: int, held: int) -> int:
    owned = a_filled + b_filled
    if owned < 0 or held != owned:
        raise RuntimeError("broker position differs from attributable probe fills")
    return owned


def _exact_account(client: Any) -> None:
    if list(client.managedAccounts()) != [client.expected_account]:
        raise ValueError("probe requires exactly the approved DU paper account")


class _ExactAccountGateway:
    """Check the account set immediately before every IBKR request."""

    _REQUESTS = frozenset({"placeOrder", "cancelOrder", "qualifyContractsAsync", "cancelMktData"})

    def __init__(self, raw: Any, expected_account: str) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "expected_account", expected_account)

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._raw, name)
        if not callable(method) or not (name.startswith("req") or name in self._REQUESTS):
            return method

        def checked(*args: Any, **kwargs: Any) -> Any:
            _exact_account(self)
            return method(*args, **kwargs)

        return checked


def _load_approval(path: Path, digest: str) -> str:
    source = path.expanduser().resolve()
    if any((ancestor / ".git").exists() for ancestor in (source, *source.parents)):
        raise ValueError("probe approval must stay outside Git")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("probe approval hash differs")
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {
        "account",
        "approved_by",
        "approval_date",
        "session",
        "symbol",
        "operator",
        "cap_per_order_aud",
    }:
        raise ValueError("probe approval terms differ")
    account = value["account"]
    if (
        not isinstance(account, str)
        or not account.startswith("DU")
        or not account[2:].isalnum()
        or value["approved_by"] != "DS"
        or value["approval_date"] != "2026-10-26"
        or value["session"] != SESSION.isoformat()
        or value["symbol"] != SYMBOL
        or value["operator"] != "DS"
        or value["cap_per_order_aud"] != str(CAP)
    ):
        raise ValueError("probe approval terms differ")
    return account


def _claim_attempt(output: Path) -> None:
    """One attempt for the pinned session, including a failed attempt."""
    with (output / "gtd-20261027-attempt.lock").open("x", encoding="utf-8") as lock:
        lock.write(_now().isoformat() + "\n")


def _event(events: list[dict[str, Any]], name: str, **data: Any) -> None:
    events.append({"event": name, "at_aedt": _now().isoformat(), **data})


def _trade_view(trade: Any) -> dict[str, Any]:
    order = trade.order
    status = trade.orderStatus
    return {
        "ref": str(order.orderRef),
        "order_id": order.orderId,
        "perm_id": order.permId,
        "action": order.action,
        "type": order.orderType,
        "quantity": str(order.totalQuantity),
        "limit": str(order.lmtPrice),
        "tif": order.tif,
        "gtd": str(order.goodTillDate),
        "status": status.status,
        "filled": str(status.filled),
        "remaining": str(status.remaining),
        "fills": [
            {
                "exec_id": str(fill.execution.execId),
                "time": str(fill.execution.time),
                "shares": str(fill.execution.shares),
                "price": str(fill.execution.price),
                "commission": repr(fill.commissionReport),
            }
            for fill in trade.fills
        ],
    }


async def _book(
    client: Any, events: list[dict[str, Any]], name: str
) -> tuple[list[Any], list[Any]]:
    positions = await client.reqPositionsAsync()
    orders = await client.reqAllOpenOrdersAsync()
    if positions is None or orders is None:
        raise RuntimeError("independent paper book unavailable")
    _event(
        events,
        name,
        positions=[repr(row) for row in positions],
        orders=[repr(row) for row in orders],
    )
    return list(positions), list(orders)


def _held(positions: list[Any], account: str, con_id: int) -> int:
    held = 0
    for row in positions:
        if row.account != account or int(row.contract.conId) != con_id:
            if Decimal(str(row.position)) != 0:
                raise RuntimeError("unrelated paper position appeared")
            continue
        quantity = Decimal(str(row.position))
        if quantity != quantity.to_integral_value():
            raise RuntimeError("non-whole probe position")
        held += int(quantity)
    return held


def _fill_count(trade: Any) -> int:
    shares = sum((Decimal(str(fill.execution.shares)) for fill in trade.fills), Decimal(0))
    if shares != shares.to_integral_value() or shares < 0:
        raise RuntimeError("probe fill quantity is ambiguous")
    return int(shares)


def _fills_match_status(trade: Any) -> bool:
    reported = Decimal(str(trade.orderStatus.filled))
    return reported == _fill_count(trade)


async def _wait_fill_details(trades: list[Any], deadline: time) -> None:
    while _now().time() < deadline:
        if all(_fills_match_status(trade) for trade in trades):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("IBKR execution details did not match reported filled quantity")


def _check_pre_expiry(
    buys: list[Any], now: datetime, cancel_requests: set[str] | None = None
) -> None:
    for trade in buys:
        status = trade.orderStatus.status
        own_cancel = str(getattr(getattr(trade, "order", None), "orderRef", "")) in (
            cancel_requests or set()
        )
        if (
            status == "Inactive"
            or (status == "PendingCancel" and not own_cancel)
            or (status in CANCELLED and now.time() < time(10, 15) and not own_cancel)
        ):
            raise RuntimeError(f"buy ended unexpectedly before GTD expiry: {status}")
        for fill in getattr(trade, "fills", ()):
            executed = fill.execution.time
            if not isinstance(executed, datetime) or executed.tzinfo is None:
                raise RuntimeError("buy execution time is unavailable or timezone-naive")
            local = executed.astimezone(SYDNEY)
            if local.date() != SESSION or local.time() < EARLIEST_FILL:
                raise RuntimeError("buy filled before the ASX opening auction threshold")
        if status == "Filled" and now.time() < EARLIEST_FILL:
            raise RuntimeError("buy filled before the ASX opening auction")


async def _record_execution_times(
    client: Any, events: list[dict[str, Any]], expected_ids: set[str] | None = None
) -> None:
    requested = _now().isoformat()
    async with asyncio.timeout(EVIDENCE_TIMEOUT_SECONDS):
        executions = await client.reqExecutionsAsync(
            ExecutionFilter(acctCode=client.expected_account)
        )
    if executions is None:
        raise RuntimeError("reqExecutions response unavailable")
    rows: list[dict[str, Any]] = []
    for fill in executions:
        executed = fill.execution.time
        if not isinstance(executed, datetime) or executed.tzinfo is None:
            raise RuntimeError("reqExecutions time is unavailable or timezone-naive")
        rows.append(
            {
                "exec_id": str(fill.execution.execId),
                "order_ref": str(fill.execution.orderRef),
                "execution_time_repr": repr(executed),
                "execution_time_utc": executed.astimezone(UTC).isoformat(),
                "execution_time_aedt": executed.astimezone(SYDNEY).isoformat(),
                "shares": str(fill.execution.shares),
                "price": str(fill.execution.price),
                "commission": repr(fill.commissionReport),
            }
        )
    _event(
        events,
        "execution times recheck",
        requested_at_aedt=requested,
        fills=rows,
        executions=[repr(fill) for fill in executions],
    )
    if expected_ids and not expected_ids.issubset({row["exec_id"] for row in rows}):
        raise RuntimeError("reqExecutions did not confirm every observed fill")


async def _wait_until(
    local: time,
    buys: list[Any] | None = None,
    client: Any | None = None,
    events: list[dict[str, Any]] | None = None,
    callback_halts: list[str] | None = None,
) -> None:
    recorded: set[str] = set()
    while _now().time() < local:
        _raise_callback_halt(callback_halts)
        if buys:
            _check_pre_expiry(buys, _now())
            observed = {str(fill.execution.execId) for trade in buys for fill in trade.fills}
            if client is not None and events is not None and observed - recorded:
                await _record_execution_times(client, events, observed)
                recorded.update(observed)
            _raise_callback_halt(callback_halts)
        seconds = (datetime.combine(SESSION, local, SYDNEY) - _now()).total_seconds()
        await asyncio.sleep(max(0.1, min(5.0, seconds)))
    _raise_callback_halt(callback_halts)


def _raise_callback_halt(reasons: list[str] | None) -> None:
    if reasons:
        raise RuntimeError(reasons[0])


async def _wait_status(
    trade: Any,
    allowed: frozenset[str],
    deadline: time,
    *,
    cancel_requested: bool = False,
    events: list[dict[str, Any]] | None = None,
    callback_halts: list[str] | None = None,
) -> None:
    last_status: str | None = None
    while _now().time() < deadline:
        _raise_callback_halt(callback_halts)
        status = trade.orderStatus.status
        if events is not None and status != last_status:
            _event(events, "cancel state", order=_trade_view(trade))
            last_status = status
        if status in allowed:
            return
        if status == "Inactive" or (status == "PendingCancel" and not cancel_requested):
            raise RuntimeError(f"unexpected order state: {status}")
        await asyncio.sleep(0.5)
    raise RuntimeError(f"order status not confirmed before {deadline}: {trade.orderStatus.status}")


async def _cancel_live_buy(
    client: Any,
    trade: Any,
    events: list[dict[str, Any]],
    cancel_requests: set[str] | None = None,
    *,
    deadline: time = time(10, 20),
    emergency: bool = False,
    callback_halts: list[str] | None = None,
) -> None:
    requested = cancel_requests if cancel_requests is not None else set()
    ref = str(trade.order.orderRef)
    if ref not in requested:
        if not _cancel_required(trade.orderStatus.status, float(trade.orderStatus.remaining)):
            return
        _event(
            events,
            "emergency cancellation" if emergency else "cancel requested",
            order=_trade_view(trade),
        )
        # Mark before the call: ib_async may emit PendingCancel synchronously.
        # An ambiguous/failed request must never be resent by emergency cleanup.
        requested.add(ref)
        client.cancelOrder(trade.order)
    await _wait_status(
        trade,
        TERMINAL,
        deadline,
        cancel_requested=True,
        events=events,
        callback_halts=callback_halts,
    )
    _event(events, "cancel confirmed", order=_trade_view(trade))


async def _observe_b_expiry(
    client: Any, trade: Any, events: list[dict[str, Any]], cancel_requests: set[str]
) -> None:
    requested = _now().isoformat()
    async with asyncio.timeout(EVIDENCE_TIMEOUT_SECONDS):
        completed = await client.reqCompletedOrdersAsync(False)
    if completed is None:
        raise RuntimeError("IBKR completed-order response unavailable at expiry observation")
    matching = [
        row
        for row in completed
        if str(row.order.orderRef) == str(trade.order.orderRef)
        or (trade.order.permId and row.order.permId == trade.order.permId)
    ]
    script_cancel = str(trade.order.orderRef) in cancel_requests
    states = {trade.orderStatus.status, *(row.orderStatus.status for row in matching)}
    _event(
        events,
        "B GTD expiry observation",
        expected_expiry_aedt="2026-10-27T10:15:00+11:00",
        completed_requested_at_aedt=requested,
        status=trade.orderStatus.status,
        completed_orders=[{"order": _trade_view(row), "repr": repr(row)} for row in matching],
        script_cancel_requested=script_cancel,
        terminal_without_script_cancel=not script_cancel and bool(states & TERMINAL),
        expired_without_script_cancellation=not script_cancel and bool(states & CANCELLED),
    )


def _owned_orders_only(orders: list[Any], refs: set[str]) -> None:
    if any(str(row.order.orderRef) not in refs for row in orders):
        raise RuntimeError("unrelated working order appeared")


async def _run(
    session: date, out_dir: Path, approval_file: Path, approval_sha256: str, execute: bool
) -> int:
    _session_window(session)
    if not execute:
        raise ValueError("--execute is required; there is no implicit run")
    account = _load_approval(approval_file, approval_sha256)
    output = _safe_output_dir(out_dir)
    _claim_attempt(output)
    raw = IB()
    client = _ExactAccountGateway(raw, account)
    events: list[dict[str, Any]] = []
    buys: list[Any] = []
    known_trades: list[Any] = []
    refs = {f"gtd-20261027-{label}" for label in ("A", "B")}
    cancel_requests: set[str] = set()
    callback_halts: list[str] = []
    sell_attempted = False
    error: str | None = None
    try:
        await raw.connectAsync("127.0.0.1", 4002, clientId=1, readonly=False, timeout=15)
        _exact_account(client)
        _event(events, "connected", account=account, host="127.0.0.1", port=4002)
        positions, orders = await _book(client, events, "initial book")
        if any(Decimal(str(row.position)) != 0 for row in positions) or orders:
            raise RuntimeError("probe requires flat account and no working order")
        qualified = await client.qualifyContractsAsync(
            Stock("BHP", "SMART", "AUD", primaryExchange="ASX")
        )
        if len(qualified) != 1 or qualified[0].symbol != "BHP" or qualified[0].currency != "AUD":
            raise RuntimeError("BHP ASX contract qualification failed")
        contract = qualified[0]
        bars = await client.reqHistoricalDataAsync(
            contract,
            endDateTime="20261027 09:30:00 Australia/Sydney",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            keepUpToDate=False,
            timeout=30,
        )
        close = _prior_close(bars)
        limits = _orders_from_close(close)
        _event(
            events,
            "prior IBKR TRADES close",
            session=PRIOR_SESSION.isoformat(),
            close=str(close),
            limits=[(str(price), qty) for price, qty in limits],
        )
        _session_window(session)

        def check_callback(trade: Any) -> None:
            if str(trade.order.orderRef) not in refs:
                return
            try:
                _check_pre_expiry([trade], _now(), cancel_requests)
            except RuntimeError as exc:
                if not callback_halts:
                    callback_halts.append(str(exc))
                    _event(
                        events, "callback halt latched", reason=str(exc), order=_trade_view(trade)
                    )

        def on_status(trade: Any) -> None:
            if str(trade.order.orderRef) in refs or str(trade.order.orderRef) in {
                "gtd-20261027-exit",
                "gtd-20261027-emergency",
            }:
                _event(events, "status", order=_trade_view(trade))
                check_callback(trade)

        def on_execution(trade: Any, fill: Any) -> None:
            if str(trade.order.orderRef) in refs or str(trade.order.orderRef) in {
                "gtd-20261027-exit",
                "gtd-20261027-emergency",
            }:
                _event(
                    events,
                    "execution",
                    order=_trade_view(trade),
                    exec_id=str(fill.execution.execId),
                )
                check_callback(trade)

        raw.orderStatusEvent += on_status
        raw.execDetailsEvent += on_execution
        for label, (limit, quantity) in zip(("A", "B"), limits, strict=True):
            order = _buy_order(quantity, limit, account, f"gtd-20261027-{label}")
            trade = client.placeOrder(contract, order)
            buys.append(trade)
            known_trades.append(trade)
            _event(events, "buy transmitted", label=label, order=_trade_view(trade))
        for trade in buys:
            await _wait_status(
                trade,
                frozenset({"PreSubmitted", "Submitted"}),
                time(9, 55),
                callback_halts=callback_halts,
            )
        _event(events, "preopen acceptance", orders=[_trade_view(trade) for trade in buys])
        await _wait_until(time(10, 15, 30), buys, client, events, callback_halts)
        await _observe_b_expiry(client, buys[1], events, cancel_requests)
        _raise_callback_halt(callback_halts)
        await _wait_until(time(10, 16), buys, client, events, callback_halts)
        await _observe_b_expiry(client, buys[1], events, cancel_requests)
        _raise_callback_halt(callback_halts)
        _event(events, "post-auction statuses", orders=[_trade_view(trade) for trade in buys])
        for trade in buys:
            await _cancel_live_buy(
                client, trade, events, cancel_requests, callback_halts=callback_halts
            )
        positions, orders = await _book(client, events, "after 10:16 cancellation")
        _owned_orders_only(orders, refs)
        if orders:
            raise RuntimeError("live buy remainder after cancellation")
        await _wait_until(time(10, 30), callback_halts=callback_halts)
        positions, orders = await _book(client, events, "before exit")
        if orders:
            raise RuntimeError("working buy remains before exit")
        await _wait_fill_details(buys, time(10, 31))
        await _record_execution_times(
            client, events, {str(fill.execution.execId) for row in buys for fill in row.fills}
        )
        _raise_callback_halt(callback_halts)
        _check_pre_expiry(buys, _now(), cancel_requests)
        qty = _exit_quantity(
            _fill_count(buys[0]), _fill_count(buys[1]), _held(positions, account, contract.conId)
        )
        if qty:
            sell = MarketOrder("SELL", qty, tif="DAY")
            sell.account = account
            sell.orderRef = "gtd-20261027-exit"
            sell_attempted = True
            sale = client.placeOrder(contract, sell)
            known_trades.append(sale)
            _event(events, "exit transmitted", order=_trade_view(sale))
            await _wait_status(sale, frozenset({"Filled"}), time(11, 0))
            await _wait_fill_details([sale], time(11, 0))
            if _fill_count(sale) != qty:
                raise RuntimeError("exit fills do not match attributable probe shares")
            _event(events, "exit filled", order=_trade_view(sale))
            await _record_execution_times(
                client,
                events,
                {str(fill.execution.execId) for row in known_trades for fill in row.fills},
            )
            _raise_callback_halt(callback_halts)
        positions, orders = await _book(client, events, "final book")
        if _held(positions, account, contract.conId) or orders:
            raise RuntimeError("paper account did not return flat")
        _event(events, "flat confirmed")
    except Exception as exc:  # noqa: BLE001 - write complete halt evidence
        error = repr(exc)
        _event(events, "halt", reason=error)
        # Bounded emergency cleanup acts on this probe's orders and shares only.
        if raw.isConnected() and buys:
            try:
                for trade in buys:
                    await _cancel_live_buy(
                        client, trade, events, cancel_requests, deadline=time(11, 0), emergency=True
                    )
                positions, orders = await _book(client, events, "emergency book")
                _owned_orders_only(orders, refs)
                if orders:
                    raise RuntimeError("emergency buys still working; no sale attempted")
                if not sell_attempted:
                    await _wait_fill_details(buys, time(11, 0))
                    qty = _exit_quantity(
                        sum(_fill_count(trade) for trade in buys),
                        0,
                        _held(positions, account, buys[0].contract.conId),
                    )
                    if qty:
                        emergency_order = MarketOrder("SELL", qty, tif="DAY")
                        emergency_order.account = account
                        emergency_order.orderRef = "gtd-20261027-emergency"
                        sell_attempted = True
                        trade = client.placeOrder(buys[0].contract, emergency_order)
                        known_trades.append(trade)
                        _event(events, "emergency exit transmitted", order=_trade_view(trade))
                        await _wait_status(trade, frozenset({"Filled"}), time(11, 0))
                        await _wait_fill_details([trade], time(11, 0))
                        _event(events, "emergency exit result", order=_trade_view(trade))
                        await _record_execution_times(
                            client,
                            events,
                            {
                                str(fill.execution.execId)
                                for row in known_trades
                                for fill in row.fills
                            },
                        )
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures
                _event(events, "emergency halt", reason=repr(cleanup_exc))
    finally:
        if raw.isConnected():
            try:
                await _book(client, events, "independent final book")
                await _record_execution_times(
                    client,
                    events,
                    {str(fill.execution.execId) for row in known_trades for fill in row.fills},
                )
                _raise_callback_halt(callback_halts)
            except Exception as exc:  # noqa: BLE001
                _event(events, "final book unavailable", reason=repr(exc))
                error = error or repr(exc)
            raw.disconnect()
        path, digest = _write_raw(
            output,
            "gtd-auction-paper",
            {"session": session.isoformat(), "events": events, "error": error},
        )
        print(f"GTD auction paper probe: {path}\nSHA-256: {digest}\nresult: {error or 'flat'}")
    return 1 if error else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        _run(args.session, args.out_dir, args.approval_file, args.approval_sha256, args.execute)
    )


if __name__ == "__main__":
    raise SystemExit(main())
