"""Offline reproductions of IBKR's observed ungrouped entry and pending race."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta

import pytest
from ib_async import OrderStatus, Trade
from test_phase1_oca_exit_handoff_paper_probe import SYDNEY, Paper, api, scenario


@pytest.fixture(params=["0", ""], autouse=True)
def observed_unused_wire(request, monkeypatch):
    monkeypatch.setattr(Paper, "unused_wire_price", request.param)


class PendingEntry(Paper):
    """A separate PendingSubmit entry survives zero-position reads."""

    def __init__(self, *args, fill_on_mismatch=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fill_on_mismatch = fill_on_mismatch
        self.changed = False

    def placeOrder(self, contract, order):
        if order.action != "BUY":
            return super().placeOrder(contract, order)
        order.orderId, order.permId, order.clientId = 1, 101, 1
        trade = Trade(contract, order, OrderStatus(status="PendingSubmit", remaining=9))
        self.trades.append(trade)
        return trade

    async def reqPositionsAsync(self):
        if self.fill_on_mismatch and not self.changed and self.trades:
            trade = self.trades[0]
            self.fill(trade, 9)
            # Position update precedes the final owner status callback.
            trade.orderStatus.status = "Submitted"
            trade.orderStatus.remaining = 9
        return await super().reqPositionsAsync()

    async def reqAllOpenOrdersAsync(self):
        rows = await super().reqAllOpenOrdersAsync()
        if rows:
            rows[0].order.lmtPrice += 0.01
            if self.fill_on_mismatch:
                self.trades[0].orderStatus.status = "Filled"
                self.trades[0].orderStatus.remaining = 0
            self.changed = True
        return rows


def pending_scenario(monkeypatch, **kwargs):
    p, old, _, _ = scenario(monkeypatch)
    old.clock[0] = datetime(2026, 11, 4, 11, 30, tzinfo=SYDNEY)
    broker = PendingEntry(old.clock, **kwargs)
    broker.real_sleep = old.real_sleep
    monkeypatch.setattr(p.asyncio, "sleep", broker.advance)
    events = []
    run = p.HandoffProbe(broker, broker, broker.contract, "DUFAKE", events)
    return p, broker, run, events


def test_ungrouped_entry_ignores_observed_type3_but_grouped_orders_pin_it(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    order = p.LimitOrder("BUY", 9, 56, account="DUFAKE", orderRef="entry")
    original = broker.placeOrder(broker.contract, order)
    returned = broker.decoded_snapshot(original)
    assert original.order.ocaType == 0 and returned.order.ocaType == 3
    assert run.order_terms(original.order) == run.order_terms(returned.order)
    original.order.ocaGroup = returned.order.ocaGroup = "group"
    assert run.order_terms(original.order) != run.order_terms(returned.order)


@pytest.mark.asyncio
async def test_working_entry_mismatch_cancels_once_waits_twenty_minutes_no_sale(monkeypatch):
    _, broker, run, events = pending_scenario(monkeypatch, pending_minutes=20)
    start = broker.clock[0]
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert len(broker.cancels) == 1 and broker.clock[0] - start >= timedelta(minutes=20)
    assert broker.trades[0].orderStatus.status == "ApiCancelled"
    assert not [t for t in broker.trades if t.order.orderType == "MKT"]
    assert any(e["event"] == "emergency cleanup" for e in events)


@pytest.mark.asyncio
async def test_entry_fills_during_mismatch_then_one_market_cleanup_without_stop(monkeypatch):
    _, broker, run, _ = pending_scenario(monkeypatch, fill_on_mismatch=True)
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    sales = [t for t in broker.trades if t.order.orderType == "MKT"]
    assert len(sales) == 1 and sales[0].order.totalQuantity == 9
    assert not sales[0].order.ocaGroup
    assert not [t for t in broker.trades if t.order.orderType == "STP"]
    assert all(
        t.orderStatus.status in {"Filled", "Cancelled", "ApiCancelled"} for t in broker.trades
    )


@pytest.mark.asyncio
async def test_transmission_halt_has_no_orders(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch, foreign=True)
    with pytest.raises(p.TransmissionHalt, match="unrelated"):
        await run.run_cases(types=(2,), monitor=False)
    assert not broker.trades and not broker.cancels


@pytest.mark.asyncio
async def test_filled_entry_with_stale_zero_position_is_reconciled_before_exit(monkeypatch):
    _, broker, run, events = pending_scenario(monkeypatch, fill_on_mismatch=True)
    positions = broker.reqPositionsAsync
    stale = 2

    async def temporarily_zero():
        nonlocal stale
        if broker.held and stale:
            stale -= 1
            return []
        return await positions()

    broker.reqPositionsAsync = temporarily_zero
    await run.run_cases(types=(2,), monitor=False)
    assert broker.held == 0
    assert sum(t.order.totalQuantity for t in broker.trades if t.order.orderType == "MKT") == 9
    assert any(e["event"] == "evidence unavailable" for e in events)


@pytest.mark.asyncio
async def test_window_end_pending_entry_is_not_flat_or_early_exit(monkeypatch, tmp_path, capsys):
    p, broker, _, _ = pending_scenario(monkeypatch, pending_minutes=300)
    broker.clock[0] = datetime(2026, 11, 4, 11, 59, 58, tzinfo=SYDNEY)

    class Event:
        def __iadd__(self, callback):
            return self

    for name in ("errorEvent", "orderStatusEvent", "execDetailsEvent", "commissionReportEvent"):
        setattr(broker, name, Event())
    broker.isConnected = lambda: False

    async def qualified(*args):
        return [broker.contract]

    broker.qualifyContractsAsync = qualified
    monkeypatch.setattr(p, "IB", lambda: broker)

    async def connect(*args):
        pass

    monkeypatch.setattr(p, "connect", connect)
    monkeypatch.setattr(p, "load_approval", lambda *args: "DUFAKE")
    monkeypatch.setattr(p, "_safe_output_dir", lambda root: root)
    monkeypatch.setattr(p, "claim_attempt", lambda *args: None)
    captured = []

    def write(root, name, result):
        captured.append(result)
        return root / "raw.json", "fake"

    monkeypatch.setattr(p, "_write_raw", write)
    assert await p.run(date(2026, 11, 4), tmp_path, tmp_path / "approval.json", "fake", True) == 1
    assert broker.clock[0] >= datetime(2026, 11, 4, 15, 30, tzinfo=SYDNEY)
    assert captured[0]["held_quantity"] == 0 and captured[0]["ds_action_required"]
    assert captured[0]["own_nonterminal_orders"]
    assert len(broker.cancels) == 1
    assert not [t for t in broker.trades if t.order.orderType == "MKT"]
    assert "DS action required" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_final_zero_snapshot_cannot_claim_flat_against_unexited_owned_fill(
    monkeypatch, tmp_path
):
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

    async def filled_then_transmission_halt(self):
        self.planned_quantity = 9
        self.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
        raise p.TransmissionHalt("unrelated order synthetic halt")

    original = broker.reqPositionsAsync
    reads = 0

    async def stale_final():
        nonlocal reads
        reads += 1
        return [] if reads >= 2 else await original()

    broker.qualifyContractsAsync = qualified
    broker.reqPositionsAsync = stale_final
    monkeypatch.setattr(p, "IB", lambda: broker)
    monkeypatch.setattr(p, "connect", connect)
    monkeypatch.setattr(p, "load_approval", lambda *args: "DUFAKE")
    monkeypatch.setattr(p, "_safe_output_dir", lambda root: root)
    monkeypatch.setattr(p, "claim_attempt", lambda *args: None)
    monkeypatch.setattr(p.HandoffProbe, "run_cases", filled_then_transmission_halt)
    captured = []
    monkeypatch.setattr(
        p,
        "_write_raw",
        lambda root, name, value: (captured.append(value) or root / "raw.json", "fake"),
    )
    assert await p.run(date(2026, 11, 4), tmp_path, tmp_path / "approval.json", "fake", True) == 1
    assert not captured[0]["flat"]
    assert len(broker.trades) == 1 and not broker.cancels


@pytest.mark.parametrize(
    "session,hour,minute,allowed",
    [
        (4, 11, 29, False),
        (4, 11, 30, True),
        (4, 12, 0, False),
        (5, 11, 29, False),
        (5, 11, 30, True),
        (5, 12, 0, False),
    ],
)
def test_revised_session_windows(session, hour, minute, allowed):
    p = api()
    day = date(2026, 11, session)
    stamp = datetime(2026, 11, session, hour, minute, tzinfo=SYDNEY)
    if allowed:
        p.session_window(day, stamp)
    else:
        with pytest.raises(ValueError):
            p.session_window(day, stamp)


def test_revision_session_locks_are_separate_and_preserve_previous_attempt(tmp_path):
    p = api()
    pm = tmp_path / "phase1-oca-exit-handoff-20261104"
    fallback = tmp_path / "phase1-oca-exit-handoff-20261105"
    pm.mkdir()
    fallback.mkdir()
    p.claim_attempt(pm, date(2026, 11, 4))
    with pytest.raises(FileExistsError):
        p.claim_attempt(pm, date(2026, 11, 4))
    p.claim_attempt(fallback, date(2026, 11, 5))
    assert (pm / "oca-20261104-attempt.lock").exists()
    assert (fallback / "oca-20261105-attempt.lock").exists()


@pytest.mark.parametrize(
    "session,signing,allowed",
    [(4, 3, True), (4, 4, True), (5, 4, True), (5, 5, True), (4, 5, False)],
)
def test_new_approval_names_session_and_actual_signing_date(
    tmp_path, monkeypatch, session, signing, allowed
):
    p = api()
    root = tmp_path / f"phase1-oca-exit-handoff-{p.session_tag(date(2026, 11, session))}"
    root.mkdir()
    value = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "operator": "DS",
        "symbol": "BHP.AX",
        "session": f"2026-11-{session:02d}",
        "approval_date": f"2026-11-{signing:02d}",
        "cap_per_order_aud": "800",
    }
    path = root / "approval.json"
    path.write_text(json.dumps(value))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(p, "ACCOUNT_SHA256", hashlib.sha256(b"DUFAKE").hexdigest())
    if allowed:
        assert p.load_approval(path, digest, root, date(2026, 11, session)) == "DUFAKE"
    else:
        with pytest.raises(ValueError):
            p.load_approval(path, digest, root, date(2026, 11, session))
