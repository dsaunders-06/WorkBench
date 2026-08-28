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
from support.source_corpus import source_files

from qat.presentation import theme

UI = pathlib.Path(theme.__file__).parent
# ⚠️ Item 20. This was a bare `UI.glob("*.py")`, and every absence assertion
# below is only worth as much as the list it iterates: an empty SOURCES makes
# all of them pass while checking nothing. `source_files` refuses that.
SOURCES = source_files(UI, exclude={"theme.py", "__init__.py"}, minimum=8)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# --- The type scale ----------------------------------------------------------


# ⚠️ Item 20. This was `r"font-size: (\d+)px"` - exactly one space after the
# colon and none before the unit. `font-size:14px` and `font-size : 14px` are
# the same declaration to Qt and were invisible to it, so the guard's green
# meant "no off-scale size written in one particular style". Measured on
# 28 August: the loose pattern finds nothing the strict one missed, so this
# narrowness was LATENT, not hiding a live violation - unlike M135's, which
# was. It is closed anyway, because a guard whose reach depends on whitespace
# is one `black` run away from mattering.
_FONT_SIZE = re.compile(r"font-size\s*:\s*(\d+)\s*px")


def _off_scale_sizes(text: str) -> list[str]:
    """The scan, over a string, so its own eyesight can be asserted."""
    allowed = {theme.CAPTION, theme.BODY, theme.SUBHEAD, theme.TITLE}
    return [f"{size}px" for size in _FONT_SIZE.findall(text) if int(size) not in allowed]


def test_only_scale_font_sizes_appear_anywhere():
    """Four steps, not eight. A fifth size is how a scale stops being one."""
    offenders = [
        f"{path.name}: {size}" for path in SOURCES for size in _off_scale_sizes(_read(path))
    ]
    assert not offenders, f"off-scale font sizes: {offenders}"


@pytest.mark.parametrize(
    "declaration",
    [
        "font-size: 14px",
        "font-size:14px",
        "font-size : 14px",
        "font-size: 14 px",
        'style = f"font-size: 14px; color: {theme.MUTED};"',
    ],
)
def test_the_scan_sees_an_off_scale_size_however_it_is_spaced(declaration):
    """⚠️ THE POSITIVE CONTROL. `test_only_scale_font_sizes_appear_anywhere`
    asserts an ABSENCE, and an absence is what a blind scan reports too. This
    plants the violation and requires the scan to find it - the half of M135's
    lesson that a non-empty corpus does not cover.

    The f-string case is here by name: that token type is precisely what the
    colour guard stopped seeing in 3.12."""
    assert _off_scale_sizes(declaration) == ["14px"]


def test_the_scan_does_not_flag_a_size_that_is_on_the_scale():
    """The other direction. A guard that flags everything earns an allowlist,
    and an allowlist is not read."""
    assert _off_scale_sizes(f"font-size: {theme.BODY}px") == []


def test_the_scale_is_ordered_and_distinct():
    steps = [theme.CAPTION, theme.BODY, theme.SUBHEAD, theme.TITLE]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


# --- The colour roles --------------------------------------------------------


# ⚠️ Item 20, and the positive control below found this rather than the sweep:
# this was `r'"(#[0-9a-fA-F]{6})"'`, which requires the hex to be the WHOLE
# quoted literal. A screen does not write `"#b71c1c"`; it writes
# `"color: #b71c1c;"` - so the one shape this guard exists to catch was the
# shape it could not see, in either quote style. Measured 28 August: nothing
# live was hiding behind it, because `test_design_system_is_the_only_source_of_
# colour` scans string TOKENS and would have caught it. Latent, and now closed.
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _theme_named_hex(text: str, named: set[str]) -> list[str]:
    """Named colours written by hand, skipping whole-line comments.

    A comment is skipped because both this file and the modules it scans
    QUOTE a hex to explain the rule, and a guard that cannot survive being
    documented gets deleted the first time someone writes about it - the same
    allowance `test_m111_trading_day` makes, for the same reason.
    """
    return [
        found
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
        for found in _HEX.findall(line)
        if found.lower() in named
    ]


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
    offenders = [
        f"{path.name}: {hexv}"
        for path in SOURCES
        for hexv in _theme_named_hex(_read(path), {c.lower() for c in named})
    ]
    assert not offenders, f"raw hex used where the theme has a name for it: {offenders}"


@pytest.mark.parametrize(
    "planted",
    [
        'self.setStyleSheet("color: {}; font-weight: bold;")',
        "self.setStyleSheet('color: {};')",
        'style = f"color: {}; background: {{theme.MUTED}};"',
        'PALETTE = {{"bad": "{}"}}',
    ],
)
def test_the_hex_scan_sees_a_named_colour_written_by_hand(planted):
    """⚠️ THE POSITIVE CONTROL for the assertion above, which reports the same
    empty list whether the codebase is clean or the regex has stopped matching.

    ⚠️ It earned its place on the first run: the pattern it replaced could only
    see a hex that was the ENTIRE literal, so none of the four lines below -
    including the ordinary stylesheet string that is how this actually gets
    written - was visible to the guard.
    """
    assert _theme_named_hex(planted.format(theme.DANGER), {theme.DANGER.lower()}) == [theme.DANGER]


def test_the_hex_scan_ignores_a_hex_quoted_in_a_comment():
    """This file and the ones it scans explain the rule by naming the colour."""
    assert (
        _theme_named_hex(f"    # never write {theme.DANGER} by hand", {theme.DANGER.lower()}) == []
    )


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
