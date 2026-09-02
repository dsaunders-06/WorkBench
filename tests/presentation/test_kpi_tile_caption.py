"""A caption that is always present is furniture.

Item 4 of the 2 September milestone scope is about exactly this: a screen region
that never changes is one an operator stops seeing, and the day it says something
alarming it reads as furniture too. So the second line is ABSENT when it has
nothing to say - not a dash, not an empty string.
"""

from __future__ import annotations

from qat.presentation.widgets import KpiTile


def test_a_tile_with_no_caption_hides_the_line_entirely(qtbot):
    """⚠️ Not a dash. Item 4 of the milestone scope is about a screen region
    that is always occupied becoming furniture an operator stops seeing."""
    tile = KpiTile("Portfolio VaR (95%)")
    qtbot.addWidget(tile)
    assert tile._caption.isVisibleTo(tile) is False

    tile.set_caption("at last decision: 2.00%")
    assert tile._caption.text() == "at last decision: 2.00%"
    assert tile._caption.isVisibleTo(tile) is True

    tile.set_caption(None)
    assert tile._caption.isVisibleTo(tile) is False


def test_empty_string_caption_also_hides_the_line(qtbot):
    """The empty string must hide the caption, not show a blank line.

    This is critical because both `None` and `""` are falsy — a mutation from
    `setVisible(bool(text))` to `setVisible(text is not None)` would break the
    `""` case while leaving the `None` case passing. This test pins that gap.
    """
    tile = KpiTile("Portfolio VaR (95%)")
    qtbot.addWidget(tile)

    tile.set_caption("something to see")
    assert tile._caption.isVisibleTo(tile) is True

    tile.set_caption("")
    assert tile._caption.isVisibleTo(tile) is False
