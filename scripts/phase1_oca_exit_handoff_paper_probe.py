"""One private-approved 27 October BHP paper OCA handoff experiment.

Build-only until DS approves the exact commit and private approval-file hash.
Client 1 transmits; independent client 99 only reads. No QAT/OMS path is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB, ExecutionFilter, LimitOrder, MarketOrder, Stock, StopOrder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from phase3_daily_history_probe import _safe_output_dir, _write_raw  # noqa: E402

from qat.data.broker.ticks import tick_size  # noqa: E402

SESSION = date(2026, 10, 27)
SYDNEY = ZoneInfo("Australia/Sydney")
CAP = Decimal("800")
MIN_PARCEL = Decimal("500")  # Existing local paper-probe parcel convention.
ACCOUNT_SHA256 = "29e762210575a39a23ff25eb7d95e435ac13f2b86ba5609eade17b55877bad6d"
TERMINAL = frozenset({"Filled", "Cancelled", "ApiCancelled"})
WORKING = frozenset({"PreSubmitted", "Submitted"})
TIMEOUT = 10.0
STARTS = {date(2026, 10, 27): time(14, 0), date(2026, 10, 28): time(11, 30)}


class SafetyHalt(RuntimeError):
    """Account, unrelated exposure or oversell risk: no further transmission."""


class TransmissionHalt(SafetyHalt):
    """Account, foreign exposure or oversell risk: no further transmission."""


class CleanupHalt(RuntimeError):
    """An owned-order/experiment fault requires emergency settlement and exit."""


class ObservationTimeout(RuntimeError):
    """An experiment could not establish its next condition before its deadline."""


class SnapshotUnavailable(ObservationTimeout):
    """A client-99 working order lacks quantity evidence; retry without interpreting it."""


def now() -> datetime:
    return datetime.now(SYDNEY)


def session_window(session: date, current: datetime | None = None) -> None:
    value = current or now()
    if value.tzinfo is None:
        raise ValueError("aware session clock required")
    value = value.astimezone(SYDNEY)
    if (
        session not in STARTS
        or value.date() != session
        or not STARTS[session] <= value.time() < time(15, 30)
    ):
        raise ValueError(
            "OCA probe starts only 27 October 14:00–15:30 or 28 October 11:30–15:30 AEDT"
        )


def parcel(reference: Decimal) -> int:
    if not reference.is_finite() or reference <= 0:
        raise ValueError("usable IBKR reference price required")
    quantity = max(2, int((MIN_PARCEL / reference).to_integral_value(rounding=ROUND_CEILING)))
    if quantity * reference > CAP:
        raise ValueError("minimum two-part parcel exceeds A$800")
    return quantity


def load_approval(path: Path, digest: str, output: Path, session: date = SESSION) -> str:
    source, root = path.resolve(), output.resolve()
    if (
        session not in STARTS
        or source.parent != root
        or root.name != f"phase1-oca-exit-handoff-{session:%Y%m%d}"
        or source.name != "approval.json"
    ):

        raise ValueError("dedicated private OCA approval directory required")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("approval and raw evidence must stay outside Git")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("approval SHA-256 differs")
    value = json.loads(content)
    expected = {
        "approved_by": "DS",
        "session": session.isoformat(),
        "symbol": "BHP.AX",
        "operator": "DS",
        "cap_per_order_aud": "800",
    }
    if not isinstance(value, dict) or set(value) != set(expected) | {"account", "approval_date"}:
        raise ValueError("approval schema differs")
    try:
        signed = date.fromisoformat(value["approval_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("approval signing date invalid") from exc
    if not date(2026, 10, 27) <= signed <= session:
        raise ValueError("new approval must name its actual signing date, not the superseded file")
    account = value["account"]
    if (
        any(value[key] != item for key, item in expected.items())
        or not isinstance(account, str)
        or not account.startswith("DU")
        or hashlib.sha256(account.encode()).hexdigest() != ACCOUNT_SHA256
    ):
        raise ValueError("approval terms or exact paper account differ")
    return account


def claim_attempt(output: Path, session: date = SESSION) -> None:
    with (output / f"oca-revised-{session:%Y%m%d}-attempt.lock").open(
        "x", encoding="utf-8"
    ) as handle:
        handle.write(now().isoformat() + "\n")


def exact_account(ib: Any, account: str) -> None:
    if list(ib.managedAccounts()) != [account]:
        raise TransmissionHalt("exact approved paper account mismatch")


class CheckedWire:
    """Guard actual SDK wire requests, including requests inside async helpers."""

    def __init__(self, ib: Any, wire: Any, account: str, *, readonly: bool) -> None:
        self.ib, self.wire, self.account, self.readonly = ib, wire, account, readonly

    def __getattr__(self, name: str) -> Any:
        denied = {
            "placeOrder",
            "cancelOrder",
            "reqGlobalCancel",
            "reqOpenOrders",
            "reqAutoOpenOrders",
        }
        if self.readonly and name in denied:

            def refuse(*args: Any, **kwargs: Any) -> None:
                raise TransmissionHalt("client 99 cannot transmit, cancel or bind orders")

            return refuse
        method = getattr(self.wire, name)
        if callable(method) and (
            name.startswith("req") or name in {"placeOrder", "cancelOrder", "cancelMktData"}
        ):

            def checked(*args: Any, **kwargs: Any) -> Any:
                exact_account(self.ib, self.account)
                return method(*args, **kwargs)

            return checked
        return method


def view(trade: Any) -> dict[str, Any]:
    order, status = trade.order, trade.orderStatus
    return {
        "ref": str(order.orderRef),
        "order_id": order.orderId,
        "perm_id": order.permId,
        "client_id": order.clientId,
        "symbol": trade.contract.symbol,
        "action": order.action,
        "type": order.orderType,
        "oca_group": order.ocaGroup,
        "oca_type": order.ocaType,
        "quantity": str(order.totalQuantity),
        "remaining": str(status.remaining),
        "filled": str(status.filled),
        "status": status.status,
        "stop_price": str(order.auxPrice),
        "limit_price": str(order.lmtPrice),
        "fills": [repr(fill) for fill in trade.fills],
        "log": [repr(row) for row in trade.log],
        "advanced_error": str(trade.advancedError),
    }


class HandoffProbe:
    def __init__(
        self,
        trader: Any,
        reader: Any,
        contract: Any,
        account: str,
        events: list[dict[str, Any]],
        session: date = SESSION,
    ) -> None:
        self.trader, self.reader, self.contract, self.account, self.events = (
            trader,
            reader,
            contract,
            account,
            events,
        )
        self.session = session
        self.grouped_refs: dict[str, bool] = {}
        self.emergency = False
        self.cleanup_reason: CleanupHalt | None = None
        self.cleanup_sale_attempted = False
        self.halt_reason: str | None = None
        self.known: dict[str, Any] = {}
        self.cancelled: set[str] = set()
        self.terms: dict[str, tuple[Any, ...]] = {}
        self.quote_reference: Decimal | None = None
        self.delayed_requested = False
        self.final_held: int | None = None
        self.lock = asyncio.Lock()
        self.fatal: TransmissionHalt | None = None
        self.oca_type = 0
        self.group = ""
        self.stage = "preflight"
        self.planned_quantity = 0
        self.armed = False
        self.stopping = False
        self.gap_started: datetime | None = None
        self.last_poll: datetime | None = None
        self.last_positions: list[Any] | None = None
        self.final_positions: list[Any] | None = None
        self.final_observed_at: str | None = None
        self.latest: dict[str, Any] | None = None

    @staticmethod
    def order_terms(order: Any, *, grouped: bool | None = None) -> tuple[Any, ...]:
        terms = (order.action, order.orderType)
        if grouped if grouped is not None else bool(order.ocaGroup):
            terms += (order.ocaGroup, order.ocaType)
        field = {"STP": "auxPrice", "LMT": "lmtPrice"}.get(order.orderType)
        if field is None:
            return terms
        value = Decimal(str(getattr(order, field)))
        if not value.is_finite() or value <= 0:
            raise CleanupHalt("invalid used order price in terms")
        tick = tick_size(value, "ASX")
        rounded = (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        settled = tick_size(rounded, "ASX")
        rounded = (rounded / settled).to_integral_value(rounding=ROUND_HALF_UP) * settled
        return (*terms, rounded)

    def event(self, kind: str, **values: Any) -> None:
        self.events.append(
            {
                "event": kind,
                "at_aedt": now().isoformat(),
                "oca_type": self.oca_type,
                "stage": self.stage,
                **values,
            }
        )

    def guard(self) -> None:
        if self.fatal:
            raise self.fatal
        if self.cleanup_reason and not self.emergency:
            raise self.cleanup_reason
        exact_account(self.trader, self.account)
        exact_account(self.reader, self.account)

    async def read(self, method: str, *args: Any) -> Any:
        exact_account(self.reader, self.account)
        async with asyncio.timeout(TIMEOUT):
            result = await getattr(self.reader, method)(*args)
        exact_account(self.reader, self.account)
        return result

    async def poll(self) -> dict[str, Any]:
        async with self.lock:
            self.guard()
            positions = await self.read("reqPositionsAsync")
            if positions is None:
                raise ObservationTimeout("position response unavailable")
            self.last_positions = list(positions)
            orders = await self.read("reqAllOpenOrdersAsync")
            if orders is None:
                raise ObservationTimeout("open-order response unavailable")
            held = 0
            for row in positions:
                quantity = Decimal(str(row.position))
                if quantity and (
                    row.account != self.account or row.contract.conId != self.contract.conId
                ):
                    raise TransmissionHalt("unrelated position")
                if row.account == self.account and row.contract.conId == self.contract.conId:
                    if not quantity.is_finite() or quantity != int(quantity):
                        raise TransmissionHalt("oversell risk: fractional holding")
                    held += int(quantity)
            if held < 0 or held > self.planned_quantity:
                raise TransmissionHalt("oversell risk or unowned BHP quantity")
            for trade in orders:
                if trade.orderStatus.status in TERMINAL:
                    continue
                if (
                    trade.order.account != self.account
                    or trade.contract.conId != self.contract.conId
                    or trade.order.orderRef not in self.known
                    or trade.order.clientId != 1
                ):
                    raise TransmissionHalt("unrelated order")
                expected = self.known[trade.order.orderRef]
                if expected is None:
                    raise TransmissionHalt("ambiguous order acknowledgement")
                if expected.order.orderId != trade.order.orderId or (
                    expected.order.permId and expected.order.permId != trade.order.permId
                ):
                    raise TransmissionHalt("unrelated order identity")
                terms = self.terms.get(trade.order.orderRef)
                if (
                    not self.emergency
                    and terms is not None
                    and self.order_terms(
                        trade.order,
                        grouped=self.grouped_refs.get(
                            trade.order.orderRef, bool(expected.order.ocaGroup)
                        ),
                    )
                    != terms
                ):
                    self.event("changed order terms", order=view(trade))
                    raise CleanupHalt("changed order terms")
                if (
                    not self.emergency
                    and trade.order.action == "SELL"
                    and self.grouped_refs.get(trade.order.orderRef, bool(expected.order.ocaGroup))
                    and (trade.order.ocaGroup != self.group or trade.order.ocaType != self.oca_type)
                ):
                    raise CleanupHalt("changed protective OCA group/type")
            working = [trade for trade in orders if trade.orderStatus.status not in TERMINAL]
            stops = [
                trade
                for trade in working
                if trade.order.orderType == "STP"
                and trade.order.action == "SELL"
                and trade.order.ocaGroup == self.group
                and trade.orderStatus.status in WORKING
            ]
            stop_qty = sum(Decimal(str(trade.orderStatus.remaining)) for trade in stops)
            protected = bool(held and len(stops) == 1 and stop_qty == held)
            if any(
                trade.order.action == "SELL" and Decimal(str(trade.orderStatus.remaining)) > held
                for trade in working
            ):
                raise TransmissionHalt("oversell risk: live sell quantity exceeds holding")
            incomplete = [
                view(trade)
                for trade in working
                if trade.orderStatus.status in WORKING
                and Decimal(str(trade.orderStatus.remaining)) == 0
            ]
            if incomplete:
                self.latest = None
                self.event(
                    "evidence unavailable",
                    request="client99 open orders",
                    reason="working owned order has zero remaining; orderStatus unavailable",
                    orders=incomplete,
                    positions=[repr(row) for row in positions],
                    held_quantity=held,
                    protection=None,
                )
                if not self.emergency:
                    raise SnapshotUnavailable("working-order remaining quantity unavailable")
                return {
                    "held_quantity": held,
                    "orders": [view(t) for t in working],
                    "exact_stop": None,
                }
            at = now()
            if self.last_poll and (at - self.last_poll).total_seconds() > 2.5:
                self.event("poll coverage gap", seconds=(at - self.last_poll).total_seconds())
            self.last_poll = at
            snapshot = {
                "at_aedt": at.isoformat(),
                "held_quantity": held,
                "stop_working": bool(stops),
                "stop_quantity": str(stop_qty),
                "exact_stop": protected,
                "orders": [view(trade) for trade in working],
                "positions": [repr(row) for row in positions],
            }
            self.event("client99 poll", **snapshot)
            if held and not protected and self.gap_started is None:
                self.gap_started = at
                self.event("protection gap", held_quantity=held, stop_quantity=str(stop_qty))
            elif self.gap_started and (not held or protected):
                self.event(
                    "protection gap ended",
                    observed_start=self.gap_started.isoformat(),
                    observed_end=at.isoformat(),
                    interval_seconds=(at - self.gap_started).total_seconds(),
                    held_quantity=held,
                )
                self.gap_started = None
            self.latest = snapshot
            return snapshot

    async def fresh_poll(self) -> dict[str, Any]:
        end = datetime.combine(self.session, time(15, 30), SYDNEY)
        while now() < end:
            try:
                return await self.poll()
            except SnapshotUnavailable:
                await asyncio.sleep(1)
        raise ObservationTimeout("quantity evidence unavailable at 15:30")

    async def final_inventory(self) -> tuple[int, list[Any]]:
        """Read after a safety halt; never transmit or silently reuse old positions."""
        self.final_positions, self.final_observed_at, self.final_held = None, None, None
        async with self.lock:
            positions = await self.read("reqPositionsAsync")
            if positions is None:
                raise ObservationTimeout("independent final positions unavailable")
            self.final_positions = list(positions)
            self.final_observed_at = now().isoformat()
            self.event("independent final positions", positions=[repr(row) for row in positions])
            held = 0
            for row in positions:
                quantity = Decimal(str(row.position))
                if quantity and (
                    row.account != self.account or row.contract.conId != self.contract.conId
                ):
                    raise TransmissionHalt("unrelated final position")
                if row.account == self.account and row.contract.conId == self.contract.conId:
                    if not quantity.is_finite() or quantity != int(quantity):
                        raise TransmissionHalt("invalid final BHP quantity")
                    held += int(quantity)
            self.final_held = held
            orders = await self.read("reqAllOpenOrdersAsync")
            if orders is None:
                raise ObservationTimeout("independent final orders unavailable")
            working = [trade for trade in orders if trade.orderStatus.status not in TERMINAL]
            self.event(
                "independent final book",
                held_quantity=held,
                orders=[view(trade) for trade in working],
            )
            return held, working

    async def monitor(self) -> None:
        while not self.stopping:
            if self.emergency:
                await asyncio.sleep(1)
                continue
            try:
                await self.poll()
            except CleanupHalt as exc:
                self.cleanup_reason = exc
                self.event("cleanup halt", reason=str(exc))
                return
            except TransmissionHalt as exc:
                self.fatal = exc
                self.event("safety halt", reason=str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - evidence failure is an observation
                self.event("poll unavailable", reason=repr(exc))
            await asyncio.sleep(1)

    async def quote(self) -> Decimal:
        for _ in range(2):
            try:
                tickers = await self.read("reqTickersAsync", self.contract)
                self.event(
                    "IBKR snapshot response",
                    requested_type=3 if self.delayed_requested else 1,
                    tickers=[repr(ticker) for ticker in (tickers or [])],
                    reported_types=[
                        getattr(ticker, "marketDataType", None) for ticker in (tickers or [])
                    ],
                )
                if not tickers or len(tickers) != 1:
                    raise ObservationTimeout("IBKR quote unavailable")
                ticker = tickers[0]
                actual_type = getattr(ticker, "marketDataType", None)
                if type(actual_type) is not int or actual_type not in {1, 3}:
                    raise ObservationTimeout("IBKR quote type is not live or delayed")
                if actual_type == 3 and not self.delayed_requested:
                    raise ObservationTimeout(
                        "delayed quote arrived before explicit fallback selection"
                    )
                values = [Decimal(str(ticker.bid)), Decimal(str(ticker.ask))]
                if (
                    any(not item.is_finite() or item <= 0 for item in values)
                    or values[0] > values[1]
                ):
                    raise ObservationTimeout("IBKR bid/ask unavailable")
                break
            except TransmissionHalt:
                raise
            except Exception as exc:  # noqa: BLE001 - one authorised delayed-data fallback
                self.event(
                    "IBKR snapshot unavailable",
                    reason=repr(exc),
                    requested_type=3 if self.delayed_requested else 1,
                )
                if self.delayed_requested:
                    raise ObservationTimeout("IBKR delayed snapshot bid/ask unavailable") from exc
                self.guard()
                self.delayed_requested = (
                    True  # pin before an uncertain acknowledgement; never resend
                )
                self.event("market data type request", requested_type=3)
                self.reader.reqMarketDataType(3)
                exact_account(self.reader, self.account)
        stamp = ticker.time
        if (
            not isinstance(stamp, datetime)
            or stamp.tzinfo is None
            or not 0 <= (now() - stamp.astimezone(SYDNEY)).total_seconds() <= 30
        ):
            raise ObservationTimeout("IBKR quote reception timestamp unavailable/stale")
        self.event(
            "IBKR quote",
            bid=str(values[0]),
            ask=str(values[1]),
            received_at=stamp.isoformat(),
            market_data_type=ticker.marketDataType,
            requested_type=3 if self.delayed_requested else 1,
            cap_basis="quote reference, not a guaranteed market fill value",
        )
        self.quote_reference = values[1]
        return values[1]

    def entry_limit(self, reference: Decimal) -> Decimal:
        value = reference * (Decimal("1.01") if self.delayed_requested else Decimal(1))
        tick = tick_size(value, "ASX")
        result = (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        settled = tick_size(result, "ASX")
        return (result / settled).to_integral_value(rounding=ROUND_CEILING) * settled

    def place(self, order: Any, role: str, reference: Decimal) -> Any:
        self.guard()
        session_window(self.session)
        quantity = Decimal(str(order.totalQuantity))
        price = Decimal(str(order.lmtPrice)) if order.orderType == "LMT" else reference
        if not quantity.is_finite() or quantity <= 0 or quantity != int(quantity):
            raise TransmissionHalt("oversell risk: invalid order quantity")
        if not price.is_finite() or price <= 0 or quantity * price > CAP:
            raise CleanupHalt("per-order A$800 reference cap or price invalid")
        ref = f"oca-{self.session:%Y%m%d}-{self.oca_type}-{role}"
        if ref in self.known:
            raise TransmissionHalt("duplicate order request")
        order.orderRef, order.account = ref, self.account
        self.grouped_refs[ref] = bool(order.ocaGroup)
        self.terms[ref] = self.order_terms(order, grouped=self.grouped_refs[ref])
        self.known[ref] = None  # pin identity before a synchronous callback
        self.event(
            "order request",
            role=role,
            ref=ref,
            quantity=str(quantity),
            reference_price=str(price),
            reference_notional=str(quantity * price),
            order=repr(order),
        )
        try:
            trade = self.trader.placeOrder(self.contract, order)
        except Exception as exc:  # noqa: BLE001 - a possibly transmitted request is never retried
            self.fatal = TransmissionHalt("ambiguous order acknowledgement; DS action required")
            raise self.fatal from exc
        self.known[ref] = trade
        self.event("order returned", role=role, order=view(trade))
        return trade

    async def until(
        self, predicate: Any, label: str, *, deadline: datetime | None = None
    ) -> dict[str, Any]:
        end = deadline or min(
            now() + timedelta(minutes=2), datetime.combine(self.session, time(15, 30), SYDNEY)
        )
        while now() < end:
            self.guard()
            try:
                snapshot = await self.poll()
                if predicate(snapshot):
                    return snapshot
            except (TransmissionHalt, CleanupHalt):
                raise
            except Exception as exc:  # noqa: BLE001 - retry evidence, never a second order
                self.event("evidence unavailable", request=label, reason=repr(exc))
            await asyncio.sleep(1)
        raise ObservationTimeout(f"{label}: deadline reached")

    def request_cancel_once(self, trade: Any) -> None:
        ref = trade.order.orderRef
        if trade.orderStatus.status in TERMINAL:
            return
        if ref not in self.cancelled and trade.orderStatus.status not in {
            "PendingCancel",
            "Inactive",
        }:
            self.guard()
            session_window(self.session)
            self.cancelled.add(ref)
            self.event("cancel request", order=view(trade))
            try:
                self.trader.cancelOrder(trade.order)
            except TransmissionHalt:
                raise
            except Exception as exc:  # noqa: BLE001 - never resend an uncertain cancellation
                self.event("cancel acknowledgement unavailable", reason=repr(exc))

    async def cancel_once(self, trade: Any) -> None:
        self.request_cancel_once(trade)
        ref = trade.order.orderRef
        last = None
        end = datetime.combine(self.session, time(15, 30), SYDNEY)
        while now() < end:
            self.guard()
            status = trade.orderStatus.status
            if status != last:
                self.event(
                    "cancel state", order=view(trade), script_cancel_requested=ref in self.cancelled
                )
                last = status
            if status in TERMINAL:
                return
            await asyncio.sleep(1)
        raise ObservationTimeout("cancel unresolved at 15:30; no sale or resend")

    async def executions(self) -> bool:
        complete = True
        for method, label, args in (
            ("reqExecutionsAsync", "reqExecutions", (ExecutionFilter(acctCode=self.account),)),
            ("reqCompletedOrdersAsync", "completed orders", (False,)),
        ):
            try:
                rows = await self.read(method, *args)
                if rows is None:
                    raise ObservationTimeout(f"{label} unavailable")
                self.event(
                    "broker evidence",
                    source=label,
                    records=[repr(row) if label == "reqExecutions" else view(row) for row in rows],
                )
            except Exception as exc:  # noqa: BLE001 - preserve each successful response separately
                complete = False
                self.event("broker evidence unavailable", source=label, reason=repr(exc))
        return complete

    async def sell(self, quantity: int, role: str) -> Any:
        snapshot = await self.fresh_poll()
        if role == "partial" and not snapshot["exact_stop"]:
            raise ObservationTimeout("stop lost before partial handoff; full gap cleanup required")
        if quantity > snapshot["held_quantity"] or quantity <= 0:
            raise TransmissionHalt("oversell risk: sale exceeds independently observed holding")
        # A previous exit or pending leg must settle before another exit exists.
        for trade in tuple(self.known.values()):
            if (
                trade is None
                or trade.orderStatus.status in TERMINAL
                or trade.order.action != "SELL"
            ):
                continue
            if trade.orderStatus.status in {"PendingCancel", "Inactive"}:
                await self.cancel_once(trade)
            elif trade.order.orderType == "MKT":
                raise TransmissionHalt("oversell risk: another exit may still fill")
        snapshot = await self.fresh_poll()
        if quantity != min(quantity, snapshot["held_quantity"]):
            raise TransmissionHalt("oversell risk: holding changed before exit")
        reference = self.quote_reference if self.stage == "gap market cleanup" else None
        if reference is None:
            reference = await self.quote()
        # All exits join this experiment's existing group, including gap cleanup.
        final_check = await self.fresh_poll()
        if quantity > final_check["held_quantity"]:
            raise TransmissionHalt("oversell risk: holding changed during quote request")
        if role == "partial" and not final_check["exact_stop"]:
            raise ObservationTimeout("stop lost during quote; full gap cleanup required")
        order = MarketOrder("SELL", quantity, tif="DAY", ocaGroup=self.group, ocaType=self.oca_type)
        trade = self.place(order, role, reference)
        end = min(
            now() + timedelta(minutes=2), datetime.combine(self.session, time(15, 30), SYDNEY)
        )
        while now() < end:
            snapshot = await self.fresh_poll()
            if trade.orderStatus.status in TERMINAL:
                return trade
            if trade.orderStatus.filled and not snapshot["exact_stop"]:
                self.event("partial exit protection gap", order=view(trade))
                # Resolve the executable remainder before adding a cleanup sale.
                await self.cancel_once(trade)
                return trade
            await asyncio.sleep(1)
        await self.cancel_once(trade)
        return trade

    async def flat(self) -> None:
        await self.until(
            lambda snapshot: not snapshot["held_quantity"], "zero holding before leg cancellation"
        )
        for trade in tuple(self.known.values()):
            if trade is not None:
                self.request_cancel_once(trade)
        for trade in tuple(self.known.values()):
            if trade is not None and trade.orderStatus.status not in TERMINAL:
                await self.cancel_once(trade)
        await self.until(
            lambda snapshot: not snapshot["held_quantity"] and not snapshot["orders"],
            "flat/no-working-order confirmation",
        )

    async def case(self, oca_type: int) -> None:
        self.oca_type, self.group, self.armed = (
            oca_type,
            f"oca-{self.session:%Y%m%d}-type-{oca_type}",
            False,
        )
        self.stage = "case start"
        snapshot = await self.fresh_poll()
        if snapshot["held_quantity"] or snapshot["orders"]:
            raise TransmissionHalt("case start requires flat account and no working orders")
        reference = await self.quote()
        entry_limit = self.entry_limit(reference)
        self.planned_quantity = parcel(entry_limit)
        self.event(
            "entry limit",
            reference=str(reference),
            limit=str(entry_limit),
            delayed_buffer=self.delayed_requested,
            cap_per_order_aud=str(CAP),
        )
        buy = self.place(
            LimitOrder("BUY", self.planned_quantity, float(entry_limit), tif="DAY"),
            "entry",
            reference,
        )
        await self.until(
            lambda row: buy.orderStatus.status == "Filled"
            and row["held_quantity"] == self.planned_quantity,
            "entry fill",
        )
        tick = tick_size(reference, "ASX")
        stop_price = (reference * Decimal("0.90") / tick).to_integral_value(
            rounding=ROUND_FLOOR
        ) * tick
        target_price = (reference * Decimal("1.10") / tick).to_integral_value(
            rounding=ROUND_CEILING
        ) * tick
        self.stage = "initial protection"
        self.place(
            StopOrder(
                "SELL",
                self.planned_quantity,
                float(stop_price),
                tif="DAY",
                ocaGroup=self.group,
                ocaType=oca_type,
                transmit=False,
            ),
            "stop",
            reference,
        )
        self.place(
            LimitOrder(
                "SELL",
                self.planned_quantity,
                float(target_price),
                tif="DAY",
                ocaGroup=self.group,
                ocaType=oca_type,
                transmit=True,
            ),
            "target",
            reference,
        )
        await self.until(
            lambda row: row["exact_stop"]
            and len(
                [
                    order
                    for order in row["orders"]
                    if order["type"] == "LMT"
                    and order["status"] in WORKING
                    and Decimal(order["remaining"]) == row["held_quantity"]
                    and Decimal(order["quantity"]) == row["held_quantity"]
                ]
            )
            == 1,
            "both protective legs working",
        )
        self.armed, self.stage = True, "partial handoff"
        await self.sell(self.planned_quantity // 2, "partial")
        snapshot = await self.fresh_poll()
        self.stage = "second handoff" if snapshot["exact_stop"] else "gap market cleanup"
        if snapshot["held_quantity"]:
            await self.sell(snapshot["held_quantity"], "remainder")
        self.stage = "case final inventory"
        await self.flat()
        await self.executions()
        self.event(
            "case flat confirmed",
            overfill_blocking="not proven merely by absence of an observed overfill",
        )

    def own_nonterminal_orders(self, orders: list[Any] | None = None) -> list[dict[str, Any]]:
        pending = {
            ref: view(trade) if trade is not None else {"ref": ref, "status": "ack unavailable"}
            for ref, trade in self.known.items()
            if trade is None or trade.orderStatus.status not in TERMINAL
        }
        for trade in orders or []:
            if trade.order.orderRef in self.known and trade.orderStatus.status not in TERMINAL:
                pending[trade.order.orderRef] = view(trade)
        return list(pending.values())

    def check_settlement_book(self, held: int, orders: list[Any]) -> None:
        """Ownership/oversell guards remain binding even after a terms halt."""
        for trade in orders:
            expected = self.known.get(trade.order.orderRef)
            if (
                expected is None
                or trade.order.account != self.account
                or trade.contract.conId != self.contract.conId
                or trade.order.clientId != 1
                or expected.order.orderId != trade.order.orderId
                or (expected.order.permId and expected.order.permId != trade.order.permId)
            ):
                raise TransmissionHalt("unrelated order in settlement snapshot")
            if trade.order.action == "SELL" and Decimal(str(trade.orderStatus.remaining)) > held:
                raise TransmissionHalt("oversell risk during settlement")

    def attributable_holding(self) -> int:
        balance = 0
        for trade in self.known.values():
            if trade is None:
                continue
            reported = Decimal(str(trade.orderStatus.filled))
            details = sum((Decimal(str(f.execution.shares)) for f in trade.fills), Decimal(0))
            filled = max(reported, details)
            if not filled.is_finite() or filled < 0 or filled != int(filled):
                raise TransmissionHalt("oversell risk: invalid owned fill quantity")
            balance += int(filled) if trade.order.action == "BUY" else -int(filled)
        if balance < 0:
            raise TransmissionHalt("oversell risk: owned sells exceed owned buys")
        return balance

    async def wait_own_terminal(self) -> tuple[int, list[Any]]:
        """Never disconnect on a zero position while an owned order may still fill."""
        end = datetime.combine(self.session, time(15, 30), SYDNEY)
        last = None
        while now() < end:
            orders = None
            try:
                held, orders = await self.final_inventory()
                self.check_settlement_book(held, orders)
                pending = self.own_nonterminal_orders(orders)
                signature = repr(pending)
                if signature != last:
                    self.event("own terminal wait", orders=pending, held_quantity=held)
                    last = signature
                if not pending:
                    attributed = self.attributable_holding()
                    if held == attributed:
                        return held, orders
                    self.event(
                        "position/fill reconciliation pending",
                        held_quantity=held,
                        attributable_quantity=attributed,
                    )
            except Exception as exc:  # noqa: BLE001 - observe, never transmit/retry a cancel
                if isinstance(exc, TransmissionHalt):
                    self.fatal = exc
                    if not self.own_nonterminal_orders(orders):
                        raise  # foreign exposure is reported promptly once our orders settle
                self.event("terminal evidence unavailable", reason=repr(exc))
            await asyncio.sleep(1)
        self.event(
            "own terminal deadline",
            orders=self.own_nonterminal_orders(),
            held_quantity=self.final_held,
        )
        raise ObservationTimeout("own order non-terminal or snapshot unavailable at 15:30")

    async def cleanup(self) -> None:
        self.emergency = True
        self.stage = "emergency cleanup"
        self.event("emergency cleanup", reason=self.halt_reason)
        self.guard()
        # Ignore only the terms fault. Account, ownership and oversell checks still run.
        end = datetime.combine(self.session, time(15, 30), SYDNEY)
        while now() < end:
            try:
                await self.fresh_poll()
                break
            except TransmissionHalt:
                raise
            except Exception as exc:  # noqa: BLE001 - recover evidence, never resend an order
                self.event("cleanup evidence unavailable", reason=repr(exc))
                await asyncio.sleep(1)
        else:
            raise ObservationTimeout("cleanup book unavailable at 15:30")
        for trade in tuple(self.known.values()):
            if trade is not None:
                self.request_cancel_once(trade)
        held, orders = await self.wait_own_terminal()
        self.guard()
        if orders:
            raise TransmissionHalt("unrelated working order before cleanup exit")
        if held:
            if self.cleanup_sale_attempted:
                raise TransmissionHalt("oversell risk: cleanup sale already attempted")
            if now() >= datetime.combine(self.session, time(15, 30), SYDNEY):
                raise ObservationTimeout("cleanup sale cannot start at or after 15:30")
            if self.quote_reference is None:
                raise CleanupHalt("cleanup reference unavailable; DS action required")
            self.cleanup_sale_attempted = True
            # All buys and sells are terminal: one ungrouped market sale, no new stop.
            self.place(MarketOrder("SELL", held, tif="DAY"), "cleanup", self.quote_reference)
            residual, _ = await self.wait_own_terminal()
            if residual:
                self.event("emergency cleanup residual", held_quantity=residual)
                raise ObservationTimeout(
                    f"emergency sale terminal with residual {residual}; DS action required"
                )
        self.event("emergency cleanup completed", held_quantity=self.final_held)

    async def run_cases(self, *, types: tuple[int, ...] = (2, 3, 1), monitor: bool = True) -> None:
        background = asyncio.create_task(self.monitor()) if monitor else None
        try:
            for oca_type in types:
                try:
                    await self.case(oca_type)
                except TransmissionHalt:
                    raise
                except Exception as exc:  # noqa: BLE001 - observation plus bounded cleanup
                    self.halt_reason = repr(exc)
                    self.event("case observation", reason=repr(exc))
                    await self.cleanup()
                    self.event("case incomplete but flat")
                    return
        finally:
            self.stopping = True
            if background:
                background.cancel()
                await asyncio.gather(background, return_exceptions=True)


async def connect(ib: Any, account: str, client_id: int) -> None:
    # Low-level handshake receives server account identity without SDK startup requests.
    ib.wrapper.clientId = client_id
    await ib.client.connectAsync("127.0.0.1", 4002, client_id, 15)
    exact_account(ib, account)
    ib.client = CheckedWire(ib, ib.client, account, readonly=client_id == 99)


async def run(
    session: date, output: Path, approval: Path, approval_hash: str, execute: bool
) -> int:
    session_window(session)
    if not execute:
        raise ValueError("explicit --execute required; build is not approval")
    account = load_approval(approval, approval_hash, output, session)
    root = _safe_output_dir(output)
    claim_attempt(root, session)
    trader, reader, events = IB(), IB(), []
    driver = None
    error = None
    held = None
    try:
        await connect(reader, account, 99)
        await connect(trader, account, 1)
        exact_account(reader, account)
        contracts = await reader.qualifyContractsAsync(
            Stock("BHP", "SMART", "AUD", primaryExchange="ASX")
        )
        if (
            len(contracts) != 1
            or contracts[0].symbol != "BHP"
            or contracts[0].primaryExchange != "ASX"
            or contracts[0].currency != "AUD"
            or contracts[0].conId <= 0
        ):
            raise TransmissionHalt("BHP ASX contract is not uniquely qualified")
        driver = HandoffProbe(trader, reader, contracts[0], account, events, session)
        for label, ib in (("client1", trader), ("client99", reader)):
            for name in (
                "errorEvent",
                "orderStatusEvent",
                "execDetailsEvent",
                "commissionReportEvent",
            ):

                def capture(*args: Any, source: str = label, event_name: str = name) -> None:
                    driver.event(
                        "SDK event",
                        source=source,
                        name=event_name,
                        arguments=[repr(arg) for arg in args],
                    )

                getattr(ib, name).__iadd__(capture)
        await driver.run_cases()
        error = driver.halt_reason
    except Exception as exc:  # noqa: BLE001 - preserve exact safety/observation result
        error = repr(exc)
        events.append(
            {
                "event": (
                    "transmission halt" if isinstance(exc, TransmissionHalt) else "cleanup halt"
                ),
                "at_aedt": now().isoformat(),
                "reason": error,
            }
        )
        if driver:
            driver.halt_reason = error
            if isinstance(exc, TransmissionHalt):
                driver.fatal = exc
            elif not driver.emergency:
                try:
                    await driver.cleanup()
                except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures
                    events.append(
                        {
                            "event": "cleanup incomplete",
                            "at_aedt": now().isoformat(),
                            "reason": repr(cleanup_exc),
                        }
                    )
                    if isinstance(cleanup_exc, TransmissionHalt):
                        driver.fatal = cleanup_exc
    finally:
        final_orders: list[Any] = []
        final_book_available = False
        if driver:
            if driver.known:
                try:
                    await driver.wait_own_terminal()
                except Exception as exc:  # noqa: BLE001 - window-end handoff, never early exit
                    error = error or repr(exc)
            if not await driver.executions():
                error = error or "final execution/completed-order evidence incomplete"
            try:
                held, final_orders = await driver.final_inventory()
                final_book_available = True
            except Exception as exc:  # noqa: BLE001
                events.append(
                    {
                        "event": "final inventory unavailable",
                        "at_aedt": now().isoformat(),
                        "reason": repr(exc),
                    }
                )
                held = driver.final_held
                error = error or repr(exc)
            end = datetime.combine(session, time(15, 30), SYDNEY)
            # The last independent snapshot can contradict the owner's terminal
            # cache. It must be drained too; an earlier terminal check is not enough.
            while driver.own_nonterminal_orders(final_orders) and now() < end:
                driver.event(
                    "final snapshot terminal wait",
                    orders=driver.own_nonterminal_orders(final_orders),
                )
                await asyncio.sleep(1)
                try:
                    await driver.wait_own_terminal()
                except (
                    Exception
                ) as exc:  # noqa: BLE001 - retain failure, continue observing own orders
                    error = error or repr(exc)
                final_book_available = False
                try:
                    held, final_orders = await driver.final_inventory()
                    final_book_available = True
                except Exception as exc:  # noqa: BLE001 - retain the last pending order evidence
                    held = driver.final_held
                    error = error or repr(exc)
                    driver.event("final inventory unavailable", reason=repr(exc))
            if final_orders:
                error = error or "working orders remain"
        for ib in (trader, reader):
            if ib.isConnected():
                ib.disconnect()
        own_nonterminal = driver.own_nonterminal_orders(final_orders) if driver else []
        attributable = None
        if driver:
            try:
                attributable = driver.attributable_holding()
            except TransmissionHalt as exc:
                error = error or repr(exc)
        reconciled = held is not None and held == attributable
        needs_action = (
            held is None
            or held != 0
            or bool(error)
            or bool(own_nonterminal)
            or bool(final_orders)
            or not reconciled
            or not final_book_available
        )
        result = {
            "session": session.isoformat(),
            "events": events,
            "error": error,
            "held_quantity": held,
            "held_quantity_observed_at": driver.final_observed_at if driver else None,
            "ds_action_required": needs_action,
            "flat": final_book_available
            and held == 0
            and not final_orders
            and not own_nonterminal
            and reconciled,
            "final_book_available": final_book_available,
            "attributable_held_quantity": attributable,
            "position_fill_reconciled": reconciled,
            "own_nonterminal_orders": own_nonterminal,
            "production_files_changed": [],
        }
        path, digest = _write_raw(root, "oca-exit-handoff-paper", result)
        if needs_action:
            quantity = str(held) if held is not None else "unavailable"
            print(f"DS action required: held quantity {quantity} BHP.AX")
            if own_nonterminal:
                print(f"Own non-terminal orders: {own_nonterminal!r}")
        else:
            print("Independent client-99 inventory: flat; no working orders")
        print(f"Evidence: {path}\nSHA-256: {digest}\nProduction files changed: none")
    return int(needs_action)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run(args.session, args.out_dir, args.approval_file, args.approval_sha256, args.execute)
    )


if __name__ == "__main__":
    raise SystemExit(main())
