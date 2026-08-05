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


def test_the_dashboard_equity_chart_says_it_plots_polls_not_time(qtbot):
    """It plots `_equity_history` as a bare list, so the x-axis is the number of
    account polls since launch - with gaps wherever a poll failed. Calling it
    "Time" would be wrong in exactly the way that matters after an outage."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    assert "poll" in _axis_text(screen.equity_plot, "bottom").lower()
    assert "$" in _axis_text(screen.equity_plot, "left")


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
