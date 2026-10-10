"""Step 4 advisory cards over recorded operational fixtures and a fake broker."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from test_operational_adapter import NOW, SESSION, prepared
from test_operational_history import ingest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.operational.cards import (
    CardEventStore,
    CardService,
    ReconfirmationRequired,
    TransmissionDisabled,
)


class OfflineBroker(MockBroker):
    def __init__(self) -> None:
        super().__init__(seed=1)
        self.equity = 100_000.0
        self.transmissions = 0

    async def account(self) -> AccountSummary:
        return AccountSummary(self.equity, self.equity, self.equity)

    async def place_order(self, order: Order) -> Order:
        self.transmissions += 1
        raise AssertionError("advisory card transmitted to broker")


def rig(tmp_path, *, live=False, costs=False):
    adapter, snapshot, store, cal, _, _ = prepared(tmp_path, qualified=True)
    result = adapter.run(snapshot, now=NOW)
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path / "phase1"),
        market="ASX",
        trading_mode="live" if live else "paper",
        execution_mode="recommend",
        max_order_pct_of_cash=1.0,
        apply_costs_in_paper=costs,
    )
    bus = EventBus()
    switch = KillSwitch(data_dir=tmp_path / "phase1")
    broker = OfflineBroker()
    risk = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, risk, switch, settings=settings)
    events = CardEventStore(store.database.parent / "card_decisions.jsonl")
    service = CardService(adapter, snapshot, oms, settings, events, store)
    return service, result, broker, risk, store, cal, switch, events


@pytest.mark.asyncio
async def test_card_is_fixed_fractional_and_never_calls_edge_sizer(tmp_path, monkeypatch) -> None:
    service, result, broker, risk, *_ = rig(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("edge-based sizing path called")

    monkeypatch.setattr(risk.sizer, "size", forbidden)
    monkeypatch.setattr(risk, "evaluate_order", forbidden)
    cards = await service.publish(result, now=NOW)
    assert len(cards) == 1
    card = cards[0]
    assert card.quantity >= 2
    assert card.sizing_basis == "fixed 1% risk to stop, no edge assumed"
    assert card.candidate.label == "unvalidated strategy, no demonstrated edge"
    assert card.risk <= Decimal("1000")
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_approval_recomputes_equity_and_requires_reconfirmation(tmp_path) -> None:
    service, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    broker.equity = 50_000.0
    with pytest.raises(ReconfirmationRequired) as change:
        await service.approve(card.card_id, "operator", now=NOW + timedelta(minutes=1))
    assert change.value.previous == card.quantity
    assert change.value.current < card.quantity
    assert events.status(card.card_id) == "created"
    instruction = await service.approve(
        card.card_id, "operator", now=NOW + timedelta(minutes=1), reconfirm=True
    )
    assert instruction.quantity == change.value.current
    assert instruction.order_id
    assert broker.transmissions == 0
    with pytest.raises(TransmissionDisabled):
        await service.submit(card.card_id, now=NOW + timedelta(minutes=1))
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_correction_appends_revocation_and_blocks_approval_and_submission(tmp_path) -> None:
    service, result, broker, _, store, cal, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    original = store.decision_bars("BHP.AX", SESSION)[-1].bar
    ingest(
        store,
        (replace(original, finalised=False, retrieved_at=NOW + timedelta(minutes=1)),),
        cal,
    )
    shown = service.display(card.card_id, now=NOW + timedelta(minutes=2))
    assert shown.status == "revoked"
    assert events.status(card.card_id) == "revoked"
    with pytest.raises(ValueError, match="revoked"):
        await service.approve(card.card_id, "operator", now=NOW + timedelta(minutes=2))
    with pytest.raises(ValueError, match="revoked"):
        await service.submit(card.card_id, now=NOW + timedelta(minutes=2))
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_expiry_is_checked_at_display_approval_and_submission(tmp_path) -> None:
    service, result, broker, *_ = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    expired = card.candidate.expires_at
    assert service.display(card.card_id, now=expired).status == "expired"
    with pytest.raises(ValueError, match="expired"):
        await service.approve(card.card_id, "operator", now=expired)
    with pytest.raises(ValueError, match="expired"):
        await service.submit(card.card_id, now=expired)
    assert broker.transmissions == 0


def test_live_account_is_refused_by_construction(tmp_path) -> None:
    with pytest.raises(ValueError, match="paper"):
        rig(tmp_path, live=True)


@pytest.mark.asyncio
async def test_kill_switch_blocks_approval_after_card_creation(tmp_path) -> None:
    service, result, broker, _, _, _, switch, _ = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    switch.trip("operator halt")
    with pytest.raises(ValueError, match="kill-switch"):
        await service.approve(card.card_id, "operator", now=NOW + timedelta(minutes=1))
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_duplicate_approval_returns_one_reserved_order(tmp_path) -> None:
    service, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    first = await service.approve(card.card_id, "operator", now=NOW)
    second = await service.approve(card.card_id, "operator", now=NOW)
    assert second == first
    assert [e.kind for e in events.events] == ["created", "approved"]
    assert len(service.order_store.orders) == 1
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_duplicate_approval_still_returns_original_after_later_alert_events(tmp_path) -> None:
    service, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    first = await service.approve(card.card_id, "operator", now=NOW)
    events.append("exit_alert", card.card_id, {"kind": "protective_stop"})
    second = await service.approve(card.card_id, "operator", now=NOW)
    assert second == first
    assert len(service.order_store.orders) == 1
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_decline_disables_approval_without_oms_order(tmp_path) -> None:
    service, result, broker, _, _, _, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    service.decline(card.card_id, "operator", now=NOW)
    assert events.status(card.card_id) == "declined"
    with pytest.raises(ValueError, match="declined"):
        await service.approve(card.card_id, "operator", now=NOW)
    assert not service.order_store.orders
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_accepted_correction_after_approval_revokes_before_submission(tmp_path) -> None:
    service, result, broker, _, store, cal, _, events = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    await service.approve(card.card_id, "operator", now=NOW)
    original = store.decision_bars("BHP.AX", SESSION)[-1].bar
    ingest(
        store,
        (replace(original, finalised=False, retrieved_at=NOW + timedelta(minutes=1)),),
        cal,
    )
    with pytest.raises(ValueError, match="revoked"):
        await service.submit(card.card_id, now=NOW + timedelta(minutes=2))
    assert events.status(card.card_id) == "revoked"
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_authority_snapshot_change_revokes_existing_card(tmp_path) -> None:
    service, result, broker, *_ = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]
    await service.approve(card.card_id, "operator", now=NOW)
    service.snapshot = replace(service.snapshot, reasons=("authority corrected",), content_hash="")
    with pytest.raises(ValueError, match="revoked"):
        await service.submit(card.card_id, now=NOW)
    assert service.events.status(card.card_id) == "revoked"
    assert broker.transmissions == 0


@pytest.mark.asyncio
async def test_history_integrity_failure_revokes_before_display_or_approval(
    tmp_path, monkeypatch
) -> None:
    service, result, broker, _, store, *_ = rig(tmp_path)
    card = (await service.publish(result, now=NOW))[0]

    def broken(*args, **kwargs):
        raise ValueError("history chain broken")

    monkeypatch.setattr(store, "decision_bars", broken)
    assert service.display(card.card_id, now=NOW).status == "revoked"
    with pytest.raises(ValueError, match="revoked"):
        await service.approve(card.card_id, "operator", now=NOW)
    assert broker.transmissions == 0


def test_card_decision_store_rejects_foreign_namespace_and_tampering(tmp_path) -> None:
    with pytest.raises(ValueError, match="OPERATIONAL"):
        CardEventStore(tmp_path / "research" / "cards.jsonl")
    service, _, _, _, store, _, _, events = rig(tmp_path)
    assert service.events is events
    events.append("created", "one", {"symbol": "BHP.AX"})
    assert CardEventStore(store.database.parent / "card_decisions.jsonl").status("one") == "created"
    path = store.database.parent / "card_decisions.jsonl"
    path.write_text(path.read_text().replace("BHP.AX", "RIO.AX"), encoding="utf-8")
    with pytest.raises(ValueError, match="chain"):
        CardEventStore(path)


def test_card_decisions_cannot_read_or_write_research_or_promotion_stores(tmp_path) -> None:
    for evidence_name in ("research", "promotion"):
        root = tmp_path / evidence_name / "OPERATIONAL"
        root.mkdir(parents=True)
        (root / "namespace.json").write_bytes(
            canonical_payload({"namespace": "OPERATIONAL", "schema": 1})
        )
        with pytest.raises(ValueError, match="OPERATIONAL"):
            CardEventStore(root / "card_decisions.jsonl")


def test_card_decision_store_refuses_truncation_before_next_append(tmp_path) -> None:
    _, _, _, _, store, _, _, events = rig(tmp_path)
    events.append("created", "one", {"symbol": "BHP.AX"})
    (store.database.parent / "card_decisions.jsonl").write_bytes(b"")
    with pytest.raises(ValueError, match="rollback|truncation"):
        events.append("approved", "one", {"quantity": 10})


@pytest.mark.asyncio
async def test_phase1_cost_rail_can_block_a_card_with_reason(tmp_path) -> None:
    service, result, *_ = rig(tmp_path, costs=True)
    card = (await service.publish(result, now=NOW))[0]
    assert card.quantity == 0
    assert "Phase 1 cost-to-risk rail blocked" in card.reasons


@pytest.mark.asyncio
async def test_missing_operational_history_for_existing_holding_blocks_portfolio_risk(
    tmp_path,
) -> None:
    service, result, broker, *_ = rig(tmp_path)
    broker._positions["UNKNOWN.AX"] = Position("UNKNOWN.AX", 10.0, 20.0)
    card = (await service.publish(result, now=NOW))[0]
    assert card.quantity == 0
    assert "holding UNKNOWN.AX lacks eligible OPERATIONAL history" in card.reasons
    assert broker.transmissions == 0
