"""Approved Phase 2 exit plans issue manual TWS alerts without order submission."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from test_operational_adapter import NOW
from test_operational_history import HALT_FIXTURE
from test_recommendation_cards import rig

from qat.data.broker.adapter import Position
from qat.domain.strategies.authoritative_swing.lifecycle import ConfirmedFill
from qat.operational.exit_alerts import ExitAlertService
from qat.operational.history import SYDNEY, Session, append_halt, digest


def extend_calendar(cards, *, through_ninth=False) -> None:
    calendar = cards.snapshot.calendar
    days = (date(2026, 1, 8), date(2026, 1, 9)) if through_ninth else (date(2026, 1, 8),)
    extended = replace(
        calendar,
        sessions=calendar.sessions
        + tuple(Session(day, datetime.combine(day, time(10), SYDNEY)) for day in days),
        coverage_end=days[-1],
    )
    snapshot = replace(cards.snapshot, calendar=extended, content_hash="")
    cards.snapshot = replace(snapshot, content_hash=digest(snapshot.identity()))


@pytest.mark.asyncio
async def test_entry_fill_emits_exact_protection_and_partial_target_alerts(tmp_path) -> None:
    cards, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    fill = ConfirmedFill(
        "entry-1",
        date(2026, 1, 7),
        "buy",
        instruction.quantity,
        instruction.entry_limit,
        "entry_fill",
    )
    alerts = await exits.entry_fill(card.card_id, fill)
    assert {alert.kind for alert in alerts} == {
        "banked_protective_stop",
        "runner_protective_stop",
        "partial_target",
    }
    banked_stop = next(alert for alert in alerts if alert.kind == "banked_protective_stop")
    runner_stop = next(alert for alert in alerts if alert.kind == "runner_protective_stop")
    target = next(alert for alert in alerts if alert.kind == "partial_target")
    assert banked_stop.quantity + runner_stop.quantity == instruction.quantity
    assert banked_stop.price == runner_stop.price == instruction.structural_stop
    assert banked_stop.order_type == "STOP_GTC_OCA_WITH_TARGET"
    assert runner_stop.order_type == "STOP_GTC"
    assert banked_stop.oca_group == target.oca_group
    assert runner_stop.oca_group is None
    assert target.quantity == (instruction.quantity + 1) // 2
    assert target.price == fill.price + (fill.price - instruction.structural_stop)
    assert all(alert.side == "sell" and alert.manual_tws_only for alert in alerts)
    assert events.status(card.card_id) == "approved"
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_target_fill_moves_runner_to_breakeven_without_loosening_protection(tmp_path) -> None:
    cards, result, broker, *_ = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    await exits.entry_fill(
        card.card_id,
        ConfirmedFill(
            "entry-1",
            date(2026, 1, 7),
            "buy",
            instruction.quantity,
            instruction.entry_limit,
            "entry_fill",
        ),
    )
    state = exits.positions[card.card_id]
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(state.runner_quantity), float(instruction.entry_limit)
    )
    alerts = await exits.target_fill(
        card.card_id,
        ConfirmedFill(
            "target-1",
            date(2026, 1, 7),
            "sell",
            state.banked_quantity,
            state.target_price,
            "partial_target",
        ),
    )
    assert len(alerts) == 1
    assert alerts[0].kind == "breakeven_stop"
    assert alerts[0].price == instruction.entry_limit
    assert alerts[0].quantity == state.runner_quantity
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_exit_state_survives_service_restart_and_replayed_fill_is_idempotent(
    tmp_path,
) -> None:
    cards, result, broker, *_ = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    fill = ConfirmedFill(
        "entry-restart",
        date(2026, 1, 7),
        "buy",
        instruction.quantity,
        instruction.entry_limit,
        "entry_fill",
    )
    first = ExitAlertService(cards)
    assert len(await first.entry_fill(card.card_id, fill)) == 3
    restarted = ExitAlertService(cards)
    assert restarted.positions[card.card_id] == first.positions[card.card_id]
    assert await restarted.entry_fill(card.card_id, fill) == ()
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_close_invalidation_and_time_stop_collapse_to_one_due_exit(tmp_path) -> None:
    cards, result, broker, *_ = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    extend_calendar(cards)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    await exits.entry_fill(
        card.card_id,
        ConfirmedFill(
            "entry-1",
            date(2026, 1, 7),
            "buy",
            instruction.quantity,
            instruction.entry_limit,
            "entry_fill",
        ),
    )
    alerts = await exits.completed_close(
        card.card_id,
        session=date(2026, 1, 7),
        high=instruction.entry_limit,
        close=instruction.structural_stop,
        ema20=instruction.entry_limit,
        atr14=Decimal("0.1"),
    )
    due = [alert for alert in alerts if alert.kind == "next_open_exit"]
    assert len(due) == 1
    assert due[0].quantity == instruction.quantity
    assert "daily_invalidation" in due[0].reason
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_manual_management_is_recorded_and_alerts_continue(tmp_path) -> None:
    cards, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    exits.switch_to_manual(card.card_id, "operator", "operator request")
    alerts = await exits.entry_fill(
        card.card_id,
        ConfirmedFill(
            "entry-1",
            date(2026, 1, 7),
            "buy",
            instruction.quantity,
            instruction.entry_limit,
            "entry_fill",
        ),
    )
    assert alerts
    assert exits.is_manual(card.card_id)
    assert any(e.kind == "manual_management" for e in events.events)
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_halt_defers_due_exit_to_first_resumed_open_and_keeps_stop(tmp_path) -> None:
    cards, result, broker, *_ = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    extend_calendar(cards, through_ninth=True)
    path = tmp_path / "halts-extended.jsonl"
    path.write_bytes(HALT_FIXTURE.read_bytes())
    halts = append_halt(
        path,
        "BHP.AX",
        date(2026, 1, 8),
        date(2026, 1, 8),
        "asx_notice",
        "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
    )
    cards.snapshot = replace(cards.snapshot, halts=halts)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    await exits.entry_fill(
        card.card_id,
        ConfirmedFill(
            "entry-1",
            date(2026, 1, 7),
            "buy",
            instruction.quantity,
            instruction.entry_limit,
            "entry_fill",
        ),
    )
    alerts = await exits.completed_close(
        card.card_id,
        session=date(2026, 1, 7),
        high=instruction.entry_limit,
        close=instruction.structural_stop,
        ema20=instruction.entry_limit,
        atr14=Decimal("0.1"),
    )
    due = next(alert for alert in alerts if alert.kind == "next_open_exit")
    assert due.effective_open.date() == date(2026, 1, 9)
    assert exits.positions[card.card_id].current_stop == instruction.structural_stop
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_broker_holding_mismatch_freezes_exit_plan(tmp_path) -> None:
    cards, result, broker, *_ = rig(tmp_path)
    card = (await cards.publish(result, now=NOW))[0]
    instruction = await cards.approve(card.card_id, "operator", now=NOW)
    broker._positions[card.candidate.symbol] = Position(
        card.candidate.symbol, float(instruction.quantity - 1), float(instruction.entry_limit)
    )
    exits = ExitAlertService(cards)
    with pytest.raises(ValueError, match="holding mismatch"):
        await exits.entry_fill(
            card.card_id,
            ConfirmedFill(
                "entry-1",
                date(2026, 1, 7),
                "buy",
                instruction.quantity,
                instruction.entry_limit,
                "entry_fill",
            ),
        )
    assert cards.managed_positions.is_frozen(card.candidate.symbol)
    assert broker.transmissions == 0


def test_manual_or_looser_change_requires_fresh_signoff(tmp_path) -> None:
    cards, _, _, _, _, _, _, events = rig(tmp_path)
    exits = ExitAlertService(cards)
    with pytest.raises(ValueError, match="fresh operator sign-off"):
        exits.approve_manual_change(
            "card-1",
            "operator",
            "loosen stop",
            adds_exposure=False,
            loosens_protection=True,
            signed_off=False,
        )
    exits.approve_manual_change(
        "card-1",
        "operator",
        "loosen stop",
        adds_exposure=False,
        loosens_protection=True,
        signed_off=True,
    )
    assert any(event.kind == "change_approval" for event in events.events)
