"""What the application's own rails say about one symbol, right now.

Every rail is ASKED of its owner. Nothing here reimplements a rule, because
the rails live in four subsystems and a second derivation is how they drift.

The most important tests in this file are the ones about what the verdict
does NOT claim: it never asks the sizer, it reports the FIRST refusal rather
than implying it enumerated all of them, and a rail it cannot evaluate yet is
neither a pass nor a fail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.autonomy.gate import AccountState, AutonomyGate
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.presentation.symbol_verdict import build_verdict

# A Monday, inside ASX continuous trading and inside "Morning Trend", which is
# an autonomy-eligible phase.
_SYD_MORNING = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)

# The same Monday, but 13:00 Sydney (AEST, UTC+10) - inside ASX continuous
# trading and inside "Midday Lull" (elapsed fraction 0.5 of the 10:00-16:00
# session), which is open but NOT an autonomy-eligible phase. The fixed clock
# every other test uses sits inside an eligible phase, which is exactly why
# the asymmetry this test guards went uncaught (M135).
_SYD_MIDDAY_LULL = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)


class _Engine:
    """Stands in for StrategyEngine's two public eligibility accessors."""

    def __init__(self, eligible: bool = True, mass: float | None = 0.72) -> None:
        self._eligible = eligible
        self._mass = mass

    def is_eligible(self, strategy) -> bool:
        return self._eligible

    def eligible_mass(self, strategy) -> float | None:
        return self._mass


class _Strategy:
    name = "swing"

    def suitable_regimes(self):
        return set()


def _verdict(**overrides):
    kwargs = dict(
        symbol="BHP.AX",
        positions=[],
        position_views=[],
        strategies=[_Strategy()],
        strategy_engine=_Engine(),
        gate=AutonomyGate(
            Settings(_env_file=None, execution_mode="auto", autonomous_strategies="swing"),
            KillSwitch(),
        ),
        account=AccountState(equity=1_000_000.0, cash=1_000_000.0, day_pnl_pct=0.0),
        entry_refusal=lambda symbol: None,
        is_quarantined=lambda symbol: False,
        settings=Settings(_env_file=None),
        last_price=41.50,
        now=_SYD_MORNING,
    )
    kwargs.update(overrides)
    return build_verdict(**kwargs)


def test_an_unheld_symbol_reports_entry_rails():
    verdict = _verdict()
    assert verdict.held is False
    names = {check.name for check in verdict.checks}
    assert "session" in names
    assert "allow list" in names


def test_an_unheld_symbol_reports_no_sell_rails():
    """A verdict that reported the minimum hold for a symbol the account does
    not own would be answering a question nobody asked, about a position that
    does not exist."""
    verdict = _verdict()
    names = {check.name for check in verdict.checks}
    assert "minimum hold" not in names
    assert "time stop" not in names


def test_a_held_symbol_reports_sell_rails_not_entry_rails():
    position = Position(symbol="BHP.AX", quantity=300.0, avg_price=40.0)
    view = _StubView(symbol="BHP.AX", pnl_r=-0.21, stop_distance=0.08, notes=("held until 3 Sep",))
    verdict = _verdict(positions=[position], position_views=[view])

    assert verdict.held is True
    names = {check.name for check in verdict.checks}
    assert "allow list" not in names, "the entry allow list says nothing about selling"
    assert "position" in names


def test_a_rail_that_cannot_be_evaluated_yet_is_neither_pass_nor_fail():
    """Before any RegimeEvent there is no distribution to read.
    `StrategyEngine.eligible_mass` returns None and its docstring says callers
    must present that as "not yet known" rather than as a measurement.
    Rendering it as a pass would claim the regime permits a strategy nobody
    has classified yet."""
    verdict = _verdict(strategy_engine=_Engine(eligible=False, mass=None))
    regime = _find(verdict.per_strategy[0].checks, "regime")
    assert regime.passed is None
    assert "not yet known" in regime.detail.lower()


def test_the_allow_list_refusal_is_the_oms_own_words():
    verdict = _verdict(entry_refusal=lambda symbol: "symbol not on the entry allow list")
    check = _find(verdict.checks, "allow list")
    assert check.passed is False
    assert "entry allow list" in check.detail


def test_first_refusal_names_one_rail_and_does_not_claim_an_audit():
    """The autonomy gate short-circuits. Saying "the first rail that would
    refuse" is true; implying every rail was evaluated is not."""
    verdict = _verdict(entry_refusal=lambda symbol: "symbol not on the entry allow list")
    assert verdict.per_strategy[0].first_refusal
    assert "first" in verdict.headline.lower()


def test_nothing_refusing_says_so_without_promising_a_fill():
    verdict = _verdict()
    assert verdict.per_strategy[0].first_refusal == ""


def test_a_held_symbol_session_check_passes_outside_autonomy_eligible_phase():
    """AutonomyGate.evaluate gates a SELL on `is_open` only - session phase
    only binds buys (gate.py ~146-158). During Midday Lull, an open but
    non-eligible phase, `_session_check` on the held branch must agree with
    the gate's own probe rather than reporting the buy-side rule and handing
    the headline a refusal the gate itself would not raise.
    """
    position = Position(symbol="BHP.AX", quantity=300.0, avg_price=40.0)
    view = _StubView(symbol="BHP.AX", pnl_r=0.1, stop_distance=0.08)
    verdict = _verdict(positions=[position], position_views=[view], now=_SYD_MIDDAY_LULL)

    session = _find(verdict.checks, "session")
    assert session.passed is True
    assert "not eligible for unattended execution" not in verdict.headline
    assert "no rail checked here would refuse it" in verdict.headline


def test_a_quarantined_symbol_is_refused():
    verdict = _verdict(is_quarantined=lambda symbol: True)
    check = _find(verdict.checks, "corporate action")
    assert check.passed is False


def test_one_entry_per_deployed_strategy():
    class _Other(_Strategy):
        name = "breakout"

    verdict = _verdict(strategies=[_Strategy(), _Other()])
    assert [rules.strategy for rules in verdict.per_strategy] == ["swing", "breakout"]


def test_symbol_level_rails_are_not_repeated_per_strategy():
    """The session and the allow list do not depend on which strategy is
    asking. Flattening them would print the same refusal twice on a
    two-strategy account."""

    class _Other(_Strategy):
        name = "breakout"

    verdict = _verdict(strategies=[_Strategy(), _Other()])
    for rules in verdict.per_strategy:
        assert {c.name for c in rules.checks}.isdisjoint({"session", "allow list"})


def test_as_dicts_is_plain_data():
    """It crosses into AdvisoryContext, which imports nothing from the rest of
    the domain - that is what lets the safety tests build a context in
    isolation."""
    for entry in _verdict().as_dicts():
        assert set(entry) >= {"name", "passed", "detail"}
        assert all(isinstance(v, (str, bool, type(None))) for v in entry.values())


def _find(checks, name):
    matching = [check for check in checks if check.name == name]
    assert matching, f"no check named {name!r} in {[c.name for c in checks]}"
    return matching[0]


class _StubView:
    """Only the PositionView fields the verdict reads."""

    def __init__(self, symbol, pnl_r=None, stop_distance=None, notes=()):
        self.symbol = symbol
        self.pnl_r = pnl_r
        self.stop_distance = stop_distance
        self.notes = tuple(notes)
        self.entry_price = 40.0
        self.last_price = 41.5
        self.pnl_pct = 0.0375
        self.exit_distance = None
        self.risk_share = 0.4
        self.quantity = 300.0
