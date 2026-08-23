"""Both screens ask about a symbol; both must be given the same material.

The Workbench passed `regime_label="unknown"` while the Advisor passed the live
regime, so the two could reach different views of one company at one moment for
no stated reason. One builder is what stops that returning - two copies drift,
and the one that drifts is the one nobody is reading.

The macro fields are deliberately NOT part of that material; see the test below
that pins the decision rather than leaving a gap for someone to "fix".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.presentation.advisory_inputs import build_advisory_context

# The material the builder FETCHES for itself. Both screens must receive the
# same of it, because differing on it is what let the two reach different views
# of one company.
_FETCHED = ("symbol", "next_earnings", "news")


@pytest.mark.asyncio
async def test_both_screens_get_the_same_fetched_material(advisory_runtime):
    """`advisory_runtime` is a stub runtime; see the conftest fixture."""
    advisor = await build_advisory_context(
        advisory_runtime, "BHP.AX", operator_question="is it cheap?"
    )
    workbench = await build_advisory_context(
        advisory_runtime, "BHP.AX", candidate_signal={"strategy": "swing"}
    )

    for field in _FETCHED:
        assert getattr(advisor, field) == getattr(workbench, field), field


@pytest.mark.asyncio
async def test_supplied_material_is_carried_through_unswapped(advisory_runtime):
    """`fundamentals` and `position` are SUPPLIED by the caller, not fetched, so
    asserting the two calls agree on them proves nothing when both default to
    empty - which is what an earlier version of this file did, twice.

    Passing different values and checking each lands where it was put is the
    version that can fail: it catches a builder that swapped two arguments, or
    dropped one, which the equality form could not see."""
    context = await build_advisory_context(
        advisory_runtime,
        "BHP.AX",
        fundamentals={"pe": 14.2},
        position={"entry_price": 40.0, "pnl_r": -0.21},
    )

    assert context.fundamentals == {"pe": 14.2}
    assert context.position == {"entry_price": 40.0, "pnl_r": -0.21}
    assert context.fundamentals != context.position


@pytest.mark.asyncio
async def test_the_workbench_no_longer_claims_the_regime_is_unknown(advisory_runtime):
    context = await build_advisory_context(
        advisory_runtime, "BHP.AX", regime_label="low_vol", regime_probs={"low_vol": 0.6}
    )
    assert context.regime_label == "low_vol"


@pytest.mark.asyncio
async def test_the_macro_fields_stay_empty_and_that_is_deliberate(advisory_runtime):
    """Not an oversight. `compute_macro_signal` needs an awaited bars fetch and
    the Regime Monitor computes it only on demand, so there is no current value
    to pass and wiring one here would mean a vendor call per question. Pinned
    so the next reader finds the decision rather than the gap."""
    context = await build_advisory_context(advisory_runtime, "BHP.AX")
    assert context.macro_signal == {}
    assert context.macro_series == {}


@pytest.mark.asyncio
async def test_one_question_fetches_the_news_once(advisory_runtime):
    """The Advisor used to fetch news TWICE per question - once for the sources
    block it shows the operator, once inside the builder for the model.

    `news_for` calls the vendor live every time and degrades silently to [] on
    failure, so two round trips milliseconds apart can disagree: a story
    publishes between them, or the second fails where the first succeeded. The
    operator would then be shown stories the model never received - M126's
    defect exactly, reproduced inside one screen.

    Counting the fetches is the only way to see it; the displayed text and the
    context agree in the happy path either way."""
    calls: list[str] = []

    class _CountingSource:
        def fetch(self, symbol: str) -> list:
            calls.append(symbol)
            return []

    advisory_runtime.news_source = _CountingSource()

    await build_advisory_context(advisory_runtime, "BHP.AX")

    assert calls == ["BHP.AX"], f"expected exactly one fetch, got {len(calls)}"


def build_verdict_for_test(runtime, symbol):
    """Exercises the REAL build_verdict rather than asserting about nothing.

    A guard that passes because it called no production code is the failure
    mode this project has met before - a rubber-stamp probe reporting success.
    """
    from qat.domain.autonomy.gate import AccountState, AutonomyGate
    from qat.domain.risk_engine.kill_switch import KillSwitch
    from qat.presentation.symbol_verdict import build_verdict

    class _Engine:
        def is_eligible(self, strategy):
            return True

        def eligible_mass(self, strategy):
            return 0.72

    class _Strategy:
        name = "swing"

        def suitable_regimes(self):
            return set()

    return build_verdict(
        symbol=symbol,
        positions=[],
        position_views=[],
        strategies=[_Strategy()],
        strategy_engine=_Engine(),
        gate=AutonomyGate(runtime.settings, KillSwitch()),
        account=AccountState(equity=1_000_000.0, cash=1_000_000.0, day_pnl_pct=0.0),
        entry_refusal=lambda s: None,
        is_quarantined=lambda s: False,
        settings=runtime.settings,
        last_price=41.50,
        now=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )


def test_the_advisory_path_writes_no_risk_decisions(tmp_path, monkeypatch, advisory_runtime):
    """⚠️ THE CONSTRAINT THAT SHAPED THE WHOLE DESIGN.

    `RiskEngine.evaluate_*` writes `risk_decisions.csv`. If the verdict ever
    asks the sizer, this file gains rows for trades nobody proposed - into the
    audit trail `session_check` reports on and whose row count is a reviewed
    figure. A defect that corrupts the record is fix-immediately, so this must
    fail loudly if someone later "improves" the verdict by asking for a size.
    """
    import hashlib

    from qat.domain.risk_engine.engine import RiskEngine

    # TWO assertions, because the file hash alone is a rubber stamp: nothing in
    # the advisory path touches this directory today, so it would pass whether
    # or not the sizer were wired in against some OTHER data_dir. The SPY is
    # what has teeth - it fails on the CALL, wherever that call would write.
    called: list[str] = []
    for name in ("evaluate_entry", "evaluate_exit"):
        original = getattr(RiskEngine, name, None)
        if original is None:
            continue

        def _spy(*args, _name=name, _original=original, **kwargs):
            called.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(RiskEngine, name, _spy)

    ledger = tmp_path / "risk_decisions.csv"
    ledger.write_text("", encoding="utf-8")
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()

    build_verdict_for_test(advisory_runtime, "BHP.AX")

    assert called == [], (
        f"the advisory path called RiskEngine.{called[0] if called else ''} - "
        "every such call writes a row to the risk audit trail for a trade "
        "nobody proposed"
    )
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert before == after, "the advisory path wrote to the risk audit trail"


def test_the_headline_is_a_conditional_not_a_suggestion():
    """M73's framing says these recommendations reach no part of the trading
    system. A verdict is the opposite kind of statement, and "the rails would
    permit a buy" under "[BUY, confidence 80%]" reads as the application
    endorsing a trade - the exact inference M73 exists to prevent."""
    from qat.presentation.symbol_verdict import RuleCheck, StrategyRules, SymbolVerdict

    verdict = SymbolVerdict(
        symbol="BHP.AX",
        held=False,
        checks=(RuleCheck("session", True, "open"),),
        per_strategy=(StrategyRules("swing", (), ""),),
        headline="If an entry in BHP.AX were proposed now, no rail checked here would refuse it. "
        "Sizing is not checked.",
    )

    assert verdict.headline.startswith("If ")
    for word in ("you should", "recommend", "buy now"):
        assert word not in verdict.headline.lower()
