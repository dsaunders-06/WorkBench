"""Offline regressions for the 3 November untransmitted protective-stop fault."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_phase1_oca_exit_handoff_paper_probe import SYDNEY, scenario
from test_phase1_oca_exit_handoff_paper_probe import wire_variant as wire_variant


@pytest.mark.asyncio
@pytest.mark.parametrize("oca_type", [2, 3, 1])
async def test_case_establishes_working_stop_before_joined_exit(monkeypatch, oca_type):
    _, broker, run, events = scenario(monkeypatch)
    await run.case(oca_type)
    partial = next(
        index
        for index, event in enumerate(events)
        if event["event"] == "order request" and event["role"] == "partial"
    )
    assert any(
        event["event"] == "client99 poll"
        and event["exact_stop"]
        and event["held_quantity"] == 9
        and any(order["type"] == "LMT" and order["remaining"] == "9" for order in event["orders"])
        for event in events[:partial]
    )
    assert broker.held == 0
    assert not await broker.reqAllOpenOrdersAsync()
    assert not broker.untransmitted_cancel_attempts


@pytest.mark.asyncio
async def test_untransmitted_stop_never_works_fills_or_cancels_as_working(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    broker.held = run.planned_quantity = 9
    order = p.StopOrder("SELL", 9, 50, transmit=False)
    trade = run.place(order, "stop", p.Decimal("56"))
    assert trade.orderStatus.status == "PendingSubmit"
    assert not await broker.reqAllOpenOrdersAsync()
    broker.fill(trade, 9)
    assert broker.held == 9 and not trade.fills
    assert trade.orderStatus.status == "PendingSubmit"
    await run.cancel_once(trade)
    assert broker.untransmitted_cancel_attempts == [order.orderRef]
    assert order.orderRef not in broker.pending
    assert trade.orderStatus.status == "Cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending", ["protection", "poll liquidation", "final liquidation", "cleanup"]
)
async def test_every_gap_end_has_one_matching_event(monkeypatch, ending):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type = 9, "test", 2
    run.quote_reference = p.Decimal("56")
    run.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
    await run.poll()
    began = broker.clock[0]
    broker.clock[0] += timedelta(seconds=3)
    if ending == "protection":
        run.place(p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56"))
        await run.poll()
    elif ending == "poll liquidation":
        run.place(p.MarketOrder("SELL", 9), "exit", p.Decimal("56"))
        await run.poll()
    elif ending == "final liquidation":
        run.place(p.MarketOrder("SELL", 9), "exit", p.Decimal("56"))
        await run.final_inventory()
    else:
        await run.cleanup()
    ends = [event for event in events if event["event"] == "protection gap ended"]
    assert len(ends) == 1
    assert ends[0]["observed_start"] == began.isoformat()
    assert datetime.fromisoformat(ends[0]["observed_end"]) >= began + timedelta(seconds=3)
    assert ends[0]["interval_seconds"] >= 3
    assert run.gap_started is None
    await run.final_inventory()
    assert len([event for event in events if event["event"] == "protection gap ended"]) == 1


@pytest.mark.asyncio
async def test_final_inventory_records_restored_protection_without_a_normal_poll(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type, broker.held = 9, "test", 2, 9
    await run.poll()
    run.place(p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56"))
    held, orders = await run.final_inventory()
    assert held == 9 and len(orders) == 1
    assert run.gap_started is None
    assert len([event for event in events if event["event"] == "protection gap ended"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", ["positions differ", "remaining zero", "terms differ"])
async def test_final_inventory_never_closes_gap_on_doubtful_protection(monkeypatch, uncertain):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type, broker.held = 9, "test", 2, 9
    await run.poll()
    stop = run.place(
        p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56")
    )
    if uncertain == "positions differ":
        quantities = iter([9, 0])

        async def positions():
            return [
                SimpleNamespace(
                    account="DUFAKE", contract=broker.contract, position=next(quantities)
                )
            ]

        broker.reqPositionsAsync = positions
        with pytest.raises(p.SnapshotUnavailable):
            await run.final_inventory()
    else:
        original = broker.reqAllOpenOrdersAsync

        async def doubtful():
            if uncertain == "remaining zero":
                return [broker.decoded_snapshot(stop, omit_status=True)]
            rows = await original()
            rows[0].order.auxPrice = 49
            return rows

        broker.reqAllOpenOrdersAsync = doubtful
        await run.final_inventory()
    assert run.gap_started is not None
    assert not any(event["event"] == "protection gap ended" for event in events)


@pytest.mark.parametrize(
    "day,hour,minute,allowed",
    [
        (4, 11, 29, False),
        (4, 11, 30, True),
        (4, 11, 59, True),
        (4, 12, 0, False),
        (5, 11, 29, False),
        (5, 11, 30, True),
        (5, 11, 59, True),
        (5, 12, 0, False),
        (2, 12, 0, False),
        (3, 11, 30, False),
    ],
)
def test_only_fourth_and_fifth_november_start_windows(day, hour, minute, allowed):
    p = __import__("phase1_oca_exit_handoff_paper_probe")
    stamp = datetime(2026, 11, day, hour, minute, tzinfo=SYDNEY)
    if allowed:
        p.session_window(stamp.date(), stamp)
    else:
        with pytest.raises(ValueError):
            p.session_window(stamp.date(), stamp)


@pytest.mark.parametrize("day", [4, 5])
def test_new_sessions_hard_end_and_separate_private_locks(tmp_path, day):
    p = __import__("phase1_oca_exit_handoff_paper_probe")
    session = date(2026, 11, day)
    before = datetime(2026, 11, day, 15, 29, 59, tzinfo=SYDNEY)
    p.session_window(session, before, starting=False)
    with pytest.raises(ValueError):
        p.session_window(session, before.replace(minute=30, second=0), starting=False)
    root = tmp_path / f"phase1-oca-exit-handoff-202611{day:02d}"
    root.mkdir()
    p.claim_attempt(root, session)
    assert (root / f"oca-202611{day:02d}-attempt.lock").is_file()
    with pytest.raises(FileExistsError):
        p.claim_attempt(root, session)


@pytest.mark.parametrize("earlier", ["20261027", "20261027-pm", "20261028", "20261102", "20261103"])
def test_every_earlier_output_directory_is_protected_even_as_an_ancestor(tmp_path, earlier):
    p = __import__("phase1_oca_exit_handoff_paper_probe")
    old = tmp_path / f"phase1-oca-exit-handoff-{earlier}"
    for target in [old, old / "phase1-oca-exit-handoff-20261104"]:
        with pytest.raises(ValueError):
            p.checked_output(target, date(2026, 11, 4))
        with pytest.raises(ValueError):
            p.load_approval(target / "approval.json", "0" * 64, target, date(2026, 11, 4))
        with pytest.raises(ValueError):
            p.claim_attempt(target, date(2026, 11, 4))
    assert not old.exists()


@pytest.mark.asyncio
async def test_final_liquidation_gap_end_survives_a_later_oversell_observation(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type = 9, "test", 2
    run.place(p.LimitOrder("BUY", 9, 56), "entry", p.Decimal("56"))
    await run.poll()
    target = run.place(
        p.LimitOrder("SELL", 9, 62, ocaGroup="test", ocaType=2), "target", p.Decimal("56")
    )
    run.place(p.MarketOrder("SELL", 9), "exit", p.Decimal("56"))
    run.observe_excess(0, [target])
    broker.clock[0] += timedelta(seconds=11)
    with pytest.raises(p.OwnSellExcess):
        await run.final_inventory()
    assert run.gap_started is None
    assert len([event for event in events if event["event"] == "protection gap ended"]) == 1
    assert not broker.cancels


@pytest.mark.asyncio
async def test_joined_fill_cannot_reduce_or_cancel_an_untransmitted_sibling(monkeypatch):
    p, broker, run, _ = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type, broker.held = 9, "test", 2, 9
    stop = run.place(
        p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2, transmit=False),
        "stop",
        p.Decimal("56"),
    )
    run.place(p.MarketOrder("SELL", 4, ocaGroup="test", ocaType=2), "partial", p.Decimal("56"))
    assert broker.held == 5
    assert stop.orderStatus.status == "PendingSubmit"
    assert stop.order.totalQuantity == 9 and stop.orderStatus.remaining == 0
    assert not stop.fills and not await broker.reqAllOpenOrdersAsync()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["auxPrice", "ocaType"])
async def test_emergency_poll_does_not_close_gap_on_changed_stop_terms(monkeypatch, changed):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type, broker.held = 9, "test", 2, 9
    await run.poll()
    run.place(p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56"))
    original = broker.reqAllOpenOrdersAsync

    async def altered():
        rows = await original()
        setattr(rows[0].order, changed, 49 if changed == "auxPrice" else 1)
        return rows

    broker.reqAllOpenOrdersAsync = altered
    run.emergency = True
    await run.poll()
    assert run.gap_started is not None
    assert not any(e["event"] == "protection gap ended" for e in events)
    assert not broker.cancels


@pytest.mark.asyncio
async def test_poll_records_restored_protection_before_oversell_halt(monkeypatch):
    p, broker, run, events = scenario(monkeypatch)
    run.planned_quantity, run.group, run.oca_type, broker.held = 9, "test", 2, 9
    await run.poll()
    target = run.place(
        p.LimitOrder("SELL", 10, 62, ocaGroup="test", ocaType=2), "target", p.Decimal("56")
    )
    run.observe_excess(9, [target])
    broker.clock[0] += timedelta(seconds=11)
    run.place(p.StopOrder("SELL", 9, 50, ocaGroup="test", ocaType=2), "stop", p.Decimal("56"))
    with pytest.raises(p.OwnSellExcess):
        await run.poll()
    assert run.gap_started is None
    assert len([e for e in events if e["event"] == "protection gap ended"]) == 1
    assert not broker.cancels
