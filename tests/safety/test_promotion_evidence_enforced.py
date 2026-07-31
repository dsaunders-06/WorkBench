"""Evidence enforcement is not optional on a live account (M29).

The policy said "earn autonomy" and the code granted it anyway. Turning the
flag on during the paper phase is circular, though: the bar is 30 closed
trades, paper is where those trades come from, and enforcing it there means
nothing trades, so no evidence is produced, so the bar is never met.

Bound to what is actually at stake instead. Paper collects the evidence; live
requires it, whatever the flag says.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.autonomy.gate import AccountState, AutonomyGate
from qat.domain.performance.scorecard import StrategyScorecard, build_scorecard
from qat.domain.risk_engine.kill_switch import KillSwitch


def test_paper_does_not_enforce_by_default():
    """Otherwise the paper phase can never produce the evidence it exists for."""
    settings = Settings(_env_file=None, trading_mode="paper")

    assert settings.enforce_promotion_evidence is False
    assert settings.promotion_evidence_enforced is False


def test_paper_can_opt_in_early():
    settings = Settings(_env_file=None, trading_mode="paper", enforce_promotion_evidence=True)

    assert settings.promotion_evidence_enforced is True


def test_live_enforces_whatever_the_flag_says():
    """The flag cannot be used to opt out of the bar with real money. Nobody
    has to remember to set it, and nobody can forget to."""
    settings = Settings(_env_file=None, trading_mode="live", enforce_promotion_evidence=False)

    assert settings.promotion_evidence_enforced is True


@pytest.mark.parametrize("flag", [True, False])
def test_live_is_enforced_in_both_flag_positions(flag: bool):
    settings = Settings(_env_file=None, trading_mode="live", enforce_promotion_evidence=flag)

    assert settings.promotion_evidence_enforced is True


# --- The gate honours it, not just the setting -----------------------------

_NY = ZoneInfo("America/New_York")
OPEN_US = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)


def _below_bar(strategy: str) -> StrategyScorecard:
    """A strategy with no history at all - exactly where swing sits today."""
    return build_scorecard(strategy, [], Settings(_env_file=None))


def _order() -> Order:
    return Order(
        order_id="o1",
        symbol="AAPL",
        side="buy",
        quantity=10.0,
        status="pending_signoff",
        strategy="swing",
        reference_price=100.0,
    )


def _account() -> AccountState:
    return AccountState(equity=100_000.0, cash=100_000.0, day_pnl_pct=0.0)


def test_a_paper_account_still_trades_while_it_gathers_evidence():
    """The circularity this design exists to avoid: paper must be able to
    produce the trades the bar is measured on."""
    settings = Settings(
        _env_file=None,
        trading_mode="paper",
        execution_mode="auto",
        autonomous_strategies="swing",
    )
    gate = AutonomyGate(settings, KillSwitch(), scorecard_source=_below_bar)

    decision = gate.evaluate(_order(), _account(), current_price=100.0, now=OPEN_US)

    assert decision.allowed is True


def test_a_live_account_refuses_a_strategy_below_the_bar():
    settings = Settings(
        _env_file=None,
        trading_mode="live",
        execution_mode="auto",
        autonomous_strategies="swing",
        allow_autonomous_live_trading=True,
        enforce_promotion_evidence=False,  # deliberately off, and ignored
    )
    gate = AutonomyGate(settings, KillSwitch(), scorecard_source=_below_bar)

    decision = gate.evaluate(_order(), _account(), current_price=100.0, now=OPEN_US)

    assert decision.allowed is False
    assert "evidence bar" in decision.reason
