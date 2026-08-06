"""Basic and Advanced sections, and the Exit button (M56).

Nine groups in one scrolling column is a wall. The split is by CONSEQUENCE, not
by difficulty: Advanced holds the two groups that change which trades happen and
how large they are.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox

from qat.config import Settings
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen


def _screen(qtbot, **settings_kwargs) -> SettingsScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, **settings_kwargs))
    screen = SettingsScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _group_titles(page) -> set[str]:
    return {box.title() for box in page.findChildren(QGroupBox)}


def test_there_are_exactly_two_sections(qtbot):
    screen = _screen(qtbot)

    assert screen.section_tabs.count() == 2
    assert screen.section_tabs.tabText(0) == "Basic"
    assert screen.section_tabs.tabText(1) == "Advanced"


def test_basic_opens_first(qtbot):
    """The page an operator lands on should be the one they need most often."""
    assert _screen(qtbot).section_tabs.currentIndex() == 0


def test_advanced_holds_only_what_changes_trading(qtbot):
    screen = _screen(qtbot)

    advanced = _group_titles(screen.section_tabs.widget(1))

    assert advanced == {"Risk Limits", "Holding, Churn && Protection"}


def test_basic_holds_everything_else(qtbot):
    screen = _screen(qtbot)

    basic = _group_titles(screen.section_tabs.widget(0))

    assert "Risk Limits" not in basic
    assert "Holding, Churn && Protection" not in basic
    for expected in ("This Build", "Interface", "AI Provider", "Market && Watchlist"):
        assert expected in basic, f"{expected} should be on Basic"


def test_every_tracked_field_still_reachable_after_the_split(qtbot):
    """Splitting the screen must not orphan a control. If a widget stopped
    having a parent it would still be tracked and never be editable."""
    screen = _screen(qtbot)

    for label, widget, _default in screen._tracked:
        assert widget.parent() is not None, f"{label} has no parent widget"


def test_exit_closes_through_the_same_guard_as_the_window(qtbot, monkeypatch):
    """The button most likely to be pressed with unsaved work on screen is
    exactly the one that must not skip the unsaved-changes prompt, so it closes
    the window rather than quitting the process."""
    screen = _screen(qtbot)
    closed: list[bool] = []
    monkeypatch.setattr(type(screen.window()), "close", lambda _self: closed.append(True))

    screen.exit_button.click()

    assert closed == [True]
