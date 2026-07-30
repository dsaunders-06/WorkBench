"""SettingsScreen (spec §K/M10): Save writes non-secret fields to .env and
the Anthropic key to the keyring - never the other way around. Everything
here is restart-required (see settings.py's module docstring), so these
tests only check what gets written, not any live reconfiguration."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

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


def test_alpaca_feed_row_hides_label_and_field_together(qtbot):
    """Hiding only the combo left a stranded 'Alpaca feed:' label beside empty
    space, implying a setting that had gone missing rather than one that does
    not apply to the selected source."""
    screen = _build_screen(qtbot)
    screen.show()
    qtbot.waitExposed(screen)
    label = screen._data_form.labelForField(screen.alpaca_feed_combo)

    assert not screen.alpaca_feed_combo.isVisible()
    assert not label.isVisible()

    screen.data_source_combo.setCurrentText("Real market data (Alpaca, US only)")
    assert screen.alpaca_feed_combo.isVisible()
    assert label.isVisible()

    screen.data_source_combo.setCurrentText("Real market data (Yahoo, free/delayed)")
    assert not screen.alpaca_feed_combo.isVisible()
    assert not label.isVisible()


def test_save_writes_expected_non_secret_env_updates(qtbot, monkeypatch):
    screen = _build_screen(qtbot)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        settings_module.env_file,
        "update_env_file",
        lambda updates, path=None: captured.update(updates),
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
        settings_module.env_file,
        "update_env_file",
        lambda updates, path=None: captured.update(updates),
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
    monkeypatch.setattr(
        settings_module.env_file, "update_env_file", lambda updates, path=None: None
    )
    secret_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        settings_module.security,
        "set_secret",
        lambda name, value: secret_calls.append((name, value)),
    )

    screen._on_save_clicked()  # anthropic_key_input left blank

    assert secret_calls == []


# --- Build provenance (M27b tooling) --------------------------------------


def test_the_screen_shows_which_build_is_running(qtbot):
    """ "Am I running the latest?" is the question asked before trusting
    anything else on this screen. The install sat on M26 while the repository
    was four milestones ahead, and nothing in the app could have said so."""
    from qat.version import build_info

    screen = _build_screen(qtbot)
    group = screen._build_group()
    labels = [child.text() for child in group.findChildren(QLabel)]
    info = build_info()

    assert info.milestone in labels
    assert info.commit in labels
    assert info.source in labels


def test_a_dirty_build_is_called_out(qtbot, monkeypatch):
    """A build made from uncommitted changes cannot be reproduced from the
    commit it names, and the operator should see that rather than trust it."""
    from qat.version import BuildInfo

    monkeypatch.setattr(
        settings_module,
        "build_info",
        lambda: BuildInfo(
            milestone="M27a", commit="db4a8e3-dirty", built_at="2026-07-30", source="packaged"
        ),
    )
    screen = _build_screen(qtbot)

    # Held in a local: an unparented QGroupBox is collected the moment the
    # expression ends, taking its children's C++ objects with it.
    group = screen._build_group()
    text = " ".join(child.text() for child in group.findChildren(QLabel))

    assert "uncommitted changes" in text
