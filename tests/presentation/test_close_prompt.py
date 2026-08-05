"""Closing the window must not silently discard settings (M55).

Every field on the Settings screen is restart-required, which makes an unsaved
edit invisible twice over: it did not take effect, and nothing on screen says
so. An operator can change a risk limit, close the window, restart, and
reasonably believe the new limit is live.
"""

from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from qat.config import Settings
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime


def _window(qtbot) -> MainWindow:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    return window


def _answer(monkeypatch, button) -> list[str]:
    """Capture the prompt text so the test can assert what the operator is told,
    not merely that they were asked."""
    seen: list[str] = []

    def _question(_parent, _title, text, *args, **kwargs):
        seen.append(text)
        return button

    monkeypatch.setattr("qat.presentation.main_window.QMessageBox.question", _question)
    return seen


def test_closing_with_no_changes_asks_nothing(qtbot, monkeypatch):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Discard)
    window = _window(qtbot)

    window.closeEvent(QCloseEvent())

    assert asked == []


def test_closing_with_unsaved_changes_names_them(qtbot, monkeypatch):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Discard)
    window = _window(qtbot)
    settings_screen = window.settings_screen
    settings_screen.max_positions_input.setValue(settings_screen.max_positions_input.value() + 4)

    window.closeEvent(QCloseEvent())

    assert asked, "the operator must be asked"
    assert "Max concurrent positions" in asked[0]


def test_cancel_keeps_the_window_open(qtbot, monkeypatch):
    """Three answers, not two. Save/Discard alone forces a decision the operator
    may not be ready to make, and is how unsaved work gets thrown away by
    someone who only meant to stop the prompt."""
    _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    window = _window(qtbot)
    window.settings_screen.max_positions_input.setValue(19)

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()


def test_discard_closes_without_writing(qtbot, monkeypatch):
    _answer(monkeypatch, QMessageBox.StandardButton.Discard)
    written: list[object] = []
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda *a, **k: written.append(a),
    )
    window = _window(qtbot)
    window.settings_screen.max_positions_input.setValue(19)

    window.closeEvent(QCloseEvent())

    assert written == []


def test_save_writes_before_closing(qtbot, monkeypatch):
    _answer(monkeypatch, QMessageBox.StandardButton.Save)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda updates, path=None: captured.update(updates),
    )
    monkeypatch.setattr("qat.presentation.settings.security.set_secret", lambda *a, **k: None)
    window = _window(qtbot)
    window.settings_screen.max_positions_input.setValue(19)

    window.closeEvent(QCloseEvent())

    assert captured["QAT_MAX_CONCURRENT_POSITIONS"] == "19"


def test_an_entered_key_is_flagged_without_being_shown(qtbot, monkeypatch):
    """The Alpaca key sits below the operator's boundary, so losing a typed key
    silently would be the same failure as losing a risk limit - but the value
    itself is never ours to put in a dialog."""
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Discard)
    window = _window(qtbot)
    window.settings_screen.alpaca_key_input.setText("PKSUPERSECRET")

    window.closeEvent(QCloseEvent())

    assert asked and "Alpaca API key (entered)" in asked[0]
    assert "PKSUPERSECRET" not in asked[0]
