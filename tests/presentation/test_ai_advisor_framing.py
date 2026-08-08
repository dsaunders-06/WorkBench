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

import pytest

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.risk_engine.audit import RiskDecision
from qat.presentation import theme
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
    assert "not financial advice" in _screen(qtbot).framing_label.text().lower()


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
    wordings = {_screen(qtbot, level).framing_label.text() for level in ("guided", "professional")}

    assert len(wordings) == 1


# --- absent is not zero -------------------------------------------------------


def test_a_missing_metric_is_omitted_rather_than_zeroed(qtbot):
    """The defect. A metric the last check did not record must not arrive as a
    measurement of zero."""
    screen = _screen(qtbot)
    _record_check(screen, {"var_95": 0.031})

    metrics = screen._risk_metrics()

    assert metrics == pytest.approx({"var_95": 0.031})
    assert "es_975" not in metrics


def test_metrics_that_are_present_are_carried(qtbot):
    screen = _screen(qtbot)
    _record_check(screen, {"var_95": 0.031, "es_975": 0.047})

    assert screen._risk_metrics() == pytest.approx({"var_95": 0.031, "es_975": 0.047})


def test_no_risk_check_at_all_yields_nothing(qtbot):
    assert _screen(qtbot)._risk_metrics() == {}


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
