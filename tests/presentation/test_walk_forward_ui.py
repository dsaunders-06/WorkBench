"""Walk-forward on the Workbench (spec M19).

The module has existed since M4; what is new is that it is reachable and that
its result is summarised in a sentence an operator can act on. The headline is
therefore what these tests are mostly about - the arithmetic is already covered
in tests/domain/backtester.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from qat.config import Settings
from qat.domain.backtester.results import (
    BacktestResult,
    WalkForwardResult,
    WalkForwardWindow,
)
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen, _walk_forward_headline


def _window(index: int, sharpe: float, trades: int = 8) -> WalkForwardWindow:
    """`trades` defaults to a healthy count so the existing tests below keep
    measuring what they were written to measure - Sharpe wording - rather than
    tripping the too-few-trades caveat added for a continuously-held strategy."""
    start = datetime(2026, 1, 1) + timedelta(days=60 * index)
    result = BacktestResult(
        equity_curve=pd.Series([100_000.0, 100_500.0]),
        trades=[object()] * trades,
        metrics={"sharpe": sharpe, "cagr": 0.05, "max_drawdown": -0.02},
        warnings=[],
    )
    return WalkForwardWindow(
        in_sample_start=start,
        in_sample_end=start + timedelta(days=30),
        out_sample_start=start + timedelta(days=31),
        out_sample_end=start + timedelta(days=59),
        out_sample_result=result,
    )


def _result(sharpes: list[float], trades_per_window: int = 8) -> WalkForwardResult:
    windows = [_window(i, s, trades_per_window) for i, s in enumerate(sharpes)]
    mean = sum(sharpes) / len(sharpes) if sharpes else 0.0
    std = float(pd.Series(sharpes).std()) if len(sharpes) > 1 else 0.0
    return WalkForwardResult(
        windows=windows,
        metric_stability={"sharpe_mean": mean, "sharpe_std": std, "num_windows": len(windows)},
    )


def test_the_headline_leads_with_how_many_windows_were_profitable():
    headline = _walk_forward_headline(_result([1.2, 0.9, 1.1, -0.2]))

    assert headline.startswith("3 of 4 out-of-sample windows profitable.")


def test_a_strategy_that_failed_half_the_time_is_called_unproven():
    headline = _walk_forward_headline(_result([2.0, -0.5, -0.4, -0.3]))

    assert "unproven" in headline


def test_one_exceptional_window_does_not_read_as_success():
    """The failure this panel exists to catch: a strong average carried
    entirely by a single period."""
    headline = _walk_forward_headline(_result([6.0, -0.4, -0.3, -0.5]))

    assert "unproven" in headline
    assert "1 of 4" in headline


def test_a_wide_spread_is_called_out_even_when_most_windows_are_profitable():
    headline = _walk_forward_headline(_result([4.0, 0.1, 0.2, 0.1]))

    assert "depends heavily on which period" in headline


def test_a_consistent_strategy_is_described_as_consistent():
    headline = _walk_forward_headline(_result([1.0, 1.1, 0.9, 1.05]))

    assert "Reasonably consistent" in headline


def test_too_few_windows_is_said_rather_than_scored():
    headline = _walk_forward_headline(_result([1.0, 1.2]))

    assert "too few to say anything about stability" in headline


def test_no_windows_at_all_explains_itself():
    headline = _walk_forward_headline(_result([]))

    assert "shorter than one in-sample" in headline


# --- the screen --------------------------------------------------------------


def _workbench(qtbot) -> WorkbenchScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = WorkbenchScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def test_the_workbench_exposes_walk_forward_controls(qtbot):
    """It was written at M4 and reachable from nowhere until M19."""
    screen = _workbench(qtbot)

    assert screen.wf_run_button is not None
    assert screen.wf_in_sample_input.value() > 0
    assert screen.wf_out_sample_input.value() > 0


async def test_running_it_populates_a_row_per_window(qtbot):
    screen = _workbench(qtbot)

    await screen._run_walk_forward()

    assert screen.wf_table.rowCount() >= 1
    assert "out-of-sample windows profitable" in screen.wf_headline.text()


async def test_windows_longer_than_the_history_are_reported_not_crashed(qtbot):
    screen = _workbench(qtbot)
    screen.wf_in_sample_input.setValue(2000)
    screen.wf_out_sample_input.setValue(2000)

    await screen._run_walk_forward()

    assert "Not enough history" in screen.wf_headline.text()
    assert screen.wf_table.rowCount() == 0


# --- The caveat the panel omitted (M69) ---------------------------------------
#
# UI_UX_APPROACH 4.5: "the walk-forward panel does not state its known
# limitation - that slicing manufactures an entry at each window boundary, so
# for a continuously-held strategy it measures 60-day chunks of a hold. A
# results panel that omits its own caveat invites over-reading."
#
# ROADMAP records it as measured, and more bluntly: "Swing barely trades.
# Exposure changes 7 times in 300 bars ... walk-forward manufactures exactly one
# entry per window at the slice boundary: 12 symbols, 1 full-run trade each,
# 3 walk-forward trades each. Neither tool says much about swing until it exits."
#
# The deploy gate is on this screen, so an operator reading a Sharpe spread
# computed from one trade per window is the over-reading that matters.


def test_one_trade_per_window_is_called_what_it_is():
    """The live case. Swing produces exactly this shape."""
    headline = _walk_forward_headline(_result([1.0, 1.1, 0.9, 1.05], trades_per_window=1))

    # The rate is the fact that matters: one entry per window is the boundary
    # the slicing manufactured, not a trade the strategy chose.
    assert "1.0 per window" in headline
    assert "4 trade(s) across 4 window(s)" in headline
    assert "slic" in headline.lower()


def test_the_caveat_states_the_measured_count_rather_than_a_warning():
    """A static disclaimer is scrolled past; a number computed from THIS run
    cannot be. The same reason the Regime Monitor shows the mass rather than
    saying 'the regime may permit this'."""
    headline = _walk_forward_headline(_result([1.0, 1.1, 0.9], trades_per_window=2))

    assert "6" in headline  # 2 trades x 3 windows, the total actually observed
    assert "3 window" in headline


def test_a_strategy_that_trades_enough_gets_no_caveat():
    """It must self-suppress, or it becomes boilerplate on every result and
    stops being read - which is how the panel got here."""
    headline = _walk_forward_headline(_result([1.0, 1.1, 0.9, 1.05], trades_per_window=8))

    assert "slic" not in headline.lower()


def test_the_caveat_does_not_replace_the_stability_verdict():
    """Both facts are true at once: the windows may be consistent AND built on
    too few trades to mean anything. Suppressing either would mislead."""
    headline = _walk_forward_headline(_result([1.0, 1.1, 0.9, 1.05], trades_per_window=1))

    assert "consistent" in headline.lower()
    assert "slic" in headline.lower()


def test_no_windows_still_says_so_and_claims_nothing_about_trades():
    headline = _walk_forward_headline(_result([]))

    assert "No complete windows" in headline
    assert "slic" not in headline.lower()


# --- The same defect in the cone beside it (M69) -------------------------------
#
# ROADMAP's sentence covers both tools: "the Monte Carlo cone resamples
# near-buy-and-holds, and walk-forward manufactures exactly one entry per window
# at the slice boundary". The cone is built by RESAMPLING the backtest's trade
# sequence, so a sequence of one trade is resampled into a cone that looks like
# a distribution and is one observation repeated.


def test_a_cone_built_from_one_trade_says_so():
    from qat.presentation.workbench import _monte_carlo_caption

    caption = _monte_carlo_caption(1)

    assert "1 trade" in caption
    assert "resampl" in caption.lower()


def test_the_cone_caption_names_the_count_it_was_built_from():
    from qat.presentation.workbench import _monte_carlo_caption

    assert "4 trade" in _monte_carlo_caption(4)


def test_a_cone_with_enough_trades_carries_no_caveat():
    """Self-suppressing, for the same reason as the walk-forward caveat: a
    warning printed on every result stops being read."""
    from qat.presentation.workbench import _monte_carlo_caption

    caption = _monte_carlo_caption(40)

    assert "40 trade" in caption
    assert "one observation repeated" not in caption


def test_no_trades_at_all_is_not_described_as_a_distribution():
    from qat.presentation.workbench import _monte_carlo_caption

    caption = _monte_carlo_caption(0)

    assert "no trades" in caption.lower()
