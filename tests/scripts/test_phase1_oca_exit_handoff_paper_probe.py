"""Offline OCA handoff scenarios with real ib_async orders, trades and fills."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from ib_async import (
    IB,
    CommissionReport,
    Contract,
    Execution,
    Fill,
    Order,
    OrderState,
    OrderStatus,
    Stock,
    Trade,
)
from ib_async.decoder import Decoder
from ib_async.util import UNSET_DOUBLE

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
SYDNEY = ZoneInfo("Australia/Sydney")
OBSERVED_UNGROUPED = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "ibkr_ungrouped_completed_order_shape.json"
    ).read_text()
)["order"]


def api():
    assert importlib.util.find_spec("phase1_oca_exit_handoff_paper_probe"), "handoff probe absent"
    return importlib.import_module("phase1_oca_exit_handoff_paper_probe")


def test_session_gate_and_minimum_parcel_cap():
    p = api()
    p.session_window(date(2026, 10, 27), datetime(2026, 10, 27, 14, 0, tzinfo=SYDNEY))
    for now in [
        datetime(2026, 10, 26, 12, tzinfo=SYDNEY),
        datetime(2026, 10, 27, 15, 30, tzinfo=SYDNEY),
    ]:
        with pytest.raises(ValueError):
            p.session_window(date(2026, 10, 27), now)
    assert p.parcel(Decimal("56")) == 9
    with pytest.raises(ValueError):
        p.parcel(Decimal("900"))


def test_exact_approval_hash_terms_and_dedicated_directory(tmp_path, monkeypatch):
    p = api()
    root = tmp_path / "phase1-oca-exit-handoff-20261027"
    root.mkdir()
    path = root / "approval.json"
    terms = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "approval_date": "2026-10-27",
        "session": "2026-10-27",
        "symbol": "BHP.AX",
        "operator": "DS",
        "cap_per_order_aud": "800",
    }
    path.write_text(json.dumps(terms))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(p, "ACCOUNT_SHA256", hashlib.sha256(b"DUFAKE").hexdigest())
    assert p.load_approval(path, digest, root) == "DUFAKE"
    with pytest.raises(ValueError):
        p.load_approval(path, "0" * 64, root)
    terms["session"] = "2026-10-26"
    path.write_text(json.dumps(terms))
    with pytest.raises(ValueError):
        p.load_approval(path, hashlib.sha256(path.read_bytes()).hexdigest(), root)


def test_wire_rechecks_account_and_client99_cannot_transmit():
    p = api()
    state = SimpleNamespace(accounts=["DUFAKE"], managedAccounts=lambda: state.accounts)
    wire = SimpleNamespace(
        reqPositions=lambda: None, placeOrder=lambda *args: None, cancelOrder=lambda *args: None
    )
    guard = p.CheckedWire(state, wire, "DUFAKE", readonly=True)
    guard.reqPositions()
    for name in ["placeOrder", "cancelOrder", "reqOpenOrders", "reqAutoOpenOrders"]:
        with pytest.raises(p.SafetyHalt):
            getattr(guard, name)(None)
    state.accounts = ["DUOTHER"]
    with pytest.raises(p.SafetyHalt):
        guard.reqPositions()


def test_attempt_lock_never_repeats(tmp_path):
    p = api()
    p.claim_attempt(tmp_path)
    with pytest.raises(FileExistsError):
        p.claim_attempt(tmp_path)


@pytest.fixture(params=["0", ""], ids=["unused-zero", "unused-unset"], autouse=True)
def wire_variant(request, monkeypatch):
    monkeypatch.setattr(Paper, "unused_wire_price", request.param)


class Paper:
    unused_wire_price = ""

    def __init__(
        self, clock, *, disappear=False, pending_minutes=0, wrong_quantity=False, foreign=False
    ):
        self.clock = clock
        self.disappear = disappear
        self.wrong_quantity = wrong_quantity
        self.pending_minutes = pending_minutes
        self.foreign = foreign
        self.accounts = ["DUFAKE"]
        self.held = 0
        self.trades = []
        self.executions = []
        self.cancels = []
        self.pending = {}
        self.price_drift = False
        self.incomplete_stop_polls = 0
        self.market_data_requests = []
        self.market_data_type = 1
        self.contract = Stock("BHP", "SMART", "AUD", primaryExchange="ASX", conId=42)

    def managedAccounts(self):
        return self.accounts

    def fill(self, trade, quantity):
        at = self.clock[0]
        execution = Execution(
            execId=f"fake-{len(self.executions)}",
            time=at.astimezone(UTC),
            acctNumber="DUFAKE",
            orderRef=trade.order.orderRef,
            shares=quantity,
            price=56,
            side="BOT" if trade.order.action == "BUY" else "SLD",
        )
        fill = Fill(
            self.contract,
            execution,
            CommissionReport(execId=execution.execId, commission=1, currency="AUD"),
            at,
        )
        trade.fills.append(fill)
        self.executions.append(fill)
        trade.orderStatus = OrderStatus(status="Filled", filled=quantity, remaining=0)
        self.held += quantity if trade.order.action == "BUY" else -quantity

    def placeOrder(self, contract, order):
        order.orderId = len(self.trades) + 1
        order.permId = 100 + order.orderId
        order.clientId = 1
        trade = Trade(
            contract, order, OrderStatus(status="Submitted", remaining=order.totalQuantity)
        )
        self.trades.append(trade)
        if order.action == "BUY":
            self.fill(trade, int(order.totalQuantity))
        elif order.orderType == "MKT":
            self.fill(trade, int(order.totalQuantity))
            for sibling in self.trades:
                if (
                    sibling is trade
                    or sibling.order.ocaGroup != order.ocaGroup
                    or sibling.orderStatus.status in {"Filled", "Cancelled", "ApiCancelled"}
                ):
                    continue
                if (
                    order.ocaType == 1
                    or not self.held
                    or (self.disappear and sibling.order.orderType == "STP")
                ):
                    sibling.orderStatus.status = "Cancelled"
                else:
                    quantity = self.held + (
                        1 if self.wrong_quantity and sibling.order.orderType == "STP" else 0
                    )
                    sibling.order.totalQuantity = quantity
                    sibling.orderStatus.remaining = quantity
        return trade

    def cancelOrder(self, order):
        self.cancels.append((order.orderRef, self.clock[0]))
        trade = next(t for t in self.trades if t.order is order)
        trade.orderStatus.status = "PendingCancel"
        self.pending[order.orderRef] = self.clock[0] + timedelta(minutes=self.pending_minutes)

    async def reqPositionsAsync(self):
        if self.foreign:
            return [
                SimpleNamespace(
                    account="DUFAKE", contract=Stock("OTHER", "SMART", "AUD", conId=99), position=1
                )
            ]
        return (
            [SimpleNamespace(account="DUFAKE", contract=self.contract, position=self.held)]
            if self.held
            else []
        )

    def decoded_snapshot(self, original, *, omit_status=False):
        # A disconnected IB supplies the actual decoder.parse/openOrder/orderStatus
        # machinery. Every response is a new wrapper, Trade, Order and OrderStatus.
        observer = IB()
        assert not observer.isConnected()
        owner = original.order
        wire = Order(
            orderId=str(owner.orderId),
            clientId=str(owner.clientId),
            permId=str(owner.permId),
            action=owner.action,
            orderType=owner.orderType,
            totalQuantity=str(owner.totalQuantity),
            account=owner.account,
            orderRef=owner.orderRef,
            tif=owner.tif,
            ocaGroup=owner.ocaGroup,
            # Observed IBKR value: even an ungrouped BUY/SELL returns type3.
            # Shape retained from the preserved 26Oct B completed-order record.
            ocaType=str(owner.ocaType if owner.ocaGroup else OBSERVED_UNGROUPED["ocaType"]),
            lmtPrice=str(owner.lmtPrice) if owner.orderType == "LMT" else self.unused_wire_price,
            auxPrice=str(owner.auxPrice) if owner.orderType == "STP" else self.unused_wire_price,
            displaySize=str(OBSERVED_UNGROUPED["displaySize"]),
            openClose=OBSERVED_UNGROUPED["openClose"],
            volatilityType=str(OBSERVED_UNGROUPED["volatilityType"]),
            deltaNeutralOrderType=OBSERVED_UNGROUPED["deltaNeutralOrderType"],
            referencePriceType=str(OBSERVED_UNGROUPED["referencePriceType"]),
            clearingIntent=OBSERVED_UNGROUPED["clearingIntent"],
            cashQty=str(OBSERVED_UNGROUPED["cashQty"]),
            dontUseAutoPriceForHedge="1",
        )
        if self.price_drift:
            if owner.orderType == "STP":
                wire.auxPrice = str(float(owner.auxPrice) + 0.000000000000006)
            elif owner.orderType == "LMT":
                wire.lmtPrice = str(float(owner.lmtPrice) + 0.000000000000006)
        contract = Contract(
            conId=str(original.contract.conId),
            symbol=original.contract.symbol,
            secType="STK",
            exchange="SMART",
            primaryExchange="ASX",
            currency="AUD",
        )
        decoder = Decoder(observer.wrapper, 180)
        decoder.parse(wire)
        decoder.parse(contract)
        observer.wrapper._results["openOrders"] = []
        observer.wrapper.openOrder(
            wire.orderId, contract, wire, OrderState(status=original.orderStatus.status)
        )
        if not omit_status:
            status = original.orderStatus
            observer.wrapper.orderStatus(
                wire.orderId,
                status.status,
                status.filled,
                status.remaining,
                status.avgFillPrice,
                wire.permId,
                wire.parentId,
                status.lastFillPrice,
                wire.clientId,
                status.whyHeld,
                status.mktCapPrice,
            )
        result = observer.wrapper._results["openOrders"][0]
        assert result is not original and result.order is not owner
        assert result.orderStatus is not original.orderStatus
        assert result.contract is not original.contract
        return result

    async def reqAllOpenOrdersAsync(self):
        missing = self.incomplete_stop_polls > 0
        if missing:
            self.incomplete_stop_polls -= 1
        return [
            self.decoded_snapshot(t, omit_status=missing and t.order.orderType == "STP")
            for t in self.trades
            if t.orderStatus.status not in {"Filled", "Cancelled", "ApiCancelled"}
        ]

    def reqMarketDataType(self, value):
        self.market_data_requests.append(value)
        self.market_data_type = value

    async def reqTickersAsync(self, contract):
        return [
            SimpleNamespace(
                bid=56.0, ask=56.0, time=self.clock[0], marketDataType=self.market_data_type
            )
        ]

    async def reqExecutionsAsync(self, *args):
        return list(self.executions)

    async def reqCompletedOrdersAsync(self, *args):
        return [
            t
            for t in self.trades
            if t.orderStatus.status in {"Filled", "Cancelled", "ApiCancelled"}
        ]

    async def advance(self, seconds):
        self.clock[0] += timedelta(seconds=seconds)
        for trade in self.trades:
            until = self.pending.get(trade.order.orderRef)
            if until and self.clock[0] >= until:
                trade.orderStatus.status = "ApiCancelled"
        await self.real_sleep(0)


def scenario(monkeypatch, **kwargs):
    p = api()
    clock = [datetime(2026, 10, 27, 14, 0, tzinfo=SYDNEY)]
    broker = Paper(clock, **kwargs)
    broker.real_sleep = asyncio.sleep
    monkeypatch.setattr(p, "now", lambda: clock[0])
    monkeypatch.setattr(p.asyncio, "sleep", broker.advance)
    events = []
    run = p.HandoffProbe(broker, broker, broker.contract, "DUFAKE", events)
    return p, broker, run, events


@pytest.mark.asyncio
async def test_types_2_3_1_partial_then_full_and_type1_gap_cleanup(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)
    await run.run_cases(monitor=False)
    assert broker.held == 0
    assert not await broker.reqAllOpenOrdersAsync()
    entries = [t for t in broker.trades if t.order.action == "BUY"]
    assert [t.order.orderRef.split("-")[-2] for t in entries] == ["2", "3", "1"]
    sales = [t for t in broker.trades if t.order.orderType == "MKT"]
    assert [t.order.totalQuantity for t in sales] == [4, 5, 4, 5, 4, 5]
    for sale in sales:
        assert sale.order.ocaGroup
    assert any(e["event"] == "protection gap" and e["oca_type"] == 1 for e in events)
    assert len([e for e in events if e["event"] == "case flat confirmed"]) == 3
    assert not any(
        t.order.orderType == "STP" and "restore" in t.order.orderRef for t in broker.trades
    )


@pytest.mark.asyncio
async def test_disappearing_stop_records_gap_and_cleans_remaining_without_restore(monkeypatch):
    _, broker, run, events = scenario(monkeypatch, disappear=True)
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert [t.order.totalQuantity for t in broker.trades if t.order.orderType == "MKT"] == [4, 5]
    assert len([t for t in broker.trades if t.order.orderType == "STP"]) == 1
    assert any(e["event"] == "protection gap" and e["held_quantity"] == 5 for e in events)


@pytest.mark.asyncio
async def test_wrong_sized_live_stop_is_oversell_safety_halt_not_duplicate_sale(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch, wrong_quantity=True)
    with pytest.raises(p.SafetyHalt, match="oversell"):
        await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 5
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1


@pytest.mark.asyncio
async def test_unrelated_position_halts_without_any_order(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch, foreign=True)
    with pytest.raises(p.SafetyHalt, match="unrelated"):
        await run.run_cases(monitor=False)
    assert not broker.trades


@pytest.mark.asyncio
async def test_pending_cancel_twenty_minutes_waits_and_never_resends(monkeypatch):
    p, broker, run, events = scenario(monkeypatch, pending_minutes=20)
    order = p.LimitOrder(
        "SELL", 1, 70, account="DUFAKE", orderRef="test-owned", ocaGroup="test", ocaType=2
    )
    trade = broker.placeOrder(broker.contract, order)
    run.known[order.orderRef] = trade
    before = broker.clock[0]
    await run.cancel_once(trade)
    await run.cancel_once(trade)
    assert len(broker.cancels) == 1
    assert broker.clock[0] - before >= timedelta(minutes=20)
    assert trade.orderStatus.status == "ApiCancelled"
    assert any(
        e["event"] == "cancel state" and e["order"]["status"] == "PendingCancel" for e in events
    )


@pytest.mark.asyncio
async def test_oversized_target_also_blocks_another_exit(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    original = broker.placeOrder

    def wrong_target(contract, order):
        trade = original(contract, order)
        if order.orderType == "MKT" and broker.held:
            target = next(t for t in broker.trades if t.order.orderRef.endswith("-target"))
            target.orderStatus.remaining = broker.held + 1
        return trade

    broker.placeOrder = wrong_target
    with pytest.raises(p.SafetyHalt, match="oversell"):
        await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 5
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1


@pytest.mark.asyncio
async def test_holding_change_during_quote_is_rechecked_before_sell(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    quote = broker.reqTickersAsync
    injected = False

    async def stopped_during_quote(contract):
        nonlocal injected
        if run.armed and not injected:
            injected = True
            stop = next(t for t in broker.trades if t.order.orderType == "STP")
            broker.fill(stop, 7)
            stop.orderStatus = OrderStatus(status="Submitted", filled=7, remaining=2)
            target = next(t for t in broker.trades if t.order.orderRef.endswith("-target"))
            target.orderStatus.remaining = 2
        return await quote(contract)

    broker.reqTickersAsync = stopped_during_quote
    with pytest.raises(p.SafetyHalt, match="oversell"):
        await run.run_cases(types=(2,), monitor=False)
    assert not [t for t in broker.trades if t.order.orderType == "MKT"]
    assert broker.held == 2


@pytest.mark.asyncio
async def test_ambiguous_exit_acknowledgement_never_sends_cleanup_duplicate(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    original = broker.placeOrder

    def lost_ack(contract, order):
        if order.orderType == "MKT":
            order.orderId, order.permId, order.clientId = 99, 199, 1
            broker.trades.append(
                Trade(
                    contract, order, OrderStatus(status="Submitted", remaining=order.totalQuantity)
                )
            )
            raise RuntimeError("connection failed after send")
        return original(contract, order)

    broker.placeOrder = lost_ack
    with pytest.raises(p.SafetyHalt, match="acknowledgement"):
        await run.run_cases(types=(2,), monitor=False)
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1
    assert broker.held == 9


@pytest.mark.asyncio
async def test_broker_changed_group_is_not_treated_as_coordinated_protection(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    original = broker.reqAllOpenOrdersAsync

    async def changed_group():
        orders = await original()
        for trade in orders:
            if trade.order.orderType == "STP":
                trade.order.ocaGroup = "unexpected-group"
        return orders

    broker.reqAllOpenOrdersAsync = changed_group
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1


@pytest.mark.asyncio
async def test_final_inventory_reads_after_safety_halt_and_does_not_reuse_stale_quantity(
    monkeypatch,
):
    p, broker, run, _ = scenario(monkeypatch)
    run.planned_quantity = 9
    run.last_positions = [SimpleNamespace(account="DUFAKE", contract=broker.contract, position=9)]
    run.fatal = p.SafetyHalt("stop mismatch")
    broker.held = 5
    assert hasattr(run, "final_inventory"), "separate read-only final inventory required"
    held, orders = await run.final_inventory()
    assert held == 5
    assert orders == []


@pytest.mark.asyncio
async def test_flat_cleanup_dispatches_all_cancels_before_twenty_minute_wait(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch, pending_minutes=20)
    run.group, run.oca_type = "test", 2
    for index in range(2):
        order = p.LimitOrder(
            "BUY", 1, 70, account="DUFAKE", orderRef=f"test-{index}", ocaGroup="test", ocaType=2
        )
        # Pending entries at zero holdings are safe to cancel; live SELLs here
        # would themselves be an oversell transmission halt under the new rule.
        order.orderId, order.permId, order.clientId = index + 1, index + 101, 1
        trade = Trade(broker.contract, order, OrderStatus(status="Submitted", remaining=1))
        broker.trades.append(trade)
        run.known[order.orderRef] = trade
    await run.flat()
    assert len(broker.cancels) == 2
    assert broker.cancels[0][1] == broker.cancels[1][1]


@pytest.mark.asyncio
async def test_flat_cleanup_never_cancels_a_stop_before_independent_zero(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    broker.clock[0] = datetime(2026, 10, 27, 15, 29, 59, tzinfo=SYDNEY)
    broker.held, run.planned_quantity, run.group, run.oca_type = 5, 5, "test", 2
    order = p.StopOrder(
        "SELL", 5, 50, account="DUFAKE", orderRef="stop-test", ocaGroup="test", ocaType=2
    )
    trade = broker.placeOrder(broker.contract, order)
    run.known[order.orderRef] = trade
    with pytest.raises(p.ObservationTimeout):
        await run.flat()
    assert not broker.cancels


@pytest.mark.asyncio
async def test_execution_evidence_cannot_delay_gap_market_cleanup(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    original = broker.reqExecutionsAsync

    async def slow_evidence(*args):
        broker.clock[0] += timedelta(seconds=30)
        return await original(*args)

    broker.reqExecutionsAsync = slow_evidence
    await run.run_cases(types=(1,), monitor=False)
    requests = [
        e for e in events if e["event"] == "order request" and e["role"] in {"partial", "remainder"}
    ]
    elapsed = datetime.fromisoformat(requests[1]["at_aedt"]) - datetime.fromisoformat(
        requests[0]["at_aedt"]
    )
    assert elapsed <= timedelta(seconds=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["action", "auxPrice"])
async def test_stop_terms_cannot_change_and_still_count_as_protection(monkeypatch, change):
    p, broker, run, _ = scenario(monkeypatch)
    original = broker.reqAllOpenOrdersAsync

    async def altered():
        orders = await original()
        for trade in orders:
            if trade.order.orderType == "STP":
                setattr(trade.order, change, "BUY" if change == "action" else 1.0)
        return orders

    broker.reqAllOpenOrdersAsync = altered
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1


@pytest.mark.asyncio
async def test_gap_on_intermediate_partial_fill_cancels_remainder_once_then_cleans(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    original = broker.placeOrder

    def partial_market(contract, order):
        if order.orderType != "MKT" or not order.orderRef.endswith("-partial"):
            return original(contract, order)
        order.orderId, order.permId, order.clientId = 4, 104, 1
        trade = Trade(
            contract, order, OrderStatus(status="Submitted", remaining=order.totalQuantity)
        )
        broker.trades.append(trade)
        broker.fill(trade, 1)
        trade.orderStatus = OrderStatus(status="Submitted", filled=1, remaining=3)
        for sibling in broker.trades:
            if sibling.order.orderType in {"STP", "LMT"} and sibling.order.action == "SELL":
                sibling.orderStatus.status = "Cancelled"
        return trade

    broker.placeOrder = partial_market
    await run.run_cases(types=(1,), monitor=False)
    sales = [t for t in broker.trades if t.order.orderType == "MKT"]
    assert len(sales) == 2
    assert sales[0].orderStatus.status == "ApiCancelled"
    assert sales[1].order.totalQuantity == 8
    assert len(broker.cancels) == 1
    requests = [
        e for e in events if e["event"] == "order request" and e["role"] in {"partial", "remainder"}
    ]
    assert datetime.fromisoformat(requests[1]["at_aedt"]) - datetime.fromisoformat(
        requests[0]["at_aedt"]
    ) <= timedelta(seconds=2)
    assert broker.held == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", ["1.5", "NaN", "Infinity"])
async def test_invalid_final_quantity_preserves_raw_evidence_and_requires_action(
    monkeypatch, tmp_path, capsys, quantity
):
    p, broker, _, _ = scenario(monkeypatch)

    async def positions():
        return [SimpleNamespace(account="DUFAKE", contract=broker.contract, position=quantity)]

    broker.reqPositionsAsync = positions

    async def contracts(*args):
        return [broker.contract]

    broker.qualifyContractsAsync = contracts

    class Event:
        def __iadd__(self, callback):
            return self

    for name in ("errorEvent", "orderStatusEvent", "execDetailsEvent", "commissionReportEvent"):
        setattr(broker, name, Event())
    broker.isConnected = lambda: False
    monkeypatch.setattr(p, "IB", lambda: broker)

    async def connect(*args):
        pass

    monkeypatch.setattr(p, "connect", connect)
    monkeypatch.setattr(p, "load_approval", lambda *args: "DUFAKE")
    monkeypatch.setattr(p, "_safe_output_dir", lambda root: root)
    monkeypatch.setattr(p, "claim_attempt", lambda *args: None)
    broker.clock[0] = datetime(2026, 10, 27, 14, 0, tzinfo=SYDNEY)

    async def halted(self):
        raise p.SafetyHalt("synthetic halt")

    monkeypatch.setattr(p.HandoffProbe, "run_cases", halted)
    captured = []

    def write(root, name, result):
        captured.append(result)
        return root / "raw.json", "fake-digest"

    monkeypatch.setattr(p, "_write_raw", write)
    assert await p.run(date(2026, 10, 27), tmp_path, tmp_path / "approval.json", "fake", True) == 1
    assert captured[0]["held_quantity"] is None
    assert captured[0]["ds_action_required"]
    assert any(row["event"] == "independent final positions" for row in captured[0]["events"])
    assert "DS action required: held quantity unavailable" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_completed_timeout_preserves_execution_response_and_final_halt_queries(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)

    async def unavailable(*args):
        raise TimeoutError("completed orders timeout")

    broker.reqCompletedOrdersAsync = unavailable
    run.fatal = p.SafetyHalt("synthetic unrelated halt")
    assert not await run.executions()
    assert any(e["event"] == "broker evidence" and e["source"] == "reqExecutions" for e in events)
    assert any(
        e["event"] == "broker evidence unavailable" and e["source"] == "completed orders"
        for e in events
    )


@pytest.mark.asyncio
async def test_initial_target_must_cover_full_holding_before_partial_handoff(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    original = broker.placeOrder

    def undersized(contract, order):
        trade = original(contract, order)
        if order.orderRef.endswith("-target"):
            order.totalQuantity = 1
            trade.orderStatus.remaining = 1
        return trade

    broker.placeOrder = undersized
    await run.run_cases(types=(2,), monitor=False)
    assert not [t for t in broker.trades if t.order.orderRef.endswith("-partial")]
    assert any(e["event"] == "case observation" for e in events)
    assert broker.held == 0


@pytest.mark.asyncio
async def test_stop_disappearing_before_partial_exits_full_holding_without_quote_delay(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    original = broker.reqAllOpenOrdersAsync

    async def lost_stop():
        orders = await original()
        if run.armed and run.stage == "partial handoff":
            orders = [trade for trade in orders if trade.order.orderType != "STP"]
        return orders

    broker.reqAllOpenOrdersAsync = lost_stop
    await run.run_cases(types=(2,), monitor=False)
    sales = [t for t in broker.trades if t.order.orderType == "MKT"]
    assert [t.order.totalQuantity for t in sales] == [9]
    assert sales[0].order.orderRef.endswith("-cleanup")
    assert not any(e["event"] == "IBKR quote" and e["stage"] == "partial handoff" for e in events)
    assert broker.held == 0
    assert any(e["event"] == "protection gap" for e in events)


@pytest.mark.asyncio
async def test_stop_disappearing_during_partial_quote_blocks_half_and_cleans_full(monkeypatch):
    _, broker, run, _ = scenario(monkeypatch)
    original = broker.reqTickersAsync

    async def disappear(contract):
        if run.armed and run.stage == "partial handoff":
            for trade in broker.trades:
                if trade.order.orderType == "STP":
                    trade.orderStatus.status = "Cancelled"
        return await original(contract)

    broker.reqTickersAsync = disappear
    await run.run_cases(types=(2,), monitor=False)
    sales = [t for t in broker.trades if t.order.orderType == "MKT"]
    assert [t.order.totalQuantity for t in sales] == [9]
    assert sales[0].order.orderRef.endswith("-cleanup")
    assert broker.held == 0


@pytest.mark.asyncio
async def test_wire_snapshots_are_independent_and_float_drift_is_on_same_tick(monkeypatch):
    _, broker, run, _ = scenario(monkeypatch)
    broker.price_drift = True
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("order_type", ["STP", "LMT"])
@pytest.mark.parametrize("status", ["PreSubmitted", "Submitted"])
async def test_working_zero_remaining_is_unavailable_without_protection_or_gap(
    monkeypatch, order_type, status
):
    p, broker, run, events = scenario(monkeypatch)
    run.group, run.oca_type, run.planned_quantity, broker.held = "test", 2, 5, 5
    stop = run.place(
        p.StopOrder("SELL", 5, 50.4, ocaGroup="test", ocaType=2), "stop", Decimal("56")
    )
    if order_type == "LMT":
        stop.order.orderType, stop.order.lmtPrice = "LMT", 61.6
        run.terms[stop.order.orderRef] = run.order_terms(stop.order)
    stop.orderStatus.status = status
    original = broker.reqAllOpenOrdersAsync
    calls = 0

    async def missing_once():
        nonlocal calls
        calls += 1
        return [broker.decoded_snapshot(stop, omit_status=True)] if calls == 1 else await original()

    broker.reqAllOpenOrdersAsync = missing_once
    with pytest.raises(p.SnapshotUnavailable):
        await run.poll()
    assert run.latest is None and run.gap_started is None
    assert not any(e["event"] in {"protection gap", "client99 poll"} for e in events)
    assert any(e["event"] == "evidence unavailable" for e in events)
    valid = await run.poll()
    if order_type == "STP":
        assert valid["exact_stop"] and valid["stop_quantity"] == "5"
    else:
        assert valid["orders"][0]["remaining"] == "5"
    assert stop.orderStatus.remaining == 5


@pytest.mark.asyncio
async def test_transient_zero_remaining_retries_before_partial_without_cancel_or_cleanup(
    monkeypatch,
):
    _, broker, run, events = scenario(monkeypatch)
    original = broker.reqAllOpenOrdersAsync
    injected = False

    async def incomplete():
        nonlocal injected
        if run.armed and not injected:
            injected = True
            broker.incomplete_stop_polls = 1
        return await original()

    broker.reqAllOpenOrdersAsync = incomplete
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0 and not broker.cancels
    assert [t.order.totalQuantity for t in broker.trades if t.order.orderType == "MKT"] == [4, 5]
    assert any(e["event"] == "evidence unavailable" for e in events)
    assert not any(e["event"] == "case observation" for e in events)
    assert not any(
        e["event"] == "protection gap" and e["stage"] == "partial handoff" for e in events
    )


@pytest.mark.asyncio
async def test_live_unusable_requests_delayed_once_and_buffers_entry_limit(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    good = broker.reqTickersAsync

    async def snapshot(contract):
        if broker.market_data_type == 1:
            return [
                SimpleNamespace(bid=float("nan"), ask=-1, time=broker.clock[0], marketDataType=1)
            ]
        return await good(contract)

    broker.reqTickersAsync = snapshot
    await run.run_cases(types=(2, 3, 1), monitor=False)
    buys = [t.order for t in broker.trades if t.order.action == "BUY"]
    assert broker.market_data_requests == [3]
    assert len(buys) == 3 and all(order.lmtPrice == 56.56 for order in buys)
    assert all(
        Decimal(str(order.totalQuantity)) * Decimal(str(order.lmtPrice)) <= 800 for order in buys
    )
    assert any(
        e["event"] == "market data type request" and e["requested_type"] == 3 for e in events
    )
    assert any(e["event"] == "IBKR quote" and e["market_data_type"] == 3 for e in events)
    assert broker.held == 0


@pytest.mark.asyncio
async def test_delayed_entry_buffer_cannot_escape_cap(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)

    async def snapshot(contract):
        value = float("nan") if broker.market_data_type == 1 else 400.0
        return [
            SimpleNamespace(
                bid=value, ask=value, time=broker.clock[0], marketDataType=broker.market_data_type
            )
        ]

    broker.reqTickersAsync = snapshot
    with pytest.raises(ValueError, match="800"):
        await run.case(2)
    assert broker.market_data_requests == [3] and not broker.trades


@pytest.mark.asyncio
async def test_unusable_delayed_snapshot_does_not_resend_type_request_or_place(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)

    async def missing(*args):
        return []

    broker.reqTickersAsync = missing
    for _ in range(2):
        with pytest.raises(p.ObservationTimeout):
            await run.quote()
    assert broker.market_data_requests == [3]
    assert not broker.trades


@pytest.mark.parametrize(
    "order_type,used", [("STP", "auxPrice"), ("LMT", "lmtPrice"), ("MKT", None)]
)
def test_terms_ignore_every_unused_price_and_round_only_used_prices(order_type, used):
    p = api()
    order = Order(action="SELL", orderType=order_type, ocaGroup="test", ocaType=2)
    if used:
        setattr(order, used, 50.4)
    expected = p.HandoffProbe.order_terms(order)
    for unused in (0.0, UNSET_DOUBLE, -1.0, float("nan"), "unused"):
        for name in ("auxPrice", "lmtPrice"):
            if name != used:
                setattr(order, name, unused)
        if used:
            setattr(order, used, 50.400000000000006)
        assert p.HandoffProbe.order_terms(order) == expected
    if used:
        setattr(order, used, 50.41)
        assert p.HandoffProbe.order_terms(order) != expected


@pytest.mark.asyncio
async def test_account_failure_cannot_request_delayed_fallback(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)

    async def changed_account(*args):
        broker.accounts = ["DUOTHER"]
        return []

    broker.reqTickersAsync = changed_account
    with pytest.raises(p.SafetyHalt, match="account"):
        await run.quote()
    assert not broker.market_data_requests and not broker.trades


@pytest.mark.asyncio
async def test_live_usable_snapshot_keeps_entry_and_never_requests_delayed(monkeypatch):
    _, broker, run, _ = scenario(monkeypatch)
    await run.run_cases(types=(2,), monitor=False)
    assert not broker.market_data_requests
    assert next(t.order for t in broker.trades if t.order.action == "BUY").lmtPrice == 56


def test_delayed_limit_rounds_up_to_destination_asx_tick():
    p = api()
    run = p.HandoffProbe(None, None, None, "DUFAKE", [])
    run.delayed_requested = True
    assert run.entry_limit(Decimal("50.401")) == Decimal("50.91")
    assert run.entry_limit(Decimal("1.99")) == Decimal("2.01")
    assert run.entry_limit(Decimal("0.0995")) == Decimal("0.105")


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_type", [2, 4])
async def test_frozen_snapshot_never_supplies_entry_reference(monkeypatch, actual_type):
    p, broker, run, _ = scenario(monkeypatch)

    async def frozen(*args):
        return [SimpleNamespace(bid=56, ask=56, time=broker.clock[0], marketDataType=actual_type)]

    broker.reqTickersAsync = frozen
    with pytest.raises(p.ObservationTimeout):
        await run.case(2)
    assert broker.market_data_requests == [3]
    assert not broker.trades


@pytest.mark.asyncio
async def test_initial_already_delayed_response_requires_selected_fallback_and_buffer(monkeypatch):
    _, broker, run, events = scenario(monkeypatch)
    broker.market_data_type = 3
    await run.run_cases(types=(2,), monitor=False)
    assert broker.market_data_requests == [3]
    assert next(t.order for t in broker.trades if t.order.action == "BUY").lmtPrice == 56.56
    assert any(e["event"] == "IBKR snapshot unavailable" for e in events)
    assert broker.held == 0
