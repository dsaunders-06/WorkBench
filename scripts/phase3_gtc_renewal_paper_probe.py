"""One date-gated ASX paper parcel to test IBKR's GTC auto-cancel renewal.

Only the 22 October 2026 session is authorised. The broker is reached through
QAT's adapter; evidence and the adapter's probe records stay outside Git.
The A$800 bound sizes the market buy from a fresh delayed quote, not its fill.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phase3_daily_history_probe import _paper_target, _safe_output_dir, _write_raw  # noqa: E402
from phase3_paper_stop_lifecycle_probe import (  # noqa: E402
    MAX_NOTIONAL,
    SYMBOL,
    _open_bhp_orders,
    _order_view,
    _parcel,
    _positions,
    _qualified_bhp_contract,
    _record_execution_recheck,
    _record_trade,
    _reference_quote,
    _rescue_quantity,
    _stop_prices,
    _wait_for_position,
    _wait_for_stop,
)

from qat.config import Settings  # noqa: E402
from qat.data.broker.adapter import Order  # noqa: E402
from qat.data.broker.ib_adapter import IBAdapter  # noqa: E402
from qat.data.broker.pending_legs import leg_order_ref  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402

SESSION = date(2026, 10, 22)
SYDNEY = ZoneInfo("Australia/Sydney")
TERMINAL = frozenset({"Cancelled", "ApiCancelled", "Inactive", "Filled"})


def _session_window(session: date, *, now: datetime | None = None) -> None:
    current = now or datetime.now(SYDNEY)
    if current.tzinfo is None:
        raise ValueError("session clock must be timezone aware")
    local = current.astimezone(SYDNEY)
    if (
        session != SESSION
        or local.date() != SESSION
        or local.weekday() >= 5
        or not time(10, 30) <= local.time() <= time(15, 0)
    ):
        raise ValueError("GTC paper probe is pinned to 22 October 2026, 10:30–15:00 AEDT")


def _load_approval(path: Path, digest: str, operator: str) -> str:
    source = path.expanduser().resolve()
    if any((ancestor / ".git").exists() for ancestor in (source, *source.parents)):
        raise ValueError("private probe approval must stay outside Git")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("private probe approval SHA-256 differs")
    approval = json.loads(content)
    if not isinstance(approval, dict) or set(approval) != {
        "account",
        "approved_by",
        "approval_date",
        "session",
        "symbol",
        "operator",
        "quote_notional_cap_aud",
    }:
        raise ValueError("private probe approval fields differ")
    account = approval["account"]
    if (
        not isinstance(account, str)
        or not account.startswith("DU")
        or not account[2:].isalnum()
        or len(account) < 6
        or approval["approved_by"] != "DS"
        or approval["approval_date"] != "2026-10-21"
        or approval["session"] != SESSION.isoformat()
        or approval["symbol"] != SYMBOL
        or approval["operator"] != operator
        or approval["quote_notional_cap_aud"] != str(MAX_NOTIONAL)
    ):
        raise ValueError("private probe approval terms differ")
    return account


def _exact_account(client: Any) -> None:
    if list(client.managedAccounts()) != [client.expected_account]:
        raise ValueError("GTC paper probe requires exactly the approved DU account")


class _ExactAccountGateway:
    """Recheck the precise DU account before every broker request or order."""

    _REQUESTS = frozenset(
        {"placeOrder", "cancelOrder", "cancelMktData", "qualifyContractsAsync", "whatIfOrderAsync"}
    )

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

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._raw, name, value)


async def _require_flat_book(client: Any, events: list[dict[str, Any]]) -> None:
    _exact_account(client)
    positions = await client.reqPositionsAsync()
    orders = await client.reqAllOpenOrdersAsync()
    if positions is None or orders is None:
        raise RuntimeError("independent broker book is unavailable")
    events.append(
        {
            "event": "initial account book",
            "at_utc": datetime.now(UTC).isoformat(),
            "positions": [repr(row) for row in positions],
            "open_orders": [_order_view(row) for row in orders],
        }
    )
    if (
        any(row.account != client.expected_account or float(row.position) != 0 for row in positions)
        or orders
    ):
        raise RuntimeError("paper probe requires a flat DU account with no working order")


def _trade_filled(client: Any, ref: str) -> float:
    trades = [trade for trade in client.trades() if str(trade.order.orderRef) == ref]
    if len(trades) != 1:
        raise RuntimeError(f"probe order identity unavailable: {ref}")
    return float(trades[0].orderStatus.filled)


def _record_buy_fill(client: Any, ref: str, events: list[dict[str, Any]]) -> None:
    trades = [trade for trade in client.trades() if str(trade.order.orderRef) == ref]
    if len(trades) != 1 or not trades[0].fills:
        raise RuntimeError("market buy has no attributable execution")
    fills = trades[0].fills
    events.append(
        {
            "event": "actual buy fills",
            "at_utc": datetime.now(UTC).isoformat(),
            "fills": [
                {
                    "exec_id": str(fill.execution.execId),
                    "quantity": str(fill.execution.shares),
                    "price": str(fill.execution.price),
                    "time": str(fill.execution.time),
                    "commission": repr(fill.commissionReport),
                }
                for fill in fills
            ],
            "gross_notional": str(
                sum(
                    Decimal(str(fill.execution.shares)) * Decimal(str(fill.execution.price))
                    for fill in fills
                )
            ),
        }
    )


async def _record_stop_book(
    client: Any, ref: str, label: str, events: list[dict[str, Any]]
) -> None:
    matching = [
        trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == ref
    ]
    events.append(
        {
            "event": label,
            "at_utc": datetime.now(UTC).isoformat(),
            "working_stops": [
                {
                    **_order_view(trade),
                    "auto_cancel_date_raw": str(getattr(trade.order, "autoCancelDate", "")),
                }
                for trade in matching
            ],
        }
    )


async def _cancel_confirmed(
    client: Any, adapter: IBAdapter, app_order_id: str, events: list[dict[str, Any]]
) -> None:
    ref = leg_order_ref(app_order_id, "primary")
    matching = [
        trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == ref
    ]
    if len(matching) != 1:
        raise RuntimeError("expected exactly one working probe stop before cancellation")
    _exact_account(client)
    await adapter.cancel_order(app_order_id)
    await _wait_for_stop(client, ref, None)
    _record_trade(client, ref, "stop cancellation confirmed", events)


async def _emergency_exit(
    client: Any,
    adapter: IBAdapter,
    con_id: int,
    buy_id: str,
    stop_id: str,
    sell_id: str,
    planned_quantity: int,
    stop_attempted: bool,
    events: list[dict[str, Any]],
) -> None:
    """Only sell confirmed probe-owned shares after protection is gone."""
    buy_ref = leg_order_ref(buy_id, "primary")
    stop_ref = leg_order_ref(stop_id, "primary")
    sell_ref = leg_order_ref(sell_id, "primary")
    if any(str(trade.order.orderRef) == sell_ref for trade in client.trades()):
        raise RuntimeError("normal market exit was submitted; a second sale is forbidden")
    buy_open = [
        trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == buy_ref
    ]
    if buy_open:
        _exact_account(client)
        await adapter.cancel_order(buy_id)
        await _wait_for_stop(client, buy_ref, None)
    held = await _positions(client, con_id, events)
    stop_open = [
        trade for trade in await _open_bhp_orders(client) if str(trade.order.orderRef) == stop_ref
    ]
    if stop_open:
        await _cancel_confirmed(client, adapter, stop_id, events)
    else:
        known = [trade for trade in client.trades() if str(trade.order.orderRef) == stop_ref]
        if stop_attempted and not known:
            raise RuntimeError("submitted stop has no confirmed broker identity; sale refused")
        if known and (len(known) != 1 or known[0].orderStatus.status not in TERMINAL):
            raise RuntimeError(
                "probe stop identity or terminal status is uncertain; manual action required"
            )
    if await _open_bhp_orders(client):
        raise RuntimeError("a working BHP order remains; emergency sale refused")
    held = await _positions(client, con_id, events)
    if held == 0:
        return
    quantity = _rescue_quantity(held, planned_quantity, _trade_filled(client, buy_ref))
    if quantity != held or quantity <= 0:
        raise RuntimeError("holding exceeds proven probe purchase; emergency sale refused")
    rescue_id = f"{sell_id}-rescue"
    rescue_ref = leg_order_ref(rescue_id, "primary")
    _exact_account(client)
    await adapter.place_order(
        Order(symbol=SYMBOL, side="sell", quantity=quantity, order_id=rescue_id)
    )
    _record_trade(client, rescue_ref, "emergency market sale submitted", events)
    await _wait_for_position(client, con_id, events, positive=False)
    _record_trade(client, rescue_ref, "emergency market sale flat", events)


async def _perform(
    client: Any, adapter: IBAdapter, operator: str, events: list[dict[str, Any]]
) -> None:
    contract = await _qualified_bhp_contract(client)
    con_id = int(contract.conId)
    await _require_flat_book(client, events)
    quote = await _reference_quote(client, contract)
    reference = quote["price"]
    assert isinstance(reference, Decimal)
    quantity = _parcel(reference)
    if quantity * reference > MAX_NOTIONAL:
        raise ValueError("delayed-quote parcel exceeds the A$800 sizing cap")
    first_stop = _stop_prices(reference)[0]
    events.append(
        {
            "event": "approved order plan",
            "at_utc": datetime.now(UTC).isoformat(),
            "quote": {key: str(value) for key, value in quote.items()},
            "quantity": quantity,
            "quote_sized_notional": str(quantity * reference),
            "first_stop": str(first_stop),
        }
    )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    buy_id = f"gtc-probe-buy-{run_id}"
    stop_id = f"gtc-probe-stop-{run_id}"
    sell_id = f"gtc-probe-sell-{run_id}"
    buy_ref = leg_order_ref(buy_id, "primary")
    stop_ref = leg_order_ref(stop_id, "primary")
    sell_ref = leg_order_ref(sell_id, "primary")
    exposure_started = False
    stop_attempted = False
    try:
        # Qualification and a delayed quote can take time. Refuse to start
        # exposure if their responses arrive after the approved entry window.
        _session_window(SESSION)
        exposure_started = True
        _exact_account(client)
        await adapter.place_order(
            Order(symbol=SYMBOL, side="buy", quantity=quantity, order_id=buy_id)
        )
        held = await _wait_for_position(client, con_id, events, positive=True)
        if held != quantity or _trade_filled(client, buy_ref) != quantity:
            raise RuntimeError("buy did not fill the exact planned parcel")
        if any(str(t.order.orderRef) == buy_ref for t in await _open_bhp_orders(client)):
            raise RuntimeError("buy remains working after the full fill")
        _record_buy_fill(client, buy_ref, events)
        _exact_account(client)
        stop_attempted = True
        await adapter.place_order(
            Order(
                symbol=SYMBOL,
                side="sell",
                quantity=quantity,
                order_id=stop_id,
                order_type="stop",
                stop_price=float(first_stop),
            )
        )
        await _wait_for_stop(client, stop_ref, first_stop)
        _record_trade(client, stop_ref, "initial GTC stop working", events)
        await _record_stop_book(client, stop_ref, "initial stop auto-cancel date", events)
        pending_identity = await adapter.pending_identity_reason(SYMBOL)
        if pending_identity:
            raise RuntimeError(pending_identity)
        before = await adapter.plan_gtc_renewal(SYMBOL)
        if (
            before.account != client.expected_account
            or before.con_id != con_id
            or before.quantity != quantity
            or before.stop_price != float(first_stop)
            or before.oca_group
            or before.oca_type
        ):
            raise RuntimeError("broker GTC renewal plan differs from the approved probe stop")
        events.append(
            {
                "event": "GTC renewal plan",
                "at_utc": datetime.now(UTC).isoformat(),
                "plan": {**asdict(before), "auto_cancel_date": before.auto_cancel_date.isoformat()},
                "plan_sha256": before.digest,
                "operator": operator,
            }
        )
        try:
            after = await adapter.apply_approved_gtc_renewal(
                before, approved_plan_sha256=before.digest, operator=operator
            )
        finally:
            try:
                await _record_stop_book(
                    client, stop_ref, "post-modification broker stop and date", events
                )
            except Exception as snapshot_error:  # noqa: BLE001 - retain the renewal failure
                events.append(
                    {
                        "event": "post-modification stop snapshot unavailable",
                        "error": repr(snapshot_error),
                        "at_utc": datetime.now(UTC).isoformat(),
                    }
                )
        events.append(
            {
                "event": "GTC renewal result",
                "at_utc": datetime.now(UTC).isoformat(),
                "same_price": after.stop_price == before.stop_price,
                "same_order": after.order_id == before.order_id,
                "old_auto_cancel_date": before.auto_cancel_date.isoformat(),
                "new_auto_cancel_date": after.auto_cancel_date.isoformat(),
            }
        )
        _record_trade(client, stop_ref, "renewed GTC stop broker state", events)
        await _cancel_confirmed(client, adapter, stop_id, events)
        held = await _positions(client, con_id, events)
        if held != quantity:
            raise RuntimeError("probe holding changed before market exit")
        if await _open_bhp_orders(client):
            raise RuntimeError("working BHP order remains before market exit")
        _exact_account(client)
        await adapter.place_order(
            Order(symbol=SYMBOL, side="sell", quantity=quantity, order_id=sell_id)
        )
        _record_trade(client, sell_ref, "market exit submitted", events)
        await _wait_for_position(client, con_id, events, positive=False)
        _record_trade(client, sell_ref, "market exit flat", events)
        await _require_flat_book(client, events)
        await _record_execution_recheck(client, con_id, (buy_ref, sell_ref), events)
    except Exception:
        if exposure_started:
            try:
                await _emergency_exit(
                    client,
                    adapter,
                    con_id,
                    buy_id,
                    stop_id,
                    sell_id,
                    quantity,
                    stop_attempted,
                    events,
                )
            except Exception as cleanup_error:  # noqa: BLE001 - retain original failure
                events.append(
                    {
                        "event": "emergency exit halted; DS action required",
                        "error": repr(cleanup_error),
                        "at_utc": datetime.now(UTC).isoformat(),
                    }
                )
        raise


async def _run(
    session: date,
    out_dir: Path,
    operator: str,
    approval_file: Path,
    approval_sha256: str,
    execute: bool,
) -> int:
    if not execute:
        raise ValueError("explicit --execute is required")
    _session_window(session)
    if not operator.strip() or operator.strip().lower() in {"agent", "operator", "unknown"}:
        raise ValueError("a named DS operator is required")
    account = _load_approval(approval_file, approval_sha256, operator.strip())
    output = _safe_output_dir(out_dir)
    run_dir = output / "gtc-renewal-2026-10-22"
    run_dir.mkdir(exist_ok=False)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        ibkr_account_id=account,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_client_id=101,
        operator_name=operator.strip(),
        data_dir=str(run_dir / "adapter-data"),
    )
    _paper_target(settings)
    client = _ExactAccountGateway(IB(), account)
    adapter = IBAdapter(client, EventBus(), settings=settings, read_only=False)
    events: list[dict[str, Any]] = []
    error: str | None = None
    connected = False

    def on_error(*values: object) -> None:
        events.append(
            {
                "event": "Gateway API error",
                "raw": repr(values),
                "at_utc": datetime.now(UTC).isoformat(),
            }
        )

    client.errorEvent += on_error
    try:
        await adapter.connect()
        connected = True
        _exact_account(client)
        await _perform(client, adapter, operator.strip(), events)
    except Exception as exc:  # noqa: BLE001 - preserve the exact failed state
        error = f"{type(exc).__name__}: {exc}"
        events.append(
            {"event": "probe halted", "error": error, "at_utc": datetime.now(UTC).isoformat()}
        )
    finally:
        if connected:
            try:
                positions = await client.reqPositionsAsync()
                orders = await client.reqAllOpenOrdersAsync()
                events.append(
                    {
                        "event": "final broker book",
                        "at_utc": datetime.now(UTC).isoformat(),
                        "positions": [repr(row) for row in positions],
                        "open_orders": [_order_view(row) for row in orders],
                    }
                )
            except Exception as exc:  # noqa: BLE001 - preserve the halt evidence
                events.append({"event": "final broker book unavailable", "error": repr(exc)})
            await adapter.disconnect()
        path, digest = _write_raw(
            run_dir,
            "gtc-renewal-paper",
            {"session": session.isoformat(), "events": events, "error": error},
        )
        print(f"GTC renewal paper probe: {path}\nSHA-256: {digest}\nresult: {error or 'flat'}")
    return 1 if error else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        _run(
            args.session,
            args.out_dir,
            args.operator,
            args.approval_file,
            args.approval_sha256,
            args.execute,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
