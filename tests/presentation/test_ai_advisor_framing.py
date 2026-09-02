"""The AI Advisor says which half of the application is speaking (M73).

§4.9 calls this "the simplest screen, and fine", and says of it: *"Do not touch:
the advisory-only framing. The user must never be led to think the AI can act."*

**That framing did not exist.** It lived in this module's docstring - "an
analyst, never a trader" - which the operator never sees, while the screen
rendered "[BUY, confidence=80%]" in bold with nothing to say what happened next.
The brief protected something that was never built. It matters here more than it
would elsewhere, because this application also trades UNATTENDED: a
recommendation displayed inside it invites exactly the inference that the two
are connected, and they are not.

**And it fed the model a zero it never measured.** `portfolio_check.get("var_95",
0.0)` turned "no risk check has run" into "VaR is zero" - in the same prompt
whose fundamentals block promises, in as many words, that "fields the vendor
could not answer are omitted rather than zeroed". The Screener's em dash and
`available_figures()` state the same rule twice more. The one consumer that is a
language model, and cannot ask which it was, got the version the rest of the
codebase refuses to produce.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.account_poller import AccountSnapshot
from qat.data.broker.adapter import AccountBalances
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.risk_engine.audit import RiskDecision
from qat.presentation import advisory_account, theme
from qat.presentation.ai_advisor import AiAdvisorScreen, _answer_caveats
from qat.presentation.runtime import Runtime


def _screen(qtbot, level: str = "standard") -> AiAdvisorScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, ui_level=level))
    screen = AiAdvisorScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _record_check(screen: AiAdvisorScreen, portfolio_check: dict[str, float]) -> None:
    """The last risk decision, as the engine writes it - the advisor reads
    `portfolio_check` off the most recent entry."""
    screen.runtime.risk_engine.audit_log.record(
        RiskDecision(
            symbol="AMD",
            approved=True,
            final_shares=0.0,
            reason="portfolio check",
            inputs={"portfolio_check": portfolio_check},
        )
    )


# --- the framing --------------------------------------------------------------


def test_the_screen_states_that_it_cannot_act(qtbot):
    screen = _screen(qtbot)

    text = screen.framing_label.text()

    assert "not a trader" in text
    assert "never reads these answers" in text.replace("\n", " ")


def test_the_framing_says_it_is_not_advice(qtbot):
    """The app is a paper trial today and the screen names real securities."""
    # Bound, not chained: a screen left as a temporary is collected and Qt
    # deletes the C++ label out from under the assertion.
    screen = _screen(qtbot)

    assert "not financial advice" in screen.framing_label.text().lower()


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_the_framing_is_identical_at_every_level(qtbot, level):
    """M45: safety is not a level, and nothing there may be used to quieten a
    rail. A Professional operator is not less entitled to know which half of
    the application is speaking."""
    screen = _screen(qtbot, level)

    assert screen.framing_label.isVisibleTo(screen)
    assert "not a trader" in screen.framing_label.text()


def test_the_framing_is_styled_from_the_design_system(qtbot):
    """ACCENT, which theme documents as structural emphasis and deliberately
    not a status colour - this is what the screen IS, not a fault in it. §3a:
    styling comes from the design system, never inline."""
    screen = _screen(qtbot)

    assert screen.framing_label.styleSheet() == theme.text(theme.ACCENT, size=theme.BODY)


def test_the_framing_is_the_same_words_at_every_level(qtbot):
    screens = [_screen(qtbot, level) for level in ("guided", "professional")]
    wordings = {screen.framing_label.text() for screen in screens}

    assert len(wordings) == 1


# --- absent is not zero -------------------------------------------------------


def test_a_missing_metric_is_omitted_rather_than_zeroed(qtbot):
    """The defect. A metric the last check did not record must not arrive as a
    measurement of zero."""
    screen = _screen(qtbot)
    _record_check(screen, {"var_95": 0.031})

    metrics = advisory_account.risk_metrics(screen.runtime)

    assert metrics["at_last_decision"] == pytest.approx({"var_95": 0.031})
    assert "es_975" not in metrics["at_last_decision"]


def test_metrics_that_are_present_are_carried(qtbot):
    screen = _screen(qtbot)
    _record_check(screen, {"var_95": 0.031, "es_975": 0.047})

    assert advisory_account.risk_metrics(screen.runtime)["at_last_decision"] == pytest.approx(
        {"var_95": 0.031, "es_975": 0.047}
    )


def test_no_risk_check_at_all_yields_nothing(qtbot):
    assert advisory_account.risk_metrics(_screen(qtbot).runtime) == {}


def test_the_prompt_says_unknown_rather_than_showing_an_empty_container():
    """A model handed "Risk metrics: {}" has to infer what the braces mean.
    Saying it outright costs one line."""
    context = AdvisoryContext(
        symbol="AMD",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
    )

    text = context.to_prompt_text()

    assert "UNKNOWN, not as zero risk" in text
    assert "Risk metrics: {}" not in text


def test_real_metrics_still_render_as_figures():
    context = AdvisoryContext(
        symbol="AMD",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={"var_95": 0.031},
        candidate_signal={},
    )

    assert "0.031" in context.to_prompt_text()


# --- what the answer was reasoning from ---------------------------------------


def test_an_answer_built_on_synthetic_fundamentals_says_so():
    """`to_prompt_text` already warns the MODEL. The operator was told
    nothing, which left the two working from different information about the
    same answer."""
    caveats = _answer_caveats({"is_synthetic": True, "roe": 0.2}, {"var_95": 0.03})

    assert "SYNTHETIC" in caveats


def test_an_answer_with_no_risk_figures_says_so():
    caveats = _answer_caveats({"is_synthetic": False}, {})

    assert "no portfolio risk check" in caveats


def test_a_fully_informed_answer_carries_no_caveat():
    """The M69 rule. A caveat printed under every reply is scrolled past, so it
    self-suppresses when there is nothing to say."""
    assert _answer_caveats({"is_synthetic": False, "roe": 0.2}, {"var_95": 0.03}) == ""


def test_both_caveats_appear_together_when_both_apply():
    caveats = _answer_caveats({"is_synthetic": True}, {})

    assert "SYNTHETIC" in caveats
    assert "no portfolio risk check" in caveats


# --- an unknown day P&L must never be fabricated as zero -----------------------


def test_an_unknown_day_pnl_produces_no_verdict_rather_than_a_permissive_one(qtbot):
    """M73's scar again, one hop over. `AutonomyGate.evaluate` pauses buys only
    when `day_pnl_pct` is at or below a threshold that is always negative
    (`autonomous_pause_buys_below_day_pnl_pct`, default -0.04, constrained
    `lt=0`), so a substituted `0.0` could NEVER trip that pause: an unreported
    -6% day would read as "no rail checked here would refuse it", a stated
    permission resting on a fabricated fact.

    `position_view.py`'s rule - "a value this module cannot support is `None`,
    never `0` or `0.0`" - already governs `equity` here; this pins that
    `day_pnl_pct` (and `cash`, the same category of fact) are held to it too.

    `AccountBalances.day_pnl_pct` is itself `None` whenever `last_equity` is
    unreported, which is the realistic shape of "the broker didn't say" -
    omitting it here reproduces exactly that.
    """
    screen = _screen(qtbot)
    balances = AccountBalances(equity=100_000.0, cash=50_000.0)  # no last_equity
    assert balances.day_pnl_pct is None
    # BOTH sources must be unknown for this to test what it claims (item 47).
    # The verdict now falls back to EquityMonitor.day_pnl_pct(), which works on
    # IBKR where `last_equity` never does; nulling only the broker would leave
    # a real figure available and assert the wrong thing.
    screen.runtime.equity_monitor.state = None  # type: ignore[union-attr]
    snapshot = AccountSnapshot(
        summary=None, balances=balances, positions=(), taken_at=datetime.now(UTC), error=None
    )

    verdict, view = advisory_account.build_symbol_verdict(screen.runtime, "AMD", [], snapshot)

    assert verdict is None
    assert view is None


def test_the_monitors_day_pnl_is_enough_to_produce_a_verdict(qtbot):
    """The other half of item 47, and the reason the verdict never rendered.

    `AccountBalances.day_pnl_pct` derives from `last_equity`, which IBKR never
    supplies, so on the live broker it is ALWAYS None - and the guard above
    suppressed the verdict every single time, across two live sessions.
    `EquityMonitor.day_pnl_pct()` is a real measured figure and is what
    `AutonomyGate` gates on. With it, the verdict renders.
    """
    screen = _screen(qtbot)
    balances = AccountBalances(equity=100_000.0, cash=50_000.0)  # no last_equity
    assert balances.day_pnl_pct is None, "fixture must reproduce the IBKR shape"

    # A REAL basis, not a patched method. `day_pnl_pct()` returns 0.0 rather
    # than None when it has no state, so patching the method alone would prove
    # nothing about whether a genuine figure reaches the verdict - and a
    # fabricated 0.0 is precisely what the guard above exists to refuse.
    from qat.domain.autonomy.equity_monitor import EquityState

    monitor = screen.runtime.equity_monitor
    monitor.state = EquityState(  # type: ignore[union-attr]
        day="2026-08-25", day_start_equity=101_250.0, high_water_mark=101_250.0
    )

    snapshot = AccountSnapshot(
        summary=None, balances=balances, positions=(), taken_at=datetime.now(UTC), error=None
    )

    verdict, _view = advisory_account.build_symbol_verdict(screen.runtime, "AMD", [], snapshot)

    assert verdict is not None, (
        "the verdict is still suppressed - the monitor's figure is not reaching "
        "it, which is item 47 exactly"
    )


def test_a_fully_known_account_still_produces_a_verdict(qtbot):
    """The guard above must not have made every account unverdictable - only
    one with a genuinely unknown figure."""
    screen = _screen(qtbot)
    balances = AccountBalances(equity=100_000.0, cash=50_000.0, last_equity=100_000.0)
    assert balances.day_pnl_pct == 0.0
    snapshot = AccountSnapshot(
        summary=None, balances=balances, positions=(), taken_at=datetime.now(UTC), error=None
    )

    verdict, _view = advisory_account.build_symbol_verdict(screen.runtime, "AMD", [], snapshot)

    assert verdict is not None
