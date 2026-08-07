"""The Advanced tab has to stay reachable (M57a).

M56 split this screen into Basic and Advanced and put the QTabWidget INSIDE
the scroll area. The Basic page is seven groups tall, so it must be scrolled to
be read - and scrolling carried the Basic/Advanced selector off the top with
everything else. Nothing was missing and nothing raised; the only route to the
risk limits and the churn rails simply left the screen, which is
indistinguishable from those settings not existing.

The file already had the rule, applied one widget over: "A save button that can
be scrolled away is a save button an operator can believe does not exist."
"""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QScrollArea, QTabWidget

from qat.config import Settings
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen


def _screen(qtbot) -> SettingsScreen:
    screen = SettingsScreen(Runtime.build_demo(settings=Settings(_env_file=None)))
    qtbot.addWidget(screen)
    return screen


def _has_ancestor_of_type(widget, kind) -> bool:
    node = widget.parent()
    while node is not None:
        if isinstance(node, kind):
            return True
        node = node.parent()
    return False


def test_the_tab_bar_cannot_be_scrolled_out_of_view(qtbot):
    """The defect itself. A selector inside the scrolled content disappears as
    soon as the operator reads past the first screenful."""
    screen = _screen(qtbot)

    assert not _has_ancestor_of_type(
        screen.section_tabs, QScrollArea
    ), "the Basic/Advanced selector is inside the scroll area, so it scrolls away"


def test_both_pages_still_scroll(qtbot):
    """The fix must not reintroduce the problem M36b solved: without a scroll
    area Qt compresses every group to fit rather than overflowing, which made
    the screen unreadable at eight groups."""
    screen = _screen(qtbot)

    for index in range(screen.section_tabs.count()):
        page = screen.section_tabs.widget(index)
        scrollers = page.findChildren(QScrollArea) + (
            [page] if isinstance(page, QScrollArea) else []
        )
        assert scrollers, f"page {screen.section_tabs.tabText(index)} cannot scroll"


def test_the_advanced_page_still_holds_the_groups_that_change_trades(qtbot):
    """The split is by consequence. If these two ever drift onto Basic the
    tab means nothing."""
    screen = _screen(qtbot)
    tabs: QTabWidget = screen.section_tabs

    advanced = next(tabs.widget(i) for i in range(tabs.count()) if tabs.tabText(i) == "Advanced")
    titles = {group.title() for group in advanced.findChildren(QGroupBox)}

    assert "Risk Limits" in titles
    assert any("Holding" in title for title in titles)


def test_save_is_still_outside_the_scrolled_content(qtbot):
    """M36b's rule, kept. This is the same property the tab bar was missing."""
    screen = _screen(qtbot)

    assert not _has_ancestor_of_type(screen.save_button, QScrollArea)
