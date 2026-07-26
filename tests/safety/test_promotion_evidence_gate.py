"""Evidence-based promotion (spec M16, Phase 6).

Being on the operator's `autonomous_strategies` list is a statement of intent.
With `enforce_promotion_evidence` on, it must also still be true: the strategy
has to keep meeting the bar on its own realised trades, so one that degrades
stops trading unattended without anyone having to notice and edit a setting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.autonomy.gate import AccountState, AutonomyGate
from qat.domain.performance.scorecard import build_scorecard
from qat.domain.performance.trades import ClosedTrade
from qat.domain.risk_engine.kill_switch import KillSwitch

_NY = ZoneInfo("America/New_York")
OPEN_US = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)
_BASE = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)


def _trade(pnl_per_share: float, day: int = 0) -> ClosedTrade:
    return ClosedTrade(
        symbol="AAA",
        strategy="swing",
        quantity=10.0,
        entry_price=100.0,
        exit_price=100.0 + pnl_per_share,
        stop_price=95.0,
        opened_at=_BASE + timedelta(days=day),
        closed_at=_BASE + timedelta(days=day, hours=6),
    )


def _strong_record() -> list[ClosedTrade]:
    return [_trade(10.0) for _ in range(24)] + [_trade(-5.0) for _ in range(8)]


def _weak_record() -> list[ClosedTrade]:
    return [_trade(-5.0) for _ in range(30)]


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "execution_mode": "auto",
        "autonomous_strategies": "swing",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _gate(settings: Settings, trades: list[ClosedTrade]) -> AutonomyGate:
    return AutonomyGate(
        settings,
        KillSwitch(),
        scorecard_source=lambda name: build_scorecard(name, trades, settings),
    )


def _order(side: str = "buy") -> Order:
    return Order(
        symbol="AAPL",
        side=side,  # type: ignore[arg-type]
        quantity=10.0,
        order_id="o1",
        status="pending_signoff",
        reference_price=100.0,
        strategy="swing",
    )


def _account() -> AccountState:
    return AccountState(equity=100_000.0, cash=50_000.0, day_pnl_pct=0.0)


def test_enforcement_is_off_by_default():
    """A fresh install has no trade history and would otherwise block
    everything for a reason that looks like a bug."""
    assert Settings(_env_file=None).enforce_promotion_evidence is False


def test_without_enforcement_the_operator_list_is_sufficient():
    gate = _gate(_settings(), _weak_record())
    assert gate.evaluate(_order(), _account(), now=OPEN_US).allowed is True


def test_with_enforcement_a_degraded_strategy_is_blocked():
    gate = _gate(_settings(enforce_promotion_evidence=True), _weak_record())
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "no longer meets the evidence bar" in decision.reason


def test_with_enforcement_a_strong_strategy_still_trades():
    gate = _gate(_settings(enforce_promotion_evidence=True), _strong_record())
    assert gate.evaluate(_order(), _account(), now=OPEN_US).allowed is True


def test_with_enforcement_a_strategy_with_no_history_is_blocked():
    """The important case for a fresh promotion: intent without evidence."""
    gate = _gate(_settings(enforce_promotion_evidence=True), [])
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "evidence bar" in decision.reason


def test_the_block_reason_names_what_actually_failed():
    """A block an operator cannot diagnose is a block they will disable."""
    gate = _gate(_settings(enforce_promotion_evidence=True), _weak_record())
    reason = gate.evaluate(_order(), _account(), now=OPEN_US).reason
    assert "net P&L" in reason or "closed trades" in reason


def test_the_evidence_gate_never_blocks_a_protective_sell():
    """Exits are risk-reducing. A weak track record is not a reason to refuse
    to close a position."""
    gate = _gate(_settings(enforce_promotion_evidence=True), _weak_record())
    assert gate.evaluate(_order(side="sell"), _account(), now=OPEN_US).allowed is True


def test_a_missing_scorecard_source_does_not_block():
    """Enforcement with no evidence source wired would otherwise silently halt
    every buy for a reason with no visible cause."""
    gate = AutonomyGate(_settings(enforce_promotion_evidence=True), KillSwitch())
    assert gate.evaluate(_order(), _account(), now=OPEN_US).allowed is True


def test_the_gate_still_requires_the_operator_list_even_with_a_strong_record():
    """Evidence is necessary, not sufficient - a strategy the operator never
    promoted does not start trading because its numbers look good."""
    gate = _gate(
        _settings(autonomous_strategies="", enforce_promotion_evidence=True), _strong_record()
    )
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "not on the autonomous list" in decision.reason
