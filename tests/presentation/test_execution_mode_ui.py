"""The execution-mode UI (spec M13).

The safety checklist requires that autonomy defaults off, that enabling it
takes a separate confirmation rather than a single control change, and that
its current state is visible at all times. Those are UI properties, so they
get UI tests.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from qat.config import Settings
from qat.domain.events import KillSwitchEvent
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime
from qat.presentation.settings import (
    _DATA_SOURCE_LABELS,
    _EXECUTION_MODE_LABELS,
    SettingsScreen,
)


def _runtime(**overrides) -> Runtime:
    base = {"_env_file": None}
    base.update(overrides)
    return Runtime.build_demo(settings=Settings(**base))  # type: ignore[arg-type]


# --- Settings screen ----------------------------------------------------------


def test_the_mode_control_defaults_to_recommend(qtbot):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    assert screen.execution_mode_combo.currentText() == _EXECUTION_MODE_LABELS["recommend"]
    assert screen._selected_execution_mode() == "recommend"


def test_the_loud_warning_is_hidden_in_recommend_mode(qtbot):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    assert screen.autonomy_warning.isVisibleTo(screen) is False


def test_declining_the_confirmation_reverts_the_control(qtbot, monkeypatch):
    """Changing the combo box is not by itself enough to enable autonomy."""
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    monkeypatch.setattr(SettingsScreen, "_confirm_autonomy", lambda self: False)

    screen.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS["auto"])

    assert screen._selected_execution_mode() == "recommend"
    assert screen.autonomy_warning.isVisibleTo(screen) is False


def test_accepting_the_confirmation_enables_it_and_shows_the_warning(qtbot, monkeypatch):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    monkeypatch.setattr(SettingsScreen, "_confirm_autonomy", lambda self: True)

    screen.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS["auto"])

    assert screen._selected_execution_mode() == "auto"
    assert screen.autonomy_warning.isVisibleTo(screen) is True


def test_switching_back_to_recommend_needs_no_confirmation(qtbot, monkeypatch):
    """Turning a safety feature back on should never be the harder direction."""
    screen = SettingsScreen(_runtime(execution_mode="auto"))
    qtbot.addWidget(screen)

    def _refuse(self):
        raise AssertionError("disabling autonomy must not prompt")

    monkeypatch.setattr(SettingsScreen, "_confirm_autonomy", _refuse)
    screen.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS["recommend"])

    assert screen._selected_execution_mode() == "recommend"


def test_the_data_source_defaults_to_simulated_and_says_so_loudly(qtbot):
    """Auto-trading against a random walk is a loop that trades noise, so the
    simulated state must be visible rather than assumed."""
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    assert screen.data_source_combo.currentText().startswith("Simulated")
    assert screen.data_warning.isVisibleTo(screen) is True


def test_the_simulated_warning_clears_when_real_data_is_selected(qtbot):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    screen.data_source_combo.setCurrentText(_DATA_SOURCE_LABELS["yfinance"])
    assert screen.data_warning.isVisibleTo(screen) is False


def test_saving_writes_the_data_source(qtbot, monkeypatch):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    screen.data_source_combo.setCurrentText(_DATA_SOURCE_LABELS["yfinance"])

    written: dict[str, str] = {}
    monkeypatch.setattr("qat.presentation.settings.env_file.update_env_file", written.update)
    screen._on_save_clicked()

    assert written["QAT_MARKET_DATA_SOURCE"] == "yfinance"


def test_saving_writes_the_mode_and_the_promoted_strategies(qtbot, monkeypatch):
    screen = SettingsScreen(_runtime())
    qtbot.addWidget(screen)
    monkeypatch.setattr(SettingsScreen, "_confirm_autonomy", lambda self: True)
    screen.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS["auto"])
    # Checked in the picker that replaced the free-text field at M20, so a
    # name that matches no strategy can no longer be saved.
    for row in range(screen._strategy_model.rowCount()):
        item = screen._strategy_model.item(row)
        if item.text() in ("swing", "breakout"):
            item.setCheckState(Qt.CheckState.Checked)

    written: dict[str, str] = {}
    monkeypatch.setattr("qat.presentation.settings.env_file.update_env_file", written.update)
    screen._on_save_clicked()

    assert written["QAT_EXECUTION_MODE"] == "auto"
    assert set(written["QAT_AUTONOMOUS_STRATEGIES"].split(",")) == {"swing", "breakout"}


# --- Always-on banner ---------------------------------------------------------


def test_the_banner_reads_recommend_by_default(qtbot):
    window = MainWindow(_runtime())
    qtbot.addWidget(window)
    assert "RECOMMEND" in window.execution_banner.text()


def test_the_banner_reads_auto_and_names_the_promoted_strategies(qtbot):
    window = MainWindow(_runtime(execution_mode="auto", autonomous_strategies="swing"))
    qtbot.addWidget(window)
    text = window.execution_banner.text()
    assert "AUTO-TRADE ACTIVE" in text
    assert "swing" in text


async def test_the_banner_switches_to_halted_when_the_kill_switch_trips(qtbot):
    """Halted must be distinguishable from off - 'I turned it off' and 'it
    stopped itself' are different situations."""
    runtime = _runtime(execution_mode="auto", autonomous_strategies="swing")
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()

    await runtime.bus.publish(KillSwitchEvent(reason="daily loss limit", triggered_by="test"))

    text = window.execution_banner.text()
    assert "HALTED" in text
    assert "daily loss limit" in text


def test_a_live_account_does_not_show_auto_active_without_the_extra_flag(qtbot):
    window = MainWindow(_runtime(trading_mode="live", execution_mode="auto"))
    qtbot.addWidget(window)
    assert "AUTO-TRADE ACTIVE" not in window.execution_banner.text()
