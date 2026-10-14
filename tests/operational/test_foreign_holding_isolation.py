"""Operational sizing and holding checks use qualified QAT holdings only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from test_operational_adapter import NOW
from test_recommendation_cards import rig

from qat.data.broker.adapter import Position
from qat.domain.strategies.authoritative_swing.model import SplitFactor
from qat.operational.consolidations import ConsolidationLedger, ConsolidationReconciler
from qat.operational.exit_alerts import ExitAlertService
from qat.operational.history import CorporateAction


@pytest.mark.asyncio
async def test_foreign_holding_suppresses_new_card(tmp_path, monkeypatch) -> None:
    service, candidates, broker, _, _, _, _, _ = rig(tmp_path)
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)

    async def positions() -> list[Position]:
        return [foreign]

    monkeypatch.setattr(broker, "positions", positions)
    card = (await service.publish(candidates, now=NOW))[0]
    assert card.quantity == 0
    assert any("foreign holding" in reason for reason in card.reasons)


@pytest.mark.asyncio
async def test_consolidation_and_exit_check_ignore_same_symbol_foreign_holding(
    tmp_path, monkeypatch
) -> None:
    service, _, broker, _, store, _, _, _ = rig(tmp_path)
    managed = Position("BHP.AX", 50, 20, account="DU1", con_id=1001, qat_holding=True)
    foreign = Position("BHP.AX", 18, 20, account="DU1", con_id=2002, qat_holding=False)

    async def positions() -> list[Position]:
        return [managed, foreign]

    monkeypatch.setattr(broker, "positions", positions)
    action = CorporateAction(
        "BHP.AX",
        date(2026, 1, 6),
        SplitFactor(2, 1),
        Decimal(0),
        "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
    )
    ledger = ConsolidationLedger(store.database.parent / "managed_positions.sqlite3")
    result = await ConsolidationReconciler(broker, ledger).apply(
        action, previous_quantity=100, total_basis_cents=100_000, cash_in_lieu_cents=0
    )

    assert result.broker_quantity == 50
    assert not result.frozen
    assert await ExitAlertService(service)._holding_matches("BHP.AX", 50)
