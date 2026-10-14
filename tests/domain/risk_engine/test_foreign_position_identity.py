"""Portfolio risk for QAT positions must not mix same-symbol foreign contracts."""

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.risk_engine.governor import PortfolioGovernor


def test_snapshot_excludes_foreign_same_symbol_contract() -> None:
    governor = PortfolioGovernor(Settings(_env_file=None))
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001)
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)

    snapshot = governor.snapshot([managed, foreign], {"BHP.AX": 55}, 100_000)

    assert snapshot.position_count == 1
    assert snapshot.gross_exposure_dollars == 540
    assert snapshot.risk_by_symbol == {"BHP.AX": 45}


def test_foreign_contract_refuses_portfolio_exposure_addition() -> None:
    governor = PortfolioGovernor(Settings(_env_file=None))
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)

    decision = governor.evaluate("CBA.AX", 100, 9, 90, [foreign], {}, 100_000)

    assert not decision.allowed
    assert "foreign holding" in decision.reason
