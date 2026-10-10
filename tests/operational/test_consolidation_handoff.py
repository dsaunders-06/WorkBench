"""Authority-driven consolidation accounting against reported fake holdings."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from test_operational_adapter import NOW
from test_recommendation_cards import rig

from qat.data.broker.adapter import Position
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.domain.strategies.authoritative_swing.model import SplitFactor
from qat.operational.consolidations import ConsolidationLedger, ConsolidationReconciler
from qat.operational.history import CorporateAction

NOTICE = "https://www.asx.com.au/markets/trade-our-cash-market/announcements"


def action(ratio: SplitFactor | None = None) -> CorporateAction:
    return CorporateAction(
        "BHP.AX", date(2026, 1, 6), ratio or SplitFactor(2, 1), Decimal(0), NOTICE
    )


@pytest.mark.asyncio
async def test_matching_consolidation_accepts_broker_holding_and_preserves_cents(tmp_path) -> None:
    service, _, broker, _, store, *_ = rig(tmp_path)
    broker._positions["BHP.AX"] = Position("BHP.AX", 50.0, 20.0)
    ledger = ConsolidationLedger(store.database.parent / "managed_positions.sqlite3")
    result = await ConsolidationReconciler(broker, ledger).apply(
        action(), previous_quantity=100, total_basis_cents=100_001, cash_in_lieu_cents=0
    )
    assert result.broker_quantity == result.expected_whole_quantity == 50
    assert result.remaining_basis_cents == 100_001
    assert result.basis_sold_cents == 0
    assert not ledger.is_frozen("BHP.AX")
    assert service.settings.trading_mode == "paper"


@pytest.mark.asyncio
async def test_fractional_part_is_realised_sale_with_pro_rata_cent_basis(tmp_path) -> None:
    _, _, broker, _, store, *_ = rig(tmp_path)
    broker._positions["BHP.AX"] = Position("BHP.AX", 3.0, 20.0)
    ledger = ConsolidationLedger(store.database.parent / "managed_positions.sqlite3")
    result = await ConsolidationReconciler(broker, ledger).apply(
        action(SplitFactor(3, 2)),
        previous_quantity=5,
        total_basis_cents=10_005,
        cash_in_lieu_cents=1_234,
    )
    assert result.fractional_quantity.numerator == 1
    assert result.fractional_quantity.denominator == 3
    assert result.basis_sold_cents == 1_000  # 1000.5, half-even
    assert result.remaining_basis_cents == 9_005
    assert result.realised_profit_cents == 234
    assert result.basis_sold_cents + result.remaining_basis_cents == 10_005
    assert result.broker_quantity == 3


@pytest.mark.asyncio
async def test_broker_quantity_mismatch_freezes_symbol_and_suppresses_card(tmp_path) -> None:
    service, candidates, broker, _, store, *_ = rig(tmp_path)
    broker._positions["BHP.AX"] = Position("BHP.AX", 49.0, 20.0)
    ledger = ConsolidationLedger(store.database.parent / "managed_positions.sqlite3")
    result = await ConsolidationReconciler(broker, ledger).apply(
        action(), previous_quantity=100, total_basis_cents=100_000, cash_in_lieu_cents=0
    )
    assert result.frozen
    assert "expected 50" in result.reason
    assert ledger.is_frozen("BHP.AX")
    assert not await service.publish(candidates, now=NOW)


def test_managed_ledger_cannot_open_research_or_promotion_store(tmp_path) -> None:
    for evidence_name in ("research", "promotion"):
        root = tmp_path / evidence_name / "OPERATIONAL"
        root.mkdir(parents=True)
        (root / "namespace.json").write_bytes(
            canonical_payload({"namespace": "OPERATIONAL", "schema": 1})
        )
        with pytest.raises(ValueError, match="OPERATIONAL"):
            ConsolidationLedger(root / "managed_positions.sqlite3")
