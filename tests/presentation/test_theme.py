"""The visual system holds, and cannot silently erode (M45).

Before this, colour and type lived in 67 inline setStyleSheet calls across
thirteen files: thirteen hex values expressing about four meanings, five
different reds all saying "danger", and eight font sizes with no ratio between
them. The application was not badly designed, it was undesigned.

These tests exist because that state is the natural resting point of any
codebase where styling is done locally. Without something asserting the
vocabulary, it comes back one defensible choice at a time.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from qat.presentation import theme

UI = pathlib.Path(theme.__file__).parent
SOURCES = [p for p in sorted(UI.glob("*.py")) if p.name not in {"theme.py", "__init__.py"}]


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# --- The type scale ----------------------------------------------------------


def test_only_scale_font_sizes_appear_anywhere():
    """Four steps, not eight. A fifth size is how a scale stops being one."""
    allowed = {theme.CAPTION, theme.BODY, theme.SUBHEAD, theme.TITLE}
    offenders: list[str] = []
    for path in SOURCES:
        for size in re.findall(r"font-size: (\d+)px", _read(path)):
            if int(size) not in allowed:
                offenders.append(f"{path.name}: {size}px")
    assert not offenders, f"off-scale font sizes: {offenders}"


def test_the_scale_is_ordered_and_distinct():
    steps = [theme.CAPTION, theme.BODY, theme.SUBHEAD, theme.TITLE]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


# --- The colour roles --------------------------------------------------------


def test_no_screen_declares_a_raw_colour_that_the_theme_names():
    """A screen asks for DANGER, never for #b71c1c. That indirection is what
    makes a future dark mode a change here rather than a change everywhere."""
    named = {
        theme.DANGER,
        theme.DANGER_STRONG,
        theme.DANGER_BORDER,
        theme.DANGER_SURFACE,
        theme.SUCCESS,
        theme.WARNING,
        theme.WARNING_STRONG,
        theme.WARNING_SURFACE,
        theme.MUTED,
        theme.ACCENT,
    }
    offenders: list[str] = []
    for path in SOURCES:
        text = _read(path)
        for hexv in re.findall(r'"(#[0-9a-fA-F]{6})"', text):
            if hexv.lower() in named:
                offenders.append(f"{path.name}: {hexv}")
    assert not offenders, f"raw hex used where the theme has a name for it: {offenders}"


def test_every_semantic_role_is_distinct_from_the_others_it_must_not_be_confused_with():
    """Danger, warning and success must never collapse into each other - they
    are the difference between 'wrong', 'watch this' and 'fine'."""
    assert theme.DANGER != theme.WARNING != theme.SUCCESS
    assert theme.DANGER != theme.SUCCESS
    assert theme.MUTED not in {theme.DANGER, theme.WARNING, theme.SUCCESS}


# --- The recipes -------------------------------------------------------------


def test_text_recipe_produces_valid_qss():
    assert theme.text(theme.MUTED) == f"color: {theme.MUTED};"
    styled = theme.text(theme.DANGER, size=theme.SUBHEAD, bold=True)
    assert f"font-size: {theme.SUBHEAD}px" in styled
    assert "font-weight: bold" in styled


def test_callout_carries_text_background_and_border():
    """The pattern that explains a consequence rather than labelling a control.
    It gets a name so that a restyle has to remove it deliberately."""
    danger = theme.callout("danger")
    for part in ("color:", "background:", "border:"):
        assert part in danger
    assert theme.DANGER_SURFACE in danger
    assert theme.DANGER_BORDER in danger


def test_an_unknown_callout_kind_is_refused_rather_than_rendered_blank():
    with pytest.raises(ValueError):
        theme.callout("mauve")


def test_banner_is_solid_and_legible():
    assert theme.banner(theme.SUCCESS).startswith(f"background-color: {theme.SUCCESS}")
    assert theme.WHITE in theme.banner(theme.DANGER_STRONG)
