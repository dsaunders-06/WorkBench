"""Restore Defaults, unsaved-change tracking, and the expertise level (M55).

Three requests from the operator, all of them about the same thing: a settings
screen where every field is restart-required makes a mistake invisible twice
over - it did not take effect, and nothing says so.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

from qat.config import Settings
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen, _widget_value
from qat.presentation.ui_level import UiLevel


def _screen(qtbot, **settings_kwargs) -> SettingsScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, **settings_kwargs))
    screen = SettingsScreen(runtime)
    qtbot.addWidget(screen)
    return screen


# --- change tracking --------------------------------------------------------


def test_a_freshly_loaded_screen_has_no_unsaved_changes(qtbot):
    """Compared against the values as LOADED, not against defaults - otherwise
    every screen opened on a customised config would claim to be dirty."""
    assert _screen(qtbot).unsaved_changes() == []


def test_a_customised_config_still_starts_clean(qtbot):
    screen = _screen(qtbot, max_concurrent_positions=17, kelly_fraction=0.25)
    assert screen.unsaved_changes() == []


def test_changing_a_field_is_reported_by_name(qtbot):
    screen = _screen(qtbot)
    screen.max_positions_input.setValue(screen.max_positions_input.value() + 3)

    assert "Max concurrent positions" in screen.unsaved_changes()


def test_retyping_the_same_value_is_not_a_change(qtbot):
    screen = _screen(qtbot)
    screen.max_positions_input.setValue(screen.max_positions_input.value())
    screen.curated_us_input.setText(screen.curated_us_input.text())

    assert screen.unsaved_changes() == []


def test_fields_above_the_boundary_are_not_watched(qtbot):
    """The operator drew the line at Market & Watchlist. Above it is provider
    and interface choice; below it is what the account actually does."""
    screen = _screen(qtbot)
    screen.local_model_input.setText("something-else")

    assert screen.unsaved_changes() == []


def test_an_entered_api_key_is_reported_but_never_echoed(qtbot):
    """The Alpaca key and secret sit BELOW the boundary, in Broker & Cash - an
    earlier draft of the plan wrongly assumed they were above it. They are
    write-only password fields, so the prompt says that something was entered
    and never what."""
    screen = _screen(qtbot)
    screen.alpaca_key_input.setText("PKTESTSECRETVALUE")

    changed = screen.unsaved_changes()

    assert "Alpaca API key (entered)" in changed
    assert not any("PKTESTSECRETVALUE" in entry for entry in changed)


def test_saving_clears_the_pending_changes(qtbot, monkeypatch):
    screen = _screen(qtbot)
    screen.max_positions_input.setValue(screen.max_positions_input.value() + 1)
    assert screen.unsaved_changes()

    screen.mark_saved()

    assert screen.unsaved_changes() == []


# --- restore defaults -------------------------------------------------------


def test_restore_defaults_puts_the_tuning_fields_back(qtbot, monkeypatch):
    """There was no way back. An operator who moved a Kelly bound to see what
    it did could only return by knowing the original, and the originals are
    visible only in config.py."""
    monkeypatch.setattr(
        "qat.presentation.settings.QMessageBox.question",
        lambda *a, **k: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes,
    )
    screen = _screen(qtbot, max_concurrent_positions=17, kelly_fraction=0.25)
    assert screen.max_positions_input.value() == 17

    screen._on_restore_defaults_clicked()

    defaults = Settings(_env_file=None)
    assert screen.max_positions_input.value() == defaults.max_concurrent_positions
    assert screen.kelly_fraction_input.value() == defaults.kelly_fraction


def test_restore_defaults_leaves_configuration_alone(qtbot, monkeypatch):
    """Broker, watchlist, data source and execution mode are what the operator
    configured, not what they tuned. Wiping them would be a far bigger surprise
    than the button promises."""
    monkeypatch.setattr(
        "qat.presentation.settings.QMessageBox.question",
        lambda *a, **k: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes,
    )
    screen = _screen(qtbot, max_concurrent_positions=17, watchlist_curated_us="AAA,BBB")
    before = screen.curated_us_input.text()
    broker_before = screen.broker_combo.currentText()

    screen._on_restore_defaults_clicked()

    assert screen.curated_us_input.text() == before
    assert screen.broker_combo.currentText() == broker_before


def test_restore_defaults_can_be_cancelled(qtbot, monkeypatch):
    monkeypatch.setattr(
        "qat.presentation.settings.QMessageBox.question",
        lambda *a, **k: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Cancel,
    )
    screen = _screen(qtbot, max_concurrent_positions=17)

    screen._on_restore_defaults_clicked()

    assert screen.max_positions_input.value() == 17


def test_restore_defaults_writes_nothing_until_save(qtbot, monkeypatch):
    """It restores VALUES, not the file, so a restore can itself be abandoned
    by closing without saving."""
    written: list[object] = []
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda *a, **k: written.append(a),
    )
    monkeypatch.setattr(
        "qat.presentation.settings.QMessageBox.question",
        lambda *a, **k: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes,
    )
    screen = _screen(qtbot, max_concurrent_positions=17)

    screen._on_restore_defaults_clicked()

    assert written == []


def test_restoring_an_untouched_screen_says_so(qtbot):
    screen = _screen(qtbot)

    screen._on_restore_defaults_clicked()

    assert "already at its default" in screen.status_label.text()


# --- every tracked field is actually readable -------------------------------


def test_every_tracked_field_reads_back(qtbot):
    """`_widget_value` returns None for a widget type it does not handle, so a
    field added later without support would silently never register a change.
    This is the test that catches it."""
    screen = _screen(qtbot)

    for label, widget, _default in screen._tracked:
        assert isinstance(
            widget, (QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit)
        ), f"{label} is an unhandled widget type"
        assert _widget_value(widget) is not None, f"{label} reads back as None"


# --- expertise level --------------------------------------------------------


def test_the_level_selector_reflects_the_configured_level(qtbot):
    """ui_level existed since M45 with no way to read it and no way to set it -
    one reference in the whole source tree, in config.py."""
    screen = _screen(qtbot, ui_level="guided")

    assert screen._selected_ui_level() is UiLevel.GUIDED
    assert "hidden" in screen.ui_level_description.text()


def test_choosing_a_level_updates_its_description(qtbot):
    screen = _screen(qtbot, ui_level="guided")

    screen.ui_level_combo.setCurrentText(UiLevel.PROFESSIONAL.label)

    assert screen._selected_ui_level() is UiLevel.PROFESSIONAL
    assert screen.ui_level_description.text() == UiLevel.PROFESSIONAL.describes_itself


def test_the_level_is_written_on_save(qtbot, monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda updates, path=None: captured.update(updates),
    )
    monkeypatch.setattr("qat.presentation.settings.security.set_secret", lambda *a, **k: None)
    screen = _screen(qtbot)
    screen.ui_level_combo.setCurrentText(UiLevel.PROFESSIONAL.label)

    screen.save_now()

    assert captured["QAT_UI_LEVEL"] == "professional"
