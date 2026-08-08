"""Asking for the detail level once, not on every launch (M58a).

The trap this avoids: `ui_level` defaults to "standard", so testing the VALUE
cannot distinguish an operator who chose Standard from one who has never been
asked - and a prompt built that way re-asks the person who already answered,
every single launch.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from qat import env_file
from qat.presentation.first_run import (
    UI_LEVEL_KEY,
    DetailLevelDialog,
    level_has_been_chosen,
)
from qat.presentation.ui_level import UiLevel


def test_a_fresh_install_has_never_chosen(tmp_path):
    assert level_has_been_chosen(tmp_path / ".env") is False


def test_an_env_without_the_key_has_never_chosen(tmp_path):
    env = tmp_path / ".env"
    env.write_text("QAT_BROKER=alpaca\nQAT_MARKET=US\n", encoding="utf-8")

    assert level_has_been_chosen(env) is False


def test_choosing_the_default_still_counts_as_choosing(tmp_path):
    """The whole point. Standard is the default, so writing it is the only
    thing that separates "chose it" from "never asked"."""
    env = tmp_path / ".env"
    env_file.update_env_file({UI_LEVEL_KEY: "standard"}, path=env)

    assert level_has_been_chosen(env) is True


def test_a_commented_out_key_does_not_count(tmp_path):
    """Otherwise a documented example in the file answers the question on the
    operator's behalf."""
    env = tmp_path / ".env"
    env.write_text(f"# {UI_LEVEL_KEY}=professional\n", encoding="utf-8")

    assert level_has_been_chosen(env) is False


def test_an_unreadable_env_reads_as_never_chosen(tmp_path):
    """Asking once more than necessary is the cheap error; silently skipping
    the question is the expensive one."""
    assert level_has_been_chosen(tmp_path / "no" / "such" / ".env") is False


def test_the_dialog_offers_all_three_levels_and_defaults_to_standard(qtbot):
    dialog = DetailLevelDialog()
    qtbot.addWidget(dialog)

    assert dialog.selected_level() is UiLevel.STANDARD


def test_the_dialog_returns_what_was_selected(qtbot):
    dialog = DetailLevelDialog(current=UiLevel.PROFESSIONAL)
    qtbot.addWidget(dialog)

    assert dialog.selected_level() is UiLevel.PROFESSIONAL


def test_the_dialog_says_it_changes_nothing_that_is_enforced(qtbot):
    """A first-run dialog that looked like it was about risk would be worse
    than no dialog at all."""
    dialog = DetailLevelDialog()
    qtbot.addWidget(dialog)

    text = " ".join(label.text() for label in dialog.findChildren(QLabel))

    assert "sign-off gate" in text
    assert "risk limit" in text
    assert "identically at all three levels" in text
