"""UI-layer safety test (spec §H/§18.2): the Risk Console's kill-switch
button must actually trip and reset the real KillSwitch instance, not just
change its own label - the console is the one place operators expect a
single click to halt trading everywhere.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from qat.config import Settings
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _build_screen(qtbot) -> tuple[RiskConsoleScreen, Runtime]:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


def test_kill_switch_button_trips_the_real_kill_switch(qtbot):
    screen, runtime = _build_screen(qtbot)
    assert not runtime.kill_switch.tripped

    # Halting now asks first (item 36), because this button is a toggle bound
    # to Qt's `clicked` - which fires on Space or Enter when focused - and it
    # is the first widget on the screen. The test answers yes; that the
    # confirmation EXISTS is covered by test_risk_console_force_check.py.
    screen._confirm_trip = lambda: True  # type: ignore[assignment]
    qtbot.mouseClick(screen.kill_switch_button, Qt.MouseButton.LeftButton)

    assert runtime.kill_switch.tripped
    assert "TRIPPED" in screen.kill_switch_button.text()


def test_kill_switch_button_resets_when_already_tripped(qtbot):
    screen, runtime = _build_screen(qtbot)
    runtime.kill_switch.trigger_manual("test-setup")
    screen._refresh_kill_switch_button()
    assert runtime.kill_switch.tripped

    screen._on_kill_switch_clicked()

    assert not runtime.kill_switch.tripped
    assert "inactive" in screen.kill_switch_button.text()


def test_timer_tick_catches_a_trip_from_reconciliation_not_the_button(qtbot):
    """Item 57. `_refresh_kill_switch_button` was called only from
    construction and from the click handler's own tail, so a switch tripped
    by any OTHER route - reconciliation, the equity rails, the startup
    restore - left the label reading its state from before that trip.

    Observed live 26 August: the banner read "Execution halted" while this
    button still read "inactive - click to halt trading", and clicking it
    would have RESET the switch and resumed order flow, because the click
    handler reads `runtime.kill_switch.tripped` - the true state - not the
    label. The operator's caution, not the label, was the only thing that
    stayed the halt.

    `check_reconciliation()` is the route reconciliation itself uses to
    trip the switch - this test goes through it, never through the button
    or its handler, so it proves the label is now DERIVED rather than
    remembered.
    """
    screen, runtime = _build_screen(qtbot)
    assert "inactive" in screen.kill_switch_button.text()

    runtime.kill_switch.check_reconciliation()

    screen._on_timer_tick()

    assert "TRIPPED" in screen.kill_switch_button.text(), (
        f"the button still reads {screen.kill_switch_button.text()!r} after a trip "
        "the button never saw - clicking it would reset the switch and resume "
        "order flow with no confirmation"
    )
