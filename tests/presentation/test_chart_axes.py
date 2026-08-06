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


def test_the_dashboard_seeds_its_chart_from_a_curve_that_actually_has_history(qtbot, tmp_path):
    """M56a. The seed drew onto `self.equity_curve` before the constructor had
    created it, so a launch against recorded history died with AttributeError
    before the window opened - and the traceback never reached the log, so the
    session simply went quiet.

    The two tests above passed throughout, because `build_demo` points at an
    empty data directory: `_equity_history` came back `[]`, the `if` guarding
    the draw was never entered, and `len(times) == len(history)` compared two
    empty lists. Every assertion held while the app could not start.

    So this writes a real `equity_curve.csv` first. Reading back what the curve
    is actually plotting, rather than what the lists contain, is the point -
    seeding that populates the lists and never reaches the plot is the failure
    this is here to catch.
    """
    curve = tmp_path / "equity_curve.csv"
    curve.write_text(
        "ts,equity,cash\n"
        "2026-08-05T15:12:19+00:00,100415.94,69845.06\n"
        "2026-08-06T01:35:05+00:00,101307.36,44772.74\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    runtime = Runtime.build_demo(settings=settings)

    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    times, equities = screen.equity_curve.getData()
    assert list(equities) == [100415.94, 101307.36]
    # Epoch seconds off the recorded timestamps, not 0 and 1 - the gap between
    # these two samples is ten hours, and the axis has to show it as ten hours.
    assert times[1] - times[0] == (10 * 60 + 22) * 60 + 46


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
