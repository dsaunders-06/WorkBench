"""The Workbench answers to the expertise level, and says what it found (M74).

Two things §4.5 asks for that were never built.

**The level model.** The Workbench consumed no level at all - it was absent from
the list of `UiLevel` consumers entirely - so every operator saw the
walk-forward panel and the deploy control, including the one the brief says
should not see the screen at all.

Guided is "not shown. Backtesting a strategy is not a beginner task", and an
EMPTIED screen is not that: M45's rule is that an absent control is one level
away *and the level selector says so*. The Risk Console met the identical
instruction at M67 by keeping its tab and hiding its contents, so the tab stays
and a notice takes the place of the tools.

**The plain-language summary**, listed in Standard's column and never written.
What Standard got was `result.metrics` as KPI tiles in ALPHABETICAL order -
alpha, beta, cagr, calmar, information_ratio - with nothing to say which of them
decides anything.

The summary leads with trade count for the reason M69 gave the cone and the
windows their caveats: ROADMAP measured swing changing exposure 7 times in 300
bars, and a Sharpe computed over one trade is a property of that trade. The
caveat existed on both tools DERIVED from the backtest and not on the backtest
itself.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.results import BacktestResult
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen, _backtest_headline


def _screen(qtbot, level: str = "standard") -> WorkbenchScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, ui_level=level))
    screen = WorkbenchScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _result(*, trades: int, **metrics: float) -> BacktestResult:
    panel = {"sharpe": 1.2, "cagr": 0.12, "max_drawdown": -0.08}
    panel.update(metrics)
    return BacktestResult(
        equity_curve=pd.Series([100.0, 101.0, 102.0]),
        trades=[object()] * trades,  # type: ignore[list-item]
        metrics=panel,
        warnings=[],
    )


# --- three levels, three outcomes ---------------------------------------------


def test_guided_gets_the_notice_and_none_of_the_tools(qtbot):
    screen = _screen(qtbot, "guided")

    assert screen.guided_notice.isVisibleTo(screen)
    assert not screen.controls_widget.isVisibleTo(screen)
    assert not screen.equity_plot.isVisibleTo(screen)
    assert not screen.walk_forward_group.isVisibleTo(screen)


def test_the_guided_notice_says_where_the_screen_went(qtbot):
    """M45: a control that is absent is one level away, AND THE LEVEL SELECTOR
    SAYS SO. A blank tab fails the second half."""
    # Bound, not chained: a screen left as a temporary is collected and Qt
    # deletes the C++ label out from under the assertion.
    screen = _screen(qtbot, "guided")
    text = screen.guided_notice.text()

    assert "Standard" in text
    assert "Settings" in text


def test_standard_gets_the_backtest_but_not_walk_forward_or_deploy(qtbot):
    screen = _screen(qtbot, "standard")

    assert not screen.guided_notice.isVisibleTo(screen)
    assert screen.controls_widget.isVisibleTo(screen)
    assert screen.equity_plot.isVisibleTo(screen)
    assert screen.headline_label.isVisibleTo(screen)
    assert not screen.walk_forward_group.isVisibleTo(screen)
    assert not screen.deploy_button.isVisibleTo(screen)


def test_professional_gets_everything(qtbot):
    screen = _screen(qtbot, "professional")

    assert not screen.guided_notice.isVisibleTo(screen)
    assert screen.controls_widget.isVisibleTo(screen)
    assert screen.walk_forward_group.isVisibleTo(screen)
    assert screen.deploy_button.isVisibleTo(screen)


def test_the_three_levels_do_not_render_identically(qtbot):
    """M58a in miniature. The Balances design reached review rendering Guided
    and Standard the same, and every test of it passed."""
    shapes = set()
    for level in ("guided", "standard", "professional"):
        screen = _screen(qtbot, level)
        shapes.add(
            (
                screen.guided_notice.isVisibleTo(screen),
                screen.controls_widget.isVisibleTo(screen),
                screen.walk_forward_group.isVisibleTo(screen),
                screen.deploy_button.isVisibleTo(screen),
            )
        )

    assert len(shapes) == 3


def test_the_deploy_control_is_professional_only(qtbot):
    """The one control on this screen that changes what the account does."""
    for level in ("guided", "standard"):
        screen = _screen(qtbot, level)
        assert not screen.deploy_button.isVisibleTo(screen), level


def test_the_deploy_gate_logic_is_untouched(qtbot):
    """§4.5: do not touch the deploy gate. Hiding the control by level is a
    different thing from the enabled-state that says "already live" - that is
    state, not level, and it must still start disabled."""
    screen = _screen(qtbot, "professional")

    assert screen.deploy_button.isEnabled() is False


# --- the plain-language summary -----------------------------------------------


def test_the_summary_leads_with_the_trade_count():
    """The caveat M69 gave the cone and the windows, on the result they are
    both computed from."""
    assert _backtest_headline(_result(trades=3)).startswith("3 trade(s)")


def test_a_thin_backtest_says_it_concludes_nothing():
    headline = _backtest_headline(_result(trades=2))

    assert "too few to conclude anything" in headline


def test_a_well_traded_backtest_drops_the_caveat():
    """It self-suppresses when the strategy trades enough, which is what stops
    it becoming the boilerplate M69 replaced."""
    assert "too few" not in _backtest_headline(_result(trades=40))


def test_no_trades_is_reported_as_no_trades_rather_than_as_a_result():
    """An equity curve that never moved produces a full set of metrics, every
    one of them describing nothing."""
    headline = _backtest_headline(_result(trades=0))

    assert "No trades were taken" in headline
    assert "none of them describes the strategy" in headline


def test_the_summary_states_the_result_against_the_benchmark():
    """A 12% CAGR is a triumph or a failure depending entirely on what the
    index did over the same bars, and the tiles report only one of the two."""
    headline = _backtest_headline(_result(trades=40, alpha=0.03))

    assert "added" in headline and "3.0%" in headline


def test_giving_up_ground_is_not_worded_as_adding_it():
    headline = _backtest_headline(_result(trades=40, alpha=-0.03))

    assert "gave up" in headline


def test_a_figure_that_rounds_to_zero_is_called_flat_rather_than_printed():
    """Rendering it found "Grew -0.0% a year", which reads as a broken template
    rather than as a small number."""
    headline = _backtest_headline(_result(trades=40, cagr=-0.00001, max_drawdown=-0.00001))

    assert "-0.0%" not in headline
    assert "was flat" in headline
    assert "no material drawdown" in headline


def test_an_alpha_indistinguishable_from_none_is_not_claimed_either_way():
    """ "gave up 0.0% a year" asserts a direction the figure does not support."""
    headline = _backtest_headline(_result(trades=40, alpha=-0.00001))

    assert "gave up" not in headline
    assert "added" not in headline


def test_a_strategy_that_lost_money_per_unit_of_risk_is_said_to_have_failed():
    headline = _backtest_headline(_result(trades=40, sharpe=-0.4))

    assert "did not work here" in headline


def test_a_severe_drawdown_is_named_as_the_thing_to_weigh():
    headline = _backtest_headline(_result(trades=40, max_drawdown=-0.35))

    assert "35%" in headline
    assert "what holding it would have felt like" in headline


@pytest.mark.asyncio
async def test_running_a_backtest_fills_the_summary(qtbot):
    """The seam. A headline function nothing calls is the M45 pattern."""
    screen = _screen(qtbot, "standard")

    await screen._run_backtest()

    assert screen.headline_label.text() != ""


# --- the design system --------------------------------------------------------


def test_the_status_label_uses_the_design_system(qtbot):
    """It held a raw #d9534f - one of the sites theme.py's own migration note
    claims to have consolidated into DANGER, and did not reach."""
    screen = _screen(qtbot, "standard")

    assert screen.status_label.styleSheet() == theme.text(theme.DANGER)
