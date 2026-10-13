"""Exercise QAT's existing stop and market paths on a bounded paper parcel.

This script is deliberately separate from the rejected opening-auction intent.
It accepts only BHP.AX on the paper Gateway, only during the nominated ASX
session, and only with ``--execute``. It refuses an existing BHP holding or
order, checks the DU account before any data or order request, and saves the
broker responses outside Git. A failed cancel is never treated as permission
to sell against a potentially resting stop.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phase3_daily_history_probe import (  # noqa: E402
    _checked_account,
    _paper_target,
    _safe_output_dir,
    _write_raw,
)

from qat.config import Settings  # noqa: E402
from qat.data.broker.adapter import Order  # noqa: E402
from qat.data.broker.ib_adapter import IBAdapter  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402
from qat.data.broker.ticks import tick_size  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
SYMBOL = "BHP.AX"
BROKER_SYMBOL = "BHP"
MAX_NOTIONAL = Decimal("800")
MIN_PARCEL = Decimal("500")
WORKING = frozenset({"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted", "PendingCancel"})


class _GuardedGateway:
    """Recheck DU immediately before each adapter or script Gateway request."""

    def __init__(self, raw: Any) -> None:
        object.__setattr__(self, "_raw", raw)

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._raw, name)
        if not callable(method) or not (
            name.startswith("req")
            or name in {"placeOrder", "cancelOrder", "qualifyContractsAsync", "whatIfOrderAsync"}
        ):
            return method

        def checked(*args: Any, **kwargs: Any) -> Any:
            _checked_account(self._raw)
            return method(*args, **kwargs)

        return checked

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._raw, name, value)


def _session_window(session: date) -> None:
    now = datetime.now(SYDNEY)
    if session != date(2026, 10, 14):
        raise ValueError("paper order probe is authorised only for 14 October 2026")
    if now.date() != session or now.weekday() >= 5 or not time(10, 30) <= now.time() <= time(15, 0):
        raise ValueError("paper order probe requires the nominated ASX session, 10:30–15:00 Sydney")


def _parcel(reference: Decimal) -> int:
    if not reference.is_finite() or reference <= 0:
        raise ValueError("no usable current BHP price for the minimum parcel")
    quantity = int((MIN_PARCEL / reference).to_integral_value(rounding=ROUND_UP))
    if quantity * reference > MAX_NOTIONAL:
        raise ValueError("minimum parcel would exceed AUD 800")
    return quantity


def _stop_prices(reference: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    tick = tick_size(reference, "ASX")
    first = ((reference * Decimal("0.90")) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return first, first + tick, first + 2 * tick


def _require_full_holding(held: float, quantity: int, stage: str) -> None:
    if held != quantity:
        raise RuntimeError(f"unexpected broker holding {stage}: {held} versus {quantity} shares")


def _rescue_quantity(held: float, planned: int, bought: float) -> int:
    if not math.isfinite(held) or held != int(held):
        raise RuntimeError(f"fractional or invalid paper holding requires manual action: {held}")
    if not math.isfinite(bought) or bought != int(bought) or bought < 0:
        raise RuntimeError(f"invalid broker buy fill requires manual action: {bought}")
    return min(int(held), planned, int(bought))


async def _qualified_bhp_contract(client: Any) -> Any:
    _checked_account(client)
    contracts = await client.qualifyContractsAsync(to_ib_contract(SYMBOL, "ASX"))
    if len(contracts) != 1:
        raise RuntimeError("BHP ASX contract could not be uniquely qualified")
    contract = contracts[0]
    con_id = int(contract.conId)
    if (
        con_id <= 0
        or contract.symbol != BROKER_SYMBOL
        or contract.primaryExchange != "ASX"
        or contract.currency != "AUD"
    ):
        raise RuntimeError("qualified BHP contract is not the expected ASX stock")
    return contract


async def _reference_quote(
    client: Any, contract: Any, *, now: datetime | None = None, wait_seconds: float = 5.0
) -> dict[str, Decimal | int | str]:
    """Require a source-dated type-3 last price before sizing any paper order."""
    _checked_account(client)
    ticker = client.reqMktData(contract, "", False, False)
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            observed = now or datetime.now(UTC)
            data_type = getattr(ticker, "marketDataType", None)
            source = getattr(ticker, "delayedLastTimestamp", None)
            last = getattr(ticker, "last", math.nan)
            try:
                price = Decimal(repr(last)) if isinstance(last, float) else Decimal(str(last))
            except (ValueError, TypeError):
                price = Decimal("NaN")
            if (
                data_type == 3
                and isinstance(source, datetime)
                and source.tzinfo is not None
                and price.is_finite()
                and price > 0
            ):
                age = observed.astimezone(UTC) - source.astimezone(UTC)
                if timedelta(0) <= age <= timedelta(minutes=30):
                    return {
                        "price": price,
                        "market_data_type": data_type,
                        "source_timestamp": source.isoformat(),
                        "observed_timestamp": observed.isoformat(),
                        "age_seconds": int(age.total_seconds()),
                    }
            if loop.time() >= deadline:
                raise ValueError(
                    "BHP delayed quote lacks type 3, a source timestamp, a positive finite "
                    "price, or age within 30 minutes"
                )
            await asyncio.sleep(0.1)
    finally:
        _checked_account(client)
        client.cancelMktData(contract)


def _position_row(row: Any) -> dict[str, str]:
    return {
        "account": str(row.account),
        "con_id": str(row.contract.conId),
        "symbol": str(row.contract.symbol),
        "exchange": str(getattr(row.contract, "exchange", "")),
        "primary_exchange": str(getattr(row.contract, "primaryExchange", "")),
        "quantity": str(row.position),
    }


async def _positions(client: Any, con_id: int, events: list[dict[str, Any]]) -> float:
    _checked_account(client)
    request_rows = await client.reqPositionsAsync()
    if request_rows is None:
        raise RuntimeError("broker positions query failed")
    _checked_account(client)
    account = client.managedAccounts()[0]
    cache_rows = list(client.positions())
    matched = [
        row for row in cache_rows if row.account == account and int(row.contract.conId) == con_id
    ]
    events.append(
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "event": "position rows",
            "qualified_con_id": str(con_id),
            "request_rows": [_position_row(row) for row in request_rows],
            "cache_rows": [_position_row(row) for row in cache_rows],
            "matched_rows": [_position_row(row) for row in matched],
        }
    )
    if len(matched) > 1:
        raise RuntimeError("keyed broker position cache returned duplicate BHP contract rows")
    return float(matched[0].position) if matched else 0.0


async def _open_bhp_orders(client: Any) -> list[Any]:
    _checked_account(client)
    rows = await client.reqAllOpenOrdersAsync()
    if rows is None:
        raise RuntimeError("broker open-orders query failed")
    return [
        trade
        for trade in rows
        if trade.contract.symbol == BROKER_SYMBOL and trade.orderStatus.status in WORKING
    ]


def _order_view(trade: Any) -> dict[str, str]:
    return {
        "broker_order_id": str(trade.order.orderId),
        "broker_perm_id": str(trade.order.permId),
        "order_ref": str(trade.order.orderRef),
        "order_type": str(trade.order.orderType),
        "tif": str(trade.order.tif),
        "side": str(trade.order.action),
        "quantity": str(trade.order.totalQuantity),
        "stop_price": str(trade.order.auxPrice),
        "status": str(trade.orderStatus.status),
        "filled": str(trade.orderStatus.filled),
        "average_fill_price": str(trade.orderStatus.avgFillPrice),
        "why_held": str(getattr(trade.orderStatus, "whyHeld", "")),
    }


def _record_trade(client: Any, ref: str, event: str, events: list[dict[str, Any]]) -> None:
    """Snapshot cached IBKR trade status, IDs and executions after each step."""
    matches = [trade for trade in client.trades() if str(trade.order.orderRef) == ref]
    trade = matches[-1] if matches else None
    events.append(
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "event": event,
            "order_ref": ref,
            "broker_order": _order_view(trade) if trade is not None else None,
            "fills": (
                [
                    {
                        "time": str(fill.time),
                        "execution_time": str(fill.execution.time),
                        "execution_time_repr": repr(fill.execution.time),
                        "execution_time_type": type(fill.execution.time).__name__,
                        "execution_time_tzinfo": str(getattr(fill.execution.time, "tzinfo", None)),
                        "receipt_time": str(fill.time),
                        "receipt_time_type": type(fill.time).__name__,
                        "receipt_time_tzinfo": str(getattr(fill.time, "tzinfo", None)),
                        "price": str(fill.execution.price),
                        "shares": str(fill.execution.shares),
                        "execution_id": str(fill.execution.execId),
                        "commission": (
                            str(fill.commissionReport.commission)
                            if getattr(fill, "commissionReport", None) is not None
                            else "not returned"
                        ),
                        "commission_currency": (
                            str(fill.commissionReport.currency)
                            if getattr(fill, "commissionReport", None) is not None
                            else "not returned"
                        ),
                    }
                    for fill in trade.fills
                ]
                if trade is not None
                else []
            ),
            "status_log": (
                [
                    {
                        "time": str(entry.time),
                        "status": str(entry.status),
                        "message": str(entry.message),
                        "error_code": str(entry.errorCode),
                    }
                    for entry in trade.log
                ]
                if trade is not None
                else []
            ),
        }
    )


async def _watch_perm_id(
    client: Any, ref: str, seconds: int = 30, started_at: float | None = None
) -> dict[str, str]:
    """Observe the cached broker identity without making another Gateway request."""
    loop = asyncio.get_running_loop()
    start = loop.time() if started_at is None else started_at
    deadline = start + seconds
    while True:
        matches = [trade for trade in client.trades() if str(trade.order.orderRef) == ref]
        if len(matches) == 1 and int(matches[0].order.permId) > 0:
            return {
                "perm_id": str(matches[0].order.permId),
                "at_utc": datetime.now(UTC).isoformat(),
                "elapsed_seconds": str(loop.time() - start),
            }
        remaining = deadline - loop.time()
        if remaining <= 0:
            return {
                "perm_id": "not observed",
                "at_utc": datetime.now(UTC).isoformat(),
                "elapsed_seconds": str(loop.time() - start),
            }
        await asyncio.sleep(min(0.05, remaining))


async def _wait_for_position(
    client: Any, con_id: int, events: list[dict[str, Any]], positive: bool, seconds: int = 90
) -> float:
    for _ in range(seconds):
        quantity = await _positions(client, con_id, events)
        if (quantity > 0) == positive:
            return quantity
        await asyncio.sleep(1)
    raise TimeoutError("paper position did not reach the expected state in 90 seconds")


async def _wait_for_stop(
    client: Any,
    ref: str,
    price: Decimal | None,
    seconds: int = 30,
    since: datetime | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        matches = [
            trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == ref
        ]
        if price is None and not matches:
            cached = [trade for trade in client.trades() if str(trade.order.orderRef) == ref]
            if len(cached) == 1 and cached[0].orderStatus.status in {"Cancelled", "ApiCancelled"}:
                return
        if price is not None and len(matches) == 1:
            trade = matches[0]
            order = trade.order
            if (
                order.orderType == "STP"
                and order.action == "SELL"
                and order.tif == "GTC"
                and Decimal(str(order.auxPrice)) == price
                and trade.orderStatus.status in {"PreSubmitted", "Submitted"}
                and (
                    since is None
                    or any(
                        entry.status in {"PreSubmitted", "Submitted"}
                        and isinstance(entry.time, datetime)
                        and entry.time.tzinfo is not None
                        and entry.time >= since
                        for entry in trade.log
                    )
                )
            ):
                return
        remaining = deadline - loop.time()
        if remaining <= 0:
            if price is None:
                raise TimeoutError("paper protective stop cancellation was not confirmed")
            raise TimeoutError("paper protective stop price was not acknowledged by IBKR")
        await asyncio.sleep(min(1, remaining))


async def _cancel_ref(
    client: Any, adapter: IBAdapter, ref: str, events: list[dict[str, Any]]
) -> None:
    matches = [
        trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == ref
    ]
    if not matches:
        return
    try:
        _checked_account(client)
        await adapter.cancel_order(ref)
        events.append({"event": "adapter cancellation requested", "order_ref": ref})
    except Exception as exc:  # noqa: BLE001 - unregistered pending orders still need cancellation
        events.append(
            {"event": "adapter cancellation failed", "order_ref": ref, "error": repr(exc)}
        )
        for trade in matches:
            _checked_account(client)
            client.cancelOrder(trade.order)
        events.append({"event": "direct cancellation requested", "order_ref": ref})
    await _wait_for_stop(client, ref, None)


async def _cleanup(
    client: Any,
    adapter: IBAdapter,
    con_id: int,
    buy_ref: str,
    stop_ref: str,
    sell_ref: str,
    planned_quantity: int,
    events: list[dict[str, Any]],
) -> None:
    """Cancel pending exposure; never sell while a protective stop may rest."""
    for ref in (buy_ref, sell_ref):
        await _cancel_ref(client, adapter, ref, events)
    held = await _positions(client, con_id, events)
    stop_working = any(
        str(trade.order.orderRef) == stop_ref for trade in await _open_bhp_orders(client)
    )
    if not held:
        await _cancel_ref(client, adapter, stop_ref, events)
        return
    if stop_working:
        try:
            await _cancel_ref(client, adapter, stop_ref, events)
        except Exception as exc:  # noqa: BLE001 - do not sell against uncertain protection
            events.append({"event": "stop cancellation unconfirmed", "error": repr(exc)})
            events.append(
                {
                    "event": "protected paper position remains; manual close required",
                    "quantity": str(held),
                }
            )
            return
        if any(str(trade.order.orderRef) == stop_ref for trade in await _open_bhp_orders(client)):
            raise RuntimeError("stop remains working after cancellation confirmation")
        held = await _positions(client, con_id, events)
        if not held:
            return
    exit_trades = [
        trade for trade in client.trades() if str(trade.order.orderRef) in {stop_ref, sell_ref}
    ]
    if any(
        float(trade.orderStatus.filled) > 0
        or trade.orderStatus.status not in {"Cancelled", "ApiCancelled", "Inactive"}
        for trade in exit_trades
    ):
        events.append(
            {
                "event": "sale fill precedes position reconciliation",
                "quantity": str(held),
                "exit_order_refs": [str(trade.order.orderRef) for trade in exit_trades],
            }
        )
        return
    buy_trades = [trade for trade in client.trades() if str(trade.order.orderRef) == buy_ref]
    if len(buy_trades) != 1:
        raise RuntimeError("buy fill identity unavailable; manual paper cleanup required")
    rescue_quantity = _rescue_quantity(
        held, planned_quantity, float(buy_trades[0].orderStatus.filled)
    )
    if rescue_quantity <= 0:
        raise RuntimeError("no confirmed probe-owned shares for emergency exit")
    rescue_ref = f"{sell_ref}-rescue"
    _checked_account(client)
    result = await adapter.place_order(
        Order(symbol=SYMBOL, side="sell", quantity=rescue_quantity, order_id=rescue_ref)
    )
    events.append(
        {
            "event": "emergency market exit returned",
            "quantity": rescue_quantity,
            "raw": repr(result),
        }
    )
    _record_trade(client, rescue_ref, "emergency exit submitted", events)
    if held == rescue_quantity:
        await _wait_for_position(client, con_id, events, positive=False)
        _record_trade(client, rescue_ref, "emergency exit flat confirmed", events)


async def _run(session: date, out_dir: Path, execute: bool) -> int:
    if not execute:
        raise ValueError("explicit --execute is required for a paper order probe")
    _session_window(session)
    from ib_async import IB

    settings = Settings(
        data_dir=tempfile.mkdtemp(prefix="qat-phase3-paper-order-"),
        trading_mode="paper",
        market="ASX",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_client_id=101,
    )
    _paper_target(settings)
    client = _GuardedGateway(IB())
    adapter = IBAdapter(client, EventBus(), settings=settings, read_only=False)
    events: list[dict[str, Any]] = []

    def record_api_error(*values: object) -> None:
        events.append(
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "event": "Gateway API error",
                "raw": repr(values),
            }
        )

    client.errorEvent += record_api_error
    error: str | None = None
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    buy_ref = f"phase3-paper-buy-{run_id}"
    stop_ref = f"phase3-paper-stop-{run_id}"
    sell_ref = f"phase3-paper-sell-{run_id}"
    connected = False
    paper_verified = False
    probe_exposure_started = False
    con_id: int | None = None
    planned_quantity = 0
    try:
        await adapter.connect()
        connected = True
        _checked_account(client)
        paper_verified = True
        events.append({"at_utc": datetime.now(UTC).isoformat(), "event": "DU account verified"})
        contract = await _qualified_bhp_contract(client)
        con_id = int(contract.conId)
        if await _positions(client, con_id, events) != 0 or await _open_bhp_orders(client):
            raise ValueError("BHP already has a holding or working order; refusing probe")
        quote = await _reference_quote(client, contract)
        reference = quote["price"]
        assert isinstance(reference, Decimal)
        quantity = _parcel(reference)
        planned_quantity = quantity
        first_stop, raised_stop, second_stop = _stop_prices(reference)
        events.append(
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "event": "bounded order plan",
                "reference": str(reference),
                "reference_market_data_type": quote["market_data_type"],
                "reference_source_timestamp": quote["source_timestamp"],
                "reference_observed_timestamp": quote["observed_timestamp"],
                "reference_age_seconds": quote["age_seconds"],
                "quantity": str(quantity),
                "first_stop": str(first_stop),
                "raised_stop": str(raised_stop),
                "second_stop": str(second_stop),
            }
        )
        probe_exposure_started = True
        _checked_account(client)
        buy = await adapter.place_order(
            Order(symbol=SYMBOL, side="buy", quantity=quantity, order_id=buy_ref)
        )
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "buy returned", "raw": repr(buy)}
        )
        _record_trade(client, buy_ref, "buy submitted", events)
        held = await _wait_for_position(client, con_id, events, positive=True)
        _record_trade(client, buy_ref, "buy holding confirmed", events)
        _require_full_holding(held, quantity, "after buy")
        if any(str(trade.order.orderRef) == buy_ref for trade in await _open_bhp_orders(client)):
            raise RuntimeError("buy order remains working after holding confirmation")
        _checked_account(client)
        stop = await adapter.place_order(
            Order(
                symbol=SYMBOL,
                side="sell",
                quantity=int(held),
                order_id=stop_ref,
                order_type="stop",
                stop_price=float(first_stop),
            )
        )
        await _wait_for_stop(client, stop_ref, first_stop)
        events.append(
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "event": "GTC stop confirmed",
                "raw": repr(stop),
            }
        )
        _record_trade(client, stop_ref, "GTC stop broker state", events)
        for stage, stop_price in (("first", raised_stop), ("second", second_stop)):
            _checked_account(client)
            changed_at = datetime.now(UTC)
            await adapter.modify_order(stop_ref, stop_price=float(stop_price))
            try:
                await _wait_for_stop(client, stop_ref, stop_price, seconds=30, since=changed_at)
            finally:
                _record_trade(client, stop_ref, f"{stage} modification broker state", events)
            events.append(
                {
                    "at_utc": datetime.now(UTC).isoformat(),
                    "event": f"{stage} raised stop acknowledged",
                    "acknowledged_price": str(stop_price),
                }
            )
        _checked_account(client)
        await adapter.cancel_order(stop_ref)
        await _wait_for_stop(client, stop_ref, None)
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "stop cancellation confirmed"}
        )
        _record_trade(client, stop_ref, "cancelled stop broker state", events)
        held = await _positions(client, con_id, events)
        if held:
            _require_full_holding(held, quantity, "before exit")
            _checked_account(client)
            loop = asyncio.get_running_loop()
            submitted_at = loop.time()
            perm_id_task = asyncio.create_task(
                _watch_perm_id(client, sell_ref, started_at=submitted_at)
            )
            try:
                sell = await adapter.place_order(
                    Order(symbol=SYMBOL, side="sell", quantity=int(held), order_id=sell_ref)
                )
                events.append(
                    {
                        "at_utc": datetime.now(UTC).isoformat(),
                        "event": "exit permId arrival",
                        **(await perm_id_task),
                    }
                )
            finally:
                if not perm_id_task.done():
                    perm_id_task.cancel()
            events.append(
                {
                    "at_utc": datetime.now(UTC).isoformat(),
                    "event": "market exit returned",
                    "raw": repr(sell),
                }
            )
            _record_trade(client, sell_ref, "market exit submitted", events)
            await _wait_for_position(client, con_id, events, positive=False)
            _record_trade(client, sell_ref, "market exit flat confirmed", events)
        if await _positions(client, con_id, events) != 0 or await _open_bhp_orders(client):
            raise RuntimeError("paper probe ended with a holding or working BHP order")
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "flat and no open BHP order"}
        )
    except Exception as exc:  # noqa: BLE001 - preserve failure as raw probe evidence
        error = f"{type(exc).__name__}: {exc}"
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "probe failed", "error": error}
        )
        if connected and paper_verified and probe_exposure_started and con_id is not None:
            try:
                await _cleanup(
                    client,
                    adapter,
                    con_id,
                    buy_ref,
                    stop_ref,
                    sell_ref,
                    planned_quantity,
                    events,
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failure reports
                events.append(
                    {
                        "event": "cleanup failed; operator action required",
                        "error": repr(cleanup_exc),
                    }
                )
    finally:
        if connected:
            try:
                if con_id is None:
                    raise RuntimeError("BHP ASX contract was not qualified")
                events.append(
                    {
                        "at_utc": datetime.now(UTC).isoformat(),
                        "event": "final broker state",
                        "position": str(await _positions(client, con_id, events)),
                        "open_bhp_orders": repr(
                            [_order_view(t) for t in await _open_bhp_orders(client)]
                        ),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - do not erase original failure
                events.append({"event": "final state unavailable", "error": repr(exc)})
            await adapter.disconnect()
        path, digest = _write_raw(
            out_dir,
            "paper-stop-lifecycle",
            {
                "probe": "paper_stop_lifecycle",
                "session": str(session),
                "events": events,
                "error": error,
            },
        )
        print(f"paper order probe: {path}\nSHA-256: {digest}")
        print(f"result: {error or 'flat with no working BHP order'}")
    return 1 if error else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args.session, _safe_output_dir(args.out_dir), args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
