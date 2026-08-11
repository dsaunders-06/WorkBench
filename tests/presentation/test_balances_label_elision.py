"""A cell label must degrade legibly, never be hard-cut at a container edge (M87).

Found by screenshotting the deployed M86 build. "Day trades (5d)" rendered as
**"Da"** on the Dashboard, cut off at the right edge of the Balances card - and
still cut off with the window maximised, so not a small-window artefact.

Measured by scanning the screenshot's pixels: the five demoted cells' labels
started at x = 58, 810, 1568, 2330, 3071 in a 3086px-wide window. Five columns
spaced ~755px demand ~3775px, and the fifth got 15 visible pixels.

`_build_broker_group` puts five cells in one row where the primary grid wraps at
four, and the comment says why - five wrapped at four orphan the last onto a row
of its own. That reasoning is sound; it just traded a wrapped row for a clipped
one, and the clipped one is worse because a wrapped row is legible.

**The overflow itself is not reproducible here.** The operator's display runs at
125% scaling (3840 physical / 3072 logical, AppliedDPI 120); the offscreen test
platform runs at 96 DPI and ignores QT_SCALE_FACTOR, where the same row fits with
592px per cell. So these tests do not assert the overflow. They assert the
property that makes the overflow harmless at ANY dpi and ANY width: a label too
wide for its column elides with an ellipsis and keeps its full text reachable,
and the five columns divide the available width evenly rather than being sized by
whichever content demands most.
"""

from __future__ import annotations

from qat.presentation.balances_panel import BalancesPanel
from qat.presentation.ui_level import UiLevel


def _panel(qtbot, level: UiLevel = UiLevel.PROFESSIONAL) -> BalancesPanel:
    panel = BalancesPanel(1.0, level=level)
    qtbot.addWidget(panel)
    # Shown, because an unshown widget never runs its layout, and every
    # assertion here is about geometry the layout produces.
    panel.show()
    return panel


def _settle(panel: BalancesPanel, qtbot) -> None:
    layout = panel.layout()
    if layout is not None:
        layout.activate()
    qtbot.wait(10)


def test_a_label_that_fits_is_shown_in_full(qtbot):
    panel = _panel(qtbot)
    panel.resize(2000, 400)
    _settle(panel, qtbot)

    assert panel.day_trades.rendered_label() == "Day trades (5d)"


def test_a_label_too_narrow_for_its_column_elides(qtbot):
    """Not truncated mid-glyph: an ellipsis is the difference between a label
    the operator can see is abbreviated and one that reads as a different
    word."""
    panel = _panel(qtbot)
    panel.resize(2000, 400)
    _settle(panel, qtbot)
    panel.day_trades.setFixedWidth(60)
    _settle(panel, qtbot)

    rendered = panel.day_trades.rendered_label()

    assert rendered != "Day trades (5d)", "nothing elided - the test is vacuous"
    assert "…" in rendered, f"hard-cut rather than elided: {rendered!r}"
    assert rendered != "Da", "the exact rendering the screenshot caught"


def test_the_full_text_stays_reachable_when_elided(qtbot):
    """An elided label that loses its own text is a worse trade than the clip:
    the figure becomes unidentifiable rather than merely abbreviated."""
    panel = _panel(qtbot)
    panel.resize(2000, 400)
    _settle(panel, qtbot)
    panel.day_trades.setFixedWidth(60)
    _settle(panel, qtbot)

    assert "Day trades (5d)" in panel.day_trades.label_tooltip()
    # label_text is what tests and readers ask for, and it never elides.
    assert panel.day_trades.label_text == "Day trades (5d)"


def test_every_demoted_column_gets_an_equal_share(qtbot):
    """The row is sized by division, not by whichever cell demands most. Without
    this the five minimum widths sum past the card and the last one is pushed
    off the edge - which is exactly what the screenshot showed."""
    panel = _panel(qtbot)
    body = panel.broker_body
    assert body is not None
    grid = body.layout()
    assert grid is not None

    stretches = [grid.columnStretch(column) for column in range(5)]

    assert stretches == [1, 1, 1, 1, 1], f"columns are not evenly divided: {stretches}"


def test_the_last_demoted_cell_stays_inside_the_card(qtbot):
    """The invariant the defect broke, stated as geometry. Checked across widths
    because the failure only appeared at one of them."""
    panel = _panel(qtbot)
    for width in (900, 1214, 1920, 3072):
        panel.resize(width, 400)
        _settle(panel, qtbot)
        cell = panel.day_trades
        right_edge = cell.mapTo(panel, cell.rect().topRight()).x()

        assert right_edge <= panel.width(), (
            f"at {width}px the last demoted cell ends at {right_edge}, "
            f"past the panel's {panel.width()}"
        )


def test_the_primary_cells_elide_too(qtbot):
    """Same treatment, because "Spendable here" is by the panel's own docstring
    the most important figure on it, and it sits in the rightmost column."""
    panel = _panel(qtbot)
    panel.resize(2000, 400)
    _settle(panel, qtbot)
    panel.spendable.setFixedWidth(50)
    _settle(panel, qtbot)

    assert "…" in panel.spendable.rendered_label()
    assert panel.spendable.label_text == "Spendable here"
