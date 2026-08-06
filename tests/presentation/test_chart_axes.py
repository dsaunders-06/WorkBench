"""Every chart states what it is showing (M55).

Measured before this existed: ONE axis-label call in the whole presentation
layer. Every other chart rendered bare axes and left the reader to infer whether
the x-axis was dates, trading days or a sample count. On screens whose purpose
is deciding whether a strategy works, that is an invitation to read the wrong
quantity confidently.
"""

from __future__ import annotations

import pyqtgraph as pg

from qat.config import Settings
from qat.presentation import theme
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen


def _axis_text(plot: pg.PlotWidget, side: str) -> str:
    return plot.getPlotItem().getAxis(side).labelText


def test_label_axes_names_both_sides(qtbot):
    # qtbot, not for the widget itself but for the QApplication it guarantees -
    # constructing a PlotWidget without one takes the process down rather than
    # raising, which is a confusing way to learn it.
    plot = pg.PlotWidget()
    qtbot.addWidget(plot)
    theme.label_axes(plot, bottom="Trades simulated", left="Equity ($)")

    assert _axis_text(plot, "bottom") == "Trades simulated"
    assert _axis_text(plot, "left") == "Equity ($)"


def test_the_dashboard_equity_chart_plots_against_real_time(qtbot):
    """M56. It counted account polls, so an overnight close and a busy minute
    occupied the same width and a failed poll shortened the axis instead of
    leaving a gap. Equity at 14:03 is a fact an operator can act on; equity at
    "sample 412" is not."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    assert _axis_text(screen.equity_plot, "bottom") == "Time"
    assert "$" in _axis_text(screen.equity_plot, "left")
    # A date axis, not a numeric one - this is what makes the spacing reflect
    # real elapsed time and pick ticks appropriate to the visible span.
    assert isinstance(screen.equity_plot.getPlotItem().getAxis("bottom"), pg.DateAxisItem)


def test_the_dashboard_equity_chart_keeps_times_and_values_in_step(qtbot):
    """Two parallel lists trimmed independently would silently shear the curve
    against its own timestamps."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    assert len(screen._equity_times) == len(screen._equity_history)


def test_the_workbench_charts_name_their_units(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = WorkbenchScreen(runtime)
    qtbot.addWidget(screen)

    # Bar index, because .to_numpy() at the render site discards the timestamps.
    assert "bar" in _axis_text(screen.equity_plot, "bottom").lower()
    assert "$" in _axis_text(screen.equity_plot, "left")
    # One step per TRADE, which is why the cone widens with trade count rather
    # than with elapsed time.
    assert "trade" in _axis_text(screen.mc_plot, "bottom").lower()
    assert "$" in _axis_text(screen.mc_plot, "left")


def test_every_plot_widget_in_the_app_is_labelled(qtbot):
    """The guard that keeps this true. A chart added later with bare axes fails
    here rather than shipping unlabelled."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screens = [DashboardScreen(runtime), WorkbenchScreen(runtime)]
    for screen in screens:
        qtbot.addWidget(screen)

    unlabelled: list[str] = []
    for screen in screens:
        for plot in screen.findChildren(pg.PlotWidget):
            for side in ("bottom", "left"):
                if not _axis_text(plot, side).strip():
                    unlabelled.append(f"{type(screen).__name__}.{plot.objectName() or plot} {side}")

    assert not unlabelled, f"charts with a bare axis: {unlabelled}"
