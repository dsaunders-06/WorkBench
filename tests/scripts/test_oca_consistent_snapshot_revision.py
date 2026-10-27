"""Replay delayed IBKR OCA sibling updates with independent decoded snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from ib_async import OrderStatus, Stock, Trade
from test_phase1_oca_exit_handoff_paper_probe import SYDNEY, Paper, api
from test_phase1_oca_exit_handoff_paper_probe import wire_variant as wire_variant


class LaggingPaper(Paper):
    def __init__(self, clock, *, lag_polls=3):
        super().__init__(clock)
        self.lag_polls, self.lag_reads, self.lag_stop = lag_polls, 0, None
        self.lag_started = None

    def placeOrder(self, contract, order):
        result = super().placeOrder(contract, order)
        if order.orderRef.endswith("-partial"):
            self.lag_stop = next(t for t in self.trades if t.order.orderType == "STP")
            self.lag_stop.order.totalQuantity = 9
            self.lag_stop.orderStatus = OrderStatus(
                status="PendingCancel" if order.ocaType == 1 else "Submitted", remaining=9
            )
            self.lag_started = self.clock[0]
        return result

    async def reqAllOpenOrdersAsync(self):
        stop = self.lag_stop
        if stop and stop.orderStatus.status not in {"Cancelled", "ApiCancelled", "Filled"}:
            self.lag_reads += 1
            if self.lag_polls is not None and self.lag_reads > self.lag_polls:
                if stop.order.ocaType == 1:
                    stop.orderStatus.status = "Cancelled"
                else:
                    stop.order.totalQuantity = self.held
                    stop.orderStatus.remaining = self.held
        return await super().reqAllOpenOrdersAsync()


def lag_scenario(monkeypatch, **kwargs):
    p = api()
    clock = [datetime(2026, 10, 27, 14, 45, tzinfo=SYDNEY)]
    broker = LaggingPaper(clock, **kwargs)
    broker.real_sleep = asyncio.sleep
    monkeypatch.setattr(p, "now", lambda: clock[0])
    monkeypatch.setattr(p.asyncio, "sleep", broker.advance)
    events = []
    run = p.HandoffProbe(broker, broker, broker.contract, "DUFAKE", events)
    return p, broker, run, events


@pytest.mark.asyncio
@pytest.mark.parametrize("oca_type", [2, 3])
async def test_three_submitted_oversize_stop_polls_reduce_without_halt(monkeypatch, oca_type):
    _, broker, run, events = lag_scenario(monkeypatch)
    await run.run_cases(types=(oca_type,), monitor=False)
    assert broker.held == 0 and not broker.cancels
    observations = [e for e in events if e["event"] == "own SELL exceeds holding"]
    assert len(observations) >= 3
    assert not any(e["event"] == "persistent own SELL excess" for e in events)
    assert any(e["event"] == "case flat confirmed" for e in events)


@pytest.mark.asyncio
async def test_type1_three_pendingcancel_polls_then_gap_cleanup(monkeypatch):
    _, broker, run, events = lag_scenario(monkeypatch)
    await run.run_cases(types=(1,), monitor=False)
    assert broker.held == 0 and not broker.cancels
    assert any(
        e["event"] == "own SELL exceeds holding" and e["order"]["status"] == "PendingCancel"
        for e in events
    )
    assert len([t for t in broker.trades if t.order.orderType == "MKT"]) == 2
    assert any(e["event"] == "protection gap" for e in events)


@pytest.mark.asyncio
async def test_position_order_position_pair_mismatch_is_unavailable(monkeypatch):
    p, broker, run, events = lag_scenario(monkeypatch)
    run.planned_quantity = 9
    trace = []
    quantities = iter([9, 5])

    async def positions():
        trace.append("positions")
        return [
            SimpleNamespace(account="DUFAKE", contract=broker.contract, position=next(quantities))
        ]

    async def orders():
        trace.append("orders")
        return []

    broker.reqPositionsAsync, broker.reqAllOpenOrdersAsync = positions, orders
    with pytest.raises(p.SnapshotUnavailable):
        await run.poll()
    assert trace == ["positions", "orders", "positions"]
    assert run.latest is None
    assert any(e["event"] == "evidence unavailable" for e in events)
    assert not any(
        e["event"] in {"client99 poll", "protection gap", "own SELL exceeds holding"}
        for e in events
    )


@pytest.mark.asyncio
async def test_persistent_oversized_stop_is_cancelled_once_then_one_cleanup(monkeypatch):
    _, broker, run, events = lag_scenario(monkeypatch, lag_polls=None)
    await run.run_cases(types=(2,), monitor=False)
    stop_ref = broker.lag_stop.order.orderRef
    stop_cancels = [row for row in broker.cancels if row[0] == stop_ref]
    assert len(stop_cancels) == 1
    assert stop_cancels[0][1] - broker.lag_started >= timedelta(seconds=10)
    assert broker.held == 0
    assert len([t for t in broker.trades if t.order.orderType == "STP"]) == 1
    assert [t.order.totalQuantity for t in broker.trades if t.order.orderType == "MKT"] == [4, 5]
    assert any(e["event"] == "persistent own SELL excess" for e in events)


@pytest.mark.asyncio
async def test_unrelated_order_remains_immediate_transmission_halt(monkeypatch):
    p, broker, run, _ = lag_scenario(monkeypatch)

    async def foreign():
        return [
            Trade(
                Stock("OTHER", "SMART", "AUD", conId=99),
                p.LimitOrder("BUY", 1, 1, account="DUFAKE", clientId=7, orderRef="foreign"),
                OrderStatus(status="Submitted", remaining=1),
            )
        ]

    broker.reqAllOpenOrdersAsync = foreign
    with pytest.raises(p.TransmissionHalt, match="unrelated"):
        await run.poll()
    assert not broker.trades and not broker.cancels


@pytest.mark.parametrize(
    "day,hour,minute,allowed",
    [
        (27, 14, 44, False),
        (27, 14, 45, True),
        (27, 15, 0, False),
        (28, 11, 30, True),
        (28, 15, 0, False),
    ],
)
def test_corrected_start_gates(day, hour, minute, allowed):
    p = api()
    args = date(2026, 10, day), datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY)
    if allowed:
        p.session_window(*args)
    else:
        with pytest.raises(ValueError):
            p.session_window(*args)


def test_pm_directory_required_and_morning_directory_rejected_before_read(tmp_path, monkeypatch):
    p = api()
    root = tmp_path / "phase1-oca-exit-handoff-20261027-pm"
    root.mkdir()
    terms = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "operator": "DS",
        "approval_date": "2026-10-27",
        "session": "2026-10-27",
        "symbol": "BHP.AX",
        "cap_per_order_aud": "800",
    }
    path = root / "approval.json"
    path.write_text(json.dumps(terms))
    monkeypatch.setattr(p, "ACCOUNT_SHA256", hashlib.sha256(b"DUFAKE").hexdigest())
    assert p.load_approval(path, hashlib.sha256(path.read_bytes()).hexdigest(), root) == "DUFAKE"
    forbidden = tmp_path / "phase1-oca-exit-handoff-20261027"
    with pytest.raises(ValueError):
        p.load_approval(forbidden / "approval.json", "0" * 64, forbidden)
    assert not forbidden.exists()


def test_valid_started_session_cleanup_allowed_after_start_cutoff():
    p = api()
    stamp = datetime(2026, 10, 27, 15, 10, tzinfo=SYDNEY)
    p.session_window(date(2026, 10, 27), stamp, starting=False)
    with pytest.raises(ValueError):
        p.session_window(date(2026, 10, 27), stamp)
    with pytest.raises(ValueError):
        p.session_window(date(2026, 10, 27), stamp.replace(minute=30), starting=False)


@pytest.mark.asyncio
async def test_unknown_poll_resets_ten_second_oversized_streak(monkeypatch):
    p, broker, run, events = lag_scenario(monkeypatch)
    run.planned_quantity = 9
    trade = run.place(p.StopOrder("SELL", 9, 50), "stop", p.Decimal("56"))
    run.observe_excess(0, [trade])
    broker.clock[0] += timedelta(seconds=9)
    original = broker.reqPositionsAsync
    quantities = iter([0, 1])

    async def changing_positions():
        return [
            SimpleNamespace(account="DUFAKE", contract=broker.contract, position=next(quantities))
        ]

    broker.reqPositionsAsync = changing_positions
    with pytest.raises(p.SnapshotUnavailable):
        await run.poll()
    assert not run.excess_since
    broker.reqPositionsAsync = original
    broker.clock[0] += timedelta(seconds=2)
    run.observe_excess(0, [trade])
    assert not run.confirmed_excess
    broker.clock[0] += timedelta(seconds=10)
    with pytest.raises(p.OwnSellExcess):
        run.observe_excess(0, [trade])
    assert len([e for e in events if e["event"] == "persistent own SELL excess"]) == 1


def test_protected_morning_ancestor_is_case_insensitive(tmp_path):
    p = api()
    root = tmp_path / "PHASE1-OCA-EXIT-HANDOFF-20261027" / "phase1-oca-exit-handoff-20261027-pm"
    with pytest.raises(ValueError):
        p.checked_output(root, date(2026, 10, 27))
    assert not root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("lag_polls", [3, None])
async def test_background_monitor_transient_and_persistent_sibling_lag(monkeypatch, lag_polls):
    _, broker, run, events = lag_scenario(monkeypatch, lag_polls=lag_polls)
    await run.run_cases(types=(2,), monitor=True)
    assert broker.held == 0
    assert all(
        t.orderStatus.status in {"Filled", "Cancelled", "ApiCancelled"} for t in broker.trades
    )
    assert not any(t.order.orderRef.endswith("restore") for t in broker.trades)
    confirmations = [e for e in events if e["event"] == "persistent own SELL excess"]
    assert bool(confirmations) == (lag_polls is None)
    if lag_polls is None:
        assert len([c for c in broker.cancels if c[0] == broker.lag_stop.order.orderRef]) == 1
    else:
        assert not broker.cancels
