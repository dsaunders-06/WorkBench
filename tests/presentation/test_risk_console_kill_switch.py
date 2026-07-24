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
