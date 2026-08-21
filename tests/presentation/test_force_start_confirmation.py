"""M124: a second deliberate act between the click and the override.

M107 removed the ACCIDENTAL path - the button is `NoFocus`, so Space or Enter
cannot reach it. A deliberate click was still instant, and on 20 August a
force-start produced six signals against stale closing prices on a shut market.

**The defaulting is the requirement, not the dialog.** Escape, Enter and
closing the window must all mean no. A confirmation that defaults to yes is one
keystroke away from no confirmation at all - which is exactly what M107 took
away, so a careless dialog would reintroduce the defect through the control
added to prevent it. That is why the dialog's configuration is asserted
directly and not only its outcome.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox

from qat.config import Settings
from qat.presentation import session_panel
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime
from qat.presentation.session_panel import (
    FORCE_START_CONFIRM_ACCEPT,
    FORCE_START_CONFIRM_REJECT,
    build_force_start_dialog,
)


def _panel(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)
    return screen.session_panel


# --- the dialog's own configuration -------------------------------------------


def test_the_default_button_is_the_safe_one(qtbot) -> None:
    """Enter must not start a session."""
    box, accept = build_force_start_dialog()
    qtbot.addWidget(box)

    assert box.defaultButton() is not accept
    assert box.defaultButton().text() == FORCE_START_CONFIRM_REJECT


def test_escape_is_the_safe_one(qtbot) -> None:
    box, accept = build_force_start_dialog()
    qtbot.addWidget(box)

    assert box.escapeButton() is not accept
    assert box.escapeButton().text() == FORCE_START_CONFIRM_REJECT


def test_the_accept_button_says_what_it_does(qtbot) -> None:
    """ "OK" would not name the action. A control names what it DOES (M106)."""
    box, accept = build_force_start_dialog()
    qtbot.addWidget(box)

    assert accept.text() == FORCE_START_CONFIRM_ACCEPT
    assert box.icon() == QMessageBox.Icon.Warning


def test_the_dialog_states_what_the_override_actually_does(qtbot) -> None:
    box, _accept = build_force_start_dialog()
    qtbot.addWidget(box)

    said = (box.text() + box.informativeText()).lower()
    assert "closed market" in said
    assert "stale" in said
    assert "until the next close" in said


# --- the panel's behaviour ----------------------------------------------------


def test_declining_does_not_start_the_session(qtbot, caplog) -> None:
    panel = _panel(qtbot)
    started: list[str] = []
    panel.controller.force_start = lambda source: started.append(source)  # type: ignore[assignment]
    panel.confirm_force_start = lambda _parent: False

    with caplog.at_level(logging.INFO, logger="qat.presentation.session_panel"):
        panel._on_start_clicked()

    assert started == [], "a declined confirmation must not arm the override"
    assert any("DECLINED" in record.getMessage() for record in caplog.records)


def test_confirming_starts_the_session(qtbot, caplog, monkeypatch) -> None:
    """`ensure_future` is patched rather than run.

    The panel schedules the force-start onto the ambient event loop, which in
    the app is qasync's and under pytest is whatever the previous test left
    behind - this passed alone and failed in the full suite for that reason
    alone. Patching the scheduling call tests the behaviour that matters
    (confirmed -> force-start scheduled) without depending on loop state.
    """
    panel = _panel(qtbot)
    scheduled: list[object] = []

    def _capture(coro):
        coro.close()  # never awaited, and an un-closed coroutine warns
        scheduled.append(coro)

    monkeypatch.setattr(session_panel.asyncio, "ensure_future", _capture)

    asked: list[object] = []
    panel.confirm_force_start = lambda parent: asked.append(parent) or True

    with caplog.at_level(logging.INFO, logger="qat.presentation.session_panel"):
        panel._on_start_clicked()

    assert asked, "the operator must be asked before the override is armed"
    assert scheduled, "a confirmed force-start must actually be scheduled"
    assert any("CONFIRMED" in record.getMessage() for record in caplog.records)


def test_the_operator_is_asked_before_anything_is_armed(qtbot) -> None:
    """Ordering, not just presence: the confirmation has to happen BEFORE the
    controller is touched, or it is a notification rather than a gate."""
    panel = _panel(qtbot)
    events: list[str] = []
    panel.controller.force_start = lambda source: events.append("started")  # type: ignore[assignment]

    def _confirm(_parent):
        events.append("asked")
        return False

    panel.confirm_force_start = _confirm
    panel._on_start_clicked()

    assert events == ["asked"]
