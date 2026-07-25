"""SettingsScreen (spec §K/M10): Save writes non-secret fields to .env and
the Anthropic key to the keyring - never the other way around. Everything
here is restart-required (see settings.py's module docstring), so these
tests only check what gets written, not any live reconfiguration."""

from __future__ import annotations

from qat.config import Settings
from qat.presentation import settings as settings_module
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen


def _build_screen(qtbot) -> SettingsScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = SettingsScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def test_fields_are_pre_filled_from_current_settings(qtbot):
    screen = _build_screen(qtbot)

    assert screen.market_combo.currentText() == "US"
    assert screen.category_combo.currentText() == "curated"
    assert screen.local_base_url_input.text() == "http://localhost:1234/v1"
    assert screen.anthropic_key_input.text() == ""  # write-only, never pre-filled


def test_sensitive_warning_only_shows_for_anthropic(qtbot):
    screen = _build_screen(qtbot)
    screen.show()
    qtbot.waitExposed(screen)

    assert not screen.sensitive_warning.isVisible()
    screen.sensitive_provider.setCurrentText("Anthropic")
    assert screen.sensitive_warning.isVisible()
    screen.sensitive_provider.setCurrentText("Local (LM Studio)")
    assert not screen.sensitive_warning.isVisible()


def test_save_writes_expected_non_secret_env_updates(qtbot, monkeypatch):
    screen = _build_screen(qtbot)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        settings_module.env_file, "update_env_file", lambda updates: captured.update(updates)
    )
    monkeypatch.setattr(settings_module.security, "set_secret", lambda name, value: None)

    screen.market_combo.setCurrentText("ASX")
    screen.max_symbols_input.setValue(7)
    screen._on_save_clicked()

    assert captured["QAT_MARKET"] == "ASX"
    assert captured["QAT_WATCHLIST_MAX_SYMBOLS"] == "7"
    assert "Restart" in screen.status_label.text()


def test_save_never_puts_the_anthropic_key_in_the_env_updates(qtbot, monkeypatch):
    screen = _build_screen(qtbot)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        settings_module.env_file, "update_env_file", lambda updates: captured.update(updates)
    )
    secret_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        settings_module.security,
        "set_secret",
        lambda name, value: secret_calls.append((name, value)),
    )

    screen.anthropic_key_input.setText("sk-super-secret")
    screen._on_save_clicked()

    assert secret_calls == [("ANTHROPIC_API_KEY", "sk-super-secret")]
    assert "sk-super-secret" not in captured.values()
    assert screen.anthropic_key_input.text() == ""  # cleared after save


def test_save_without_a_key_never_calls_set_secret(qtbot, monkeypatch):
    screen = _build_screen(qtbot)
    monkeypatch.setattr(settings_module.env_file, "update_env_file", lambda updates: None)
    secret_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        settings_module.security,
        "set_secret",
        lambda name, value: secret_calls.append((name, value)),
    )

    screen._on_save_clicked()  # anthropic_key_input left blank

    assert secret_calls == []
