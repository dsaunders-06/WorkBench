"""The expertise level, and the two rules that keep it honest (M45).

A trading interface has two audiences that want opposite things: someone new
needs fewer numbers and to be told what each means; someone institutional needs
density and finds explanation patronising. Building for the average serves
neither, so the level is a property of the operator and screens ask for it.

This is plumbing - it changes no screen on its own. What it must never become
is a way to quieten a rail.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.ui_level import UiLevel


def _settings(level: str) -> Settings:
    return Settings(_env_file=None, ui_level=level)  # type: ignore[arg-type]


def test_the_default_is_standard():
    """Not guided. The default should suit someone comfortable with trading and
    new to this system, which is who actually opens it."""
    assert UiLevel.from_settings(Settings(_env_file=None)) is UiLevel.STANDARD


def test_each_level_resolves_from_configuration():
    assert UiLevel.from_settings(_settings("guided")) is UiLevel.GUIDED
    assert UiLevel.from_settings(_settings("standard")) is UiLevel.STANDARD
    assert UiLevel.from_settings(_settings("professional")) is UiLevel.PROFESSIONAL


def test_levels_are_ordered_so_a_screen_can_ask_for_at_least_this_much():
    """An IntEnum rather than a set of strings, precisely so that
    `level >= STANDARD` reads as intended and cannot be got wrong by comparing
    spellings."""
    assert UiLevel.GUIDED < UiLevel.STANDARD < UiLevel.PROFESSIONAL


def test_explanations_are_on_below_professional():
    assert UiLevel.GUIDED.explains() is True
    assert UiLevel.STANDARD.explains() is True
    assert UiLevel.PROFESSIONAL.explains() is False


def test_advanced_controls_are_absent_only_at_guided():
    """Hidden, never disabled: a greyed-out control invites a fight with the
    interface, where an absent one is a level away."""
    assert UiLevel.GUIDED.shows_advanced() is False
    assert UiLevel.STANDARD.shows_advanced() is True
    assert UiLevel.PROFESSIONAL.shows_advanced() is True


def test_every_level_describes_itself_to_the_operator():
    """The selector has to say what changes, or it is a mystery dial."""
    for level in UiLevel:
        assert level.label
        assert len(level.describes_itself) > 40


def test_an_unrecognised_level_falls_back_to_standard_rather_than_failing():
    """A configuration file edited by hand must not stop the application
    starting, and must not silently land on the least informative level."""
    settings = Settings(_env_file=None)
    object.__setattr__(settings, "ui_level", "expert")  # not a valid level
    assert UiLevel.from_settings(settings) is UiLevel.STANDARD
