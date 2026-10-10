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
from datetime import UTC, date, datetime, time
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
    if now.date() != session or now.weekday() >= 5 or not time(10, 5) <= now.time() <= time(15, 0):
        raise ValueError("paper order probe requires the nominated ASX session, 10:05–15:00 Sydney")


def _parcel(reference: Decimal) -> int:
    if not reference.is_finite() or reference <= 0:
        raise ValueError("no usable current BHP price for the minimum parcel")
    quantity = int((MIN_PARCEL / reference).to_integral_value(rounding=ROUND_UP))
    if quantity * reference > MAX_NOTIONAL:
        raise ValueError("minimum parcel would exceed AUD 800")
    return quantity


def _stop_prices(reference: Decimal) -> tuple[Decimal, Decimal]:
    tick = tick_size(reference, "ASX")
    first = ((reference * Decimal("0.90")) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return first, first + tick


async def _positions(client: Any) -> float:
    _checked_account(client)
    rows = await client.reqPositionsAsync()
    if rows is None:
        raise RuntimeError("broker positions query failed")
    return sum(
        float(row.position)
        for row in rows
        if row.contract.symbol == BROKER_SYMBOL and row.account.upper().startswith("DU")
    )


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
                        "price": str(fill.execution.price),
                        "shares": str(fill.execution.shares),
                        "execution_id": str(fill.execution.execId),
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


async def _wait_for_position(client: Any, positive: bool, seconds: int = 90) -> float:
    for _ in range(seconds):
        quantity = await _positions(client)
        if (quantity > 0) == positive:
            return quantity
        await asyncio.sleep(1)
    raise TimeoutError("paper position did not reach the expected state in 90 seconds")


async def _wait_for_stop(client: Any, ref: str, price: Decimal | None, seconds: int = 20) -> None:
    for _ in range(seconds):
        matches = [
            trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == ref
        ]
        if price is None and not matches:
            return
        if price is not None and len(matches) == 1:
            order = matches[0].order
            if (
                order.orderType == "STP"
                and order.action == "SELL"
                and order.tif == "GTC"
                and Decimal(str(order.auxPrice)) == price
            ):
                return
        await asyncio.sleep(1)
    raise TimeoutError("paper protective stop state was not confirmed at the broker")


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
    buy_ref: str,
    stop_ref: str,
    sell_ref: str,
    events: list[dict[str, Any]],
) -> None:
    """Cancel pending exposure; never sell while a protective stop may rest."""
    for ref in (buy_ref, sell_ref):
        await _cancel_ref(client, adapter, ref, events)
    held = await _positions(client)
    stop_working = any(
        str(trade.order.orderRef) == stop_ref for trade in await _open_bhp_orders(client)
    )
    if not held:
        await _cancel_ref(client, adapter, stop_ref, events)
        return
    if stop_working:
        events.append(
            {
                "event": "protected paper position remains; manual close required",
                "quantity": str(held),
            }
        )
        return
    if held != int(held):
        raise RuntimeError(f"unprotected fractional paper holding requires manual action: {held}")
    rescue_ref = f"{sell_ref}-rescue"
    _checked_account(client)
    result = await adapter.place_order(
        Order(symbol=SYMBOL, side="sell", quantity=int(held), order_id=rescue_ref)
    )
    events.append({"event": "emergency market exit returned", "raw": repr(result)})
    await _wait_for_position(client, positive=False)


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
    try:
        await adapter.connect()
        connected = True
        _checked_account(client)
        paper_verified = True
        events.append({"at_utc": datetime.now(UTC).isoformat(), "event": "DU account verified"})
        if await _positions(client) != 0 or await _open_bhp_orders(client):
            raise ValueError("BHP already has a holding or working order; refusing probe")
        _checked_account(client)
        quote = await adapter.get_market_data(SYMBOL)
        reference = Decimal(str(quote.get("last", math.nan)))
        quantity = _parcel(reference)
        first_stop, raised_stop = _stop_prices(reference)
        events.append(
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "event": "bounded order plan",
                "reference": str(reference),
                "quantity": str(quantity),
                "first_stop": str(first_stop),
                "raised_stop": str(raised_stop),
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
        held = await _wait_for_position(client, positive=True)
        _record_trade(client, buy_ref, "buy holding confirmed", events)
        if held != int(held) or held > quantity:
            raise RuntimeError(f"unexpected broker holding after buy: {held}")
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
        _checked_account(client)
        await adapter.modify_order(stop_ref, stop_price=float(raised_stop))
        await _wait_for_stop(client, stop_ref, raised_stop)
        events.append({"at_utc": datetime.now(UTC).isoformat(), "event": "raised stop confirmed"})
        _record_trade(client, stop_ref, "raised stop broker state", events)
        _checked_account(client)
        await adapter.cancel_order(stop_ref)
        await _wait_for_stop(client, stop_ref, None)
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "stop cancellation confirmed"}
        )
        _record_trade(client, stop_ref, "cancelled stop broker state", events)
        held = await _positions(client)
        if held:
            if held != int(held) or held > quantity:
                raise RuntimeError(f"unexpected broker holding before exit: {held}")
            _checked_account(client)
            sell = await adapter.place_order(
                Order(symbol=SYMBOL, side="sell", quantity=int(held), order_id=sell_ref)
            )
            events.append(
                {
                    "at_utc": datetime.now(UTC).isoformat(),
                    "event": "market exit returned",
                    "raw": repr(sell),
                }
            )
            _record_trade(client, sell_ref, "market exit submitted", events)
            await _wait_for_position(client, positive=False)
            _record_trade(client, sell_ref, "market exit flat confirmed", events)
        if await _positions(client) != 0 or await _open_bhp_orders(client):
            raise RuntimeError("paper probe ended with a holding or working BHP order")
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "flat and no open BHP order"}
        )
    except Exception as exc:  # noqa: BLE001 - preserve failure as raw probe evidence
        error = f"{type(exc).__name__}: {exc}"
        events.append(
            {"at_utc": datetime.now(UTC).isoformat(), "event": "probe failed", "error": error}
        )
        if connected and paper_verified and probe_exposure_started:
            try:
                await _cleanup(client, adapter, buy_ref, stop_ref, sell_ref, events)
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
                events.append(
                    {
                        "at_utc": datetime.now(UTC).isoformat(),
                        "event": "final broker state",
                        "position": str(await _positions(client)),
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
