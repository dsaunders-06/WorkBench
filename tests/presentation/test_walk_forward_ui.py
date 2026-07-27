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


def _window(index: int, sharpe: float) -> WalkForwardWindow:
    start = datetime(2026, 1, 1) + timedelta(days=60 * index)
    result = BacktestResult(
        equity_curve=pd.Series([100_000.0, 100_500.0]),
        trades=[],
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


def _result(sharpes: list[float]) -> WalkForwardResult:
    windows = [_window(i, s) for i, s in enumerate(sharpes)]
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
