"""Drives the main window with mock/default state (spec §K smoke test)."""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.main_window import MainWindow

_EXPECTED_TABS = [
    "Dashboard",
    "Strategy Workbench",
    "Regime Monitor",
    "Risk Console",
    "AI Advisor",
    "Order Blotter",
    "Screener",
    "Settings",
]


def test_main_window_renders_all_screens_in_paper_mode(qtbot):
    window = MainWindow(Settings(_env_file=None))
    qtbot.addWidget(window)

    tab_widget = next(
        child for child in window.centralWidget().children() if hasattr(child, "tabText")
    )
    labels = [tab_widget.tabText(i) for i in range(tab_widget.count())]

    assert labels == _EXPECTED_TABS


def test_main_window_shows_live_banner_when_live(qtbot):
    window = MainWindow(Settings(_env_file=None, trading_mode="live"))
    qtbot.addWidget(window)

    banner = next(child for child in window.centralWidget().children() if hasattr(child, "text"))
    assert "LIVE" in banner.text()
