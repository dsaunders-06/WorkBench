"""Independent-review counterexamples, all offline using ib_async objects."""

from __future__ import annotations

from datetime import timedelta

import pytest
from ib_async import OrderStatus, Stock, Trade
from test_oca_managed_entry_revision import pending_scenario
from test_phase1_oca_exit_handoff_paper_probe import scenario
from test_phase1_oca_exit_handoff_paper_probe import wire_variant as wire_variant


@pytest.mark.asyncio
async def test_incomplete_final_orders_response_cannot_emit_flat(monkeypatch, tmp_path):
    p, broker, _, _ = scenario(monkeypatch)

    class Event:
        def __iadd__(self, callback):
            return self

    for name in ("errorEvent", "orderStatusEvent", "execDetailsEvent", "commissionReportEvent"):
        setattr(broker, name, Event())
    broker.isConnected = lambda: False

    async def qualified(*args):
        return [broker.contract]

    async def connect(*args):
        pass

    async def completed(self):
        pass

    async def unavailable():
        raise TimeoutError("open orders response unavailable after zero positions")

    broker.qualifyContractsAsync = qualified
    broker.reqAllOpenOrdersAsync = unavailable
    monkeypatch.setattr(p, "IB", lambda: broker)
    monkeypatch.setattr(p, "connect", connect)
    monkeypatch.setattr(p, "load_approval", lambda *args: "DUFAKE")
    monkeypatch.setattr(p, "_safe_output_dir", lambda root: root)
    monkeypatch.setattr(p, "claim_attempt", lambda *args: None)
    monkeypatch.setattr(p.HandoffProbe, "run_cases", completed)
    captured = []

    def write(root, name, value):
        captured.append(value)
        return root / "raw.json", "fake"

    monkeypatch.setattr(p, "_write_raw", write)
    assert await p.run(p.SESSION, tmp_path, tmp_path / "approval.json", "fake", True) == 1
    assert captured[0]["ds_action_required"] and not captured[0]["flat"]
    assert not captured[0]["final_book_available"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["Submitted", "PendingCancel"])
async def test_zero_holding_live_sell_is_transmission_halt_before_any_cancel(monkeypatch, status):
    p, broker, run, _ = scenario(monkeypatch)
    run.group, run.oca_type, run.planned_quantity = "test", 2, 9
    trade = run.place(
        p.StopOrder("SELL", 5, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56")
    )
    trade.orderStatus.status = status
    with pytest.raises(p.TransmissionHalt, match="oversell"):
        await run.cleanup()
    assert not broker.cancels and len(broker.trades) == 1


@pytest.mark.asyncio
async def test_transient_first_cleanup_read_recovers_then_requests_one_cancel(monkeypatch):
    p, broker, run, events = pending_scenario(monkeypatch)
    run.planned_quantity = 9
    run.quote_reference = p.Decimal("56")
    run.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
    original = broker.reqPositionsAsync
    calls = 0

    async def transient():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("transient client99 positions timeout")
        return await original()

    broker.reqPositionsAsync = transient
    await run.cleanup()
    assert len(broker.cancels) == 1
    assert broker.trades[0].orderStatus.status == "ApiCancelled" and broker.held == 0
    assert any(e["event"] == "cleanup evidence unavailable" for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["order", "position"])
async def test_foreign_exposure_reports_promptly_once_owned_orders_terminal(monkeypatch, foreign):
    p, broker, run, _ = scenario(monkeypatch)
    run.planned_quantity = 9
    run.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
    if foreign == "position":
        broker.foreign = True
    else:

        async def other_order():
            return [
                Trade(
                    Stock("OTHER", "SMART", "AUD", conId=99),
                    p.LimitOrder("BUY", 1, 1, account="DUFAKE", orderRef="foreign", clientId=7),
                    OrderStatus(status="Submitted", remaining=1),
                )
            ]

        broker.reqAllOpenOrdersAsync = other_order
    start = broker.clock[0]
    with pytest.raises(p.TransmissionHalt, match="unrelated"):
        await run.wait_own_terminal()
    assert broker.clock[0] - start < timedelta(seconds=1)
    assert not broker.cancels and len(broker.trades) == 1


@pytest.mark.asyncio
async def test_terminal_partial_emergency_sale_never_emits_flat_or_retries(monkeypatch):
    p, broker, run, events = pending_scenario(monkeypatch, fill_on_mismatch=True)
    original = broker.placeOrder

    def partial_cancelled(contract, order):
        if order.orderType != "MKT":
            return original(contract, order)
        order.orderId, order.permId, order.clientId = 2, 102, 1
        trade = Trade(contract, order, OrderStatus(status="Submitted", remaining=9))
        broker.trades.append(trade)
        broker.fill(trade, 3)
        trade.orderStatus = OrderStatus(status="Cancelled", filled=3, remaining=0)
        return trade

    broker.placeOrder = partial_cancelled
    with pytest.raises(p.ObservationTimeout, match="residual"):
        await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 6
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 1
    assert not any(
        e["event"] in {"case incomplete but flat", "emergency cleanup completed"} for e in events
    )


@pytest.mark.asyncio
async def test_last_snapshot_pending_order_is_drained_before_disconnect(monkeypatch, tmp_path):
    p, broker, _, _ = scenario(monkeypatch)

    class Event:
        def __iadd__(self, callback):
            return self

    for name in ("errorEvent", "orderStatusEvent", "execDetailsEvent", "commissionReportEvent"):
        setattr(broker, name, Event())
    broker.isConnected = lambda: False

    async def connect(*args):
        pass

    async def qualified(*args):
        return [broker.contract]

    async def completed(self):
        self.planned_quantity = 9
        self.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
        self.place(p.MarketOrder("SELL", 9), "exit", p.Decimal("56"))

    start = broker.clock[0]
    calls = 0

    async def late_pending():
        nonlocal calls
        calls += 1
        if calls >= 2 and broker.clock[0] < start + timedelta(minutes=20):
            # A fresh independent snapshot contradicts the owner's terminal cache.
            row = broker.decoded_snapshot(broker.trades[0])
            row.orderStatus = OrderStatus(status="PendingSubmit", remaining=9)
            return [row]
        return []

    broker.qualifyContractsAsync = qualified
    broker.reqAllOpenOrdersAsync = late_pending
    monkeypatch.setattr(p, "IB", lambda: broker)
    monkeypatch.setattr(p, "connect", connect)
    monkeypatch.setattr(p, "load_approval", lambda *args: "DUFAKE")
    monkeypatch.setattr(p, "_safe_output_dir", lambda root: root)
    monkeypatch.setattr(p, "claim_attempt", lambda *args: None)
    monkeypatch.setattr(p.HandoffProbe, "run_cases", completed)
    captured = []

    def write(root, name, value):
        captured.append(value)
        return root / "raw.json", "fake"

    monkeypatch.setattr(p, "_write_raw", write)
    assert await p.run(p.SESSION, tmp_path, tmp_path / "approval.json", "fake", True) == 0
    assert broker.clock[0] - start >= timedelta(minutes=20)
    assert captured[0]["flat"] and not captured[0]["own_nonterminal_orders"]
