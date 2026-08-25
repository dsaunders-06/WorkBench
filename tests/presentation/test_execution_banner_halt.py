"""The banner must follow the kill-switch, in both directions.

The main window's execution banner is the most prominent statement the app
makes about whether it is trading. It subscribed only to KillSwitchEvent, so
a halt from the Risk Console or the staleness detector left it reading
AUTO-TRADE ACTIVE, and a reset left it reading HALTED for the rest of the
session. Both are the banner lying about the thing it exists to report.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from qat.config import Settings
from qat.domain.strategies.swing import SwingStrategy
from qat.presentation.main_window import MainWindow
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _window(qtbot) -> MainWindow:
    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, execution_mode="auto", autonomous_strategies="swing")
    )
    # A strategy is deployed because these tests are about what the banner says
    # when something happens to an app that CAN trade. With an empty deployed
    # set the banner correctly reports that nothing can (M27b).
    runtime.strategy_engine.deploy(SwingStrategy())
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    return window


def test_banner_shows_the_halt_when_the_switch_trips_directly(qtbot):
    """No event, no bus, no loop - just the switch changing state."""
    window = _window(qtbot)
    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()

    window.runtime.kill_switch.check_reconciliation()

    assert "EXECUTION HALTED" in window.execution_banner.text()
    assert "Broker reconciliation mismatch" in window.execution_banner.text()


def test_banner_clears_when_the_switch_is_reset(qtbot):
    window = _window(qtbot)
    window.runtime.kill_switch.trigger_manual("operator")
    assert "EXECUTION HALTED" in window.execution_banner.text()

    window.runtime.kill_switch.reset("operator")

    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()


def test_risk_console_button_moves_the_main_banner(qtbot):
    """The end-to-end case the operator actually performs.

    Clicking halt on one screen has to change the banner on another, with no
    event loop running - which is why this travels by listener rather than by
    an awaited publish from a Qt slot.
    """
    window = _window(qtbot)
    console = RiskConsoleScreen(window.runtime)
    qtbot.addWidget(console)

    # Halting asks first (item 36); the reset click below deliberately
    # does NOT, which is the asymmetry this button is built around.
    console._confirm_trip = lambda: True  # type: ignore[assignment]
    qtbot.mouseClick(console.kill_switch_button, Qt.MouseButton.LeftButton)
    assert "EXECUTION HALTED" in window.execution_banner.text()
    assert "Manual trigger" in window.execution_banner.text()

    qtbot.mouseClick(console.kill_switch_button, Qt.MouseButton.LeftButton)
    assert "EXECUTION HALTED" not in window.execution_banner.text()
