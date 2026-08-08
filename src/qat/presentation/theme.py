"""The single source of visual truth for every screen (M45).

Before this, colour and type lived in 67 inline `setStyleSheet` calls spread
across thirteen files, with no palette and no stylesheet. That produced
thirteen hex values expressing about four meanings - five different reds all
saying "danger" - and eight font sizes between 11px and 18px with no ratio
between them. The application was not badly designed; it was undesigned, every
choice locally defensible and no two screens agreeing.

Three layers, so that a change lands in one place:

* **Primitives** are raw values named by what they ARE (`RED_700`). Nothing
  outside this module should use them.
* **Semantics** are named by what they MEAN (`DANGER`, `MUTED`). This is what
  screens use, and it is why a future dark mode is a change here rather than a
  change everywhere.
* **Recipes** are complete style strings for the two patterns that actually
  recur: a coloured piece of text, and a callout with a background and border.

The brief is "classic and simple", and the type scale reflects it: four steps,
not eight. Nothing here is decorative - a smaller vocabulary is what makes an
interface look deliberate rather than accumulated.
"""

from __future__ import annotations

from typing import Any, Final

# --------------------------------------------------------------------------
# Layer 1: primitives. Raw values, named by what they are.
# --------------------------------------------------------------------------
# Every one of these was already in the codebase; this only gives them names.
# The two exceptions are noted in SEMANTIC below.

RED_900: Final = "#7f1d1d"
RED_700: Final = "#b71c1c"
RED_600: Final = "#b91c1c"
RED_50: Final = "#fee2e2"

GREEN_900: Final = "#1b5e20"

AMBER_900: Final = "#78350f"
AMBER_600: Final = "#b45309"
AMBER_50: Final = "#fef3c7"

SLATE_500: Final = "#5b6572"
SLATE_800: Final = "#444444"
NAVY_900: Final = "#1e3a5f"

WHITE: Final = "#ffffff"

# Saturated primaries, for CHARTS only (M78). These are drawn on pyqtgraph's
# near-black plot background, where every colour above - chosen to sit on a pale
# UI - is close to invisible. They are their own family for that reason, and
# nothing outside a plot should reach for them.
PURE_YELLOW: Final = "#ffff00"
PURE_CYAN: Final = "#00ffff"
PURE_RED: Final = "#ff0000"
PURE_GREEN: Final = "#00ff00"

# --------------------------------------------------------------------------
# Layer 2: semantics. Named by what they mean.
# --------------------------------------------------------------------------
# A screen asks for DANGER, never for RED_700. That indirection is the whole
# point: the meaning is stable where the value is not.
#
# Consolidated here, and the only intentional visual changes in this module:
#   #d9534f (3 uses) and #b3261e (1 use) -> DANGER
#   #5cb85c (2 uses)                     -> SUCCESS
# Six call sites shift by a shade. Everything else keeps its exact colour.

DANGER: Final = RED_700
"""Something is wrong, or a control that can lose money."""

DANGER_STRONG: Final = RED_900
"""Danger text ON a danger surface, and the solid danger banner."""

DANGER_SURFACE: Final = RED_50
DANGER_BORDER: Final = RED_600

WARNING: Final = AMBER_600
"""Needs attention but nothing is broken."""

WARNING_STRONG: Final = AMBER_900
WARNING_SURFACE: Final = AMBER_50
WARNING_BORDER: Final = AMBER_600

SUCCESS: Final = GREEN_900
"""Working as intended. Also the safe-mode banner."""

MUTED: Final = SLATE_500
"""Explanatory text, and any figure that is unavailable rather than zero.

Load-bearing: an unavailable number rendered at full weight reads as data.
"""

ACCENT: Final = NAVY_900
"""Structural emphasis. Deliberately not a status colour."""

BORDER: Final = SLATE_800
"""The hairline round a panel. Four screens spelled this `#444` by hand."""


# --------------------------------------------------------------------------
# Chart series. Named by their ROLE IN A PLOT, not by status (M78).
# --------------------------------------------------------------------------
# Six pyqtgraph pens were single letters - `pen="y"`, `pen="r"` - which is
# outside the palette in the most literal way: not a wrong colour, no colour at
# all, just a code the library resolves. Naming them is what lets a future
# change to the cone's colours happen here instead of in three files.
#
# Deliberately NOT mapped onto DANGER/WARNING/SUCCESS. Those are dark by design
# so they read as text on a pale surface, and on the plot's black background
# they disappear. Same meanings, different medium, so different values.

SERIES_PRIMARY: Final = PURE_YELLOW
"""The strategy's own equity curve - the line the screen is about."""

SERIES_BENCHMARK: Final = PURE_CYAN
"""What buying the index did over the same bars. Deliberately cool against the
warm primary, so the two are separable without reading the legend."""

BAND_LOW: Final = PURE_RED
"""The p5 edge of a Monte Carlo cone."""

BAND_MID: Final = PURE_YELLOW
"""The p50 path. Shares the primary's colour because it is the same claim -
"this is the central case" - made about a distribution instead of a history."""

BAND_HIGH: Final = PURE_GREEN
"""The p95 edge."""

# --------------------------------------------------------------------------
# Type scale. Four steps, down from eight sizes with no ratio.
# --------------------------------------------------------------------------
# Mapping applied at migration: 12->13, 14->15, 16->15, 17->18. Six
# declarations move by one or two pixels; none changes its role.

CAPTION: Final = 11
"""Dense tables and secondary annotation."""

BODY: Final = 13
"""Default. Anything read as prose."""

SUBHEAD: Final = 15
"""Panel headings and figures that lead a section."""

TITLE: Final = 18
"""One per screen at most."""

# --------------------------------------------------------------------------
# Spacing. A 4px rhythm.
# --------------------------------------------------------------------------

SPACE_XS: Final = 4
SPACE_SM: Final = 8
SPACE_MD: Final = 12
SPACE_LG: Final = 16
SPACE_XL: Final = 24


# --------------------------------------------------------------------------
# Layer 3: recipes. The two patterns that actually recur.
# --------------------------------------------------------------------------


def text(colour: str, *, size: int | None = None, bold: bool = False) -> str:
    """Coloured text, optionally sized and weighted.

    The commonest case by far: `setStyleSheet(theme.text(theme.MUTED))`.
    """
    parts = [f"color: {colour};"]
    if size is not None:
        parts.append(f"font-size: {size}px;")
    if bold:
        parts.append("font-weight: bold;")
    return " ".join(parts)


def callout(kind: str) -> str:
    """A bordered block on a tinted background - the panel that explains a
    consequence rather than labelling a control.

    That pattern is the best thing about this interface and the easiest to lose
    in a restyle, so it gets a name here to make it deliberate.
    """
    if kind == "danger":
        return (
            f"color: {DANGER_STRONG}; background: {DANGER_SURFACE}; "
            f"border: 1px solid {DANGER_BORDER}; padding: {SPACE_SM}px;"
        )
    if kind == "warning":
        return (
            f"color: {WARNING_STRONG}; background: {WARNING_SURFACE}; "
            f"border: 1px solid {WARNING_BORDER}; padding: {SPACE_SM}px;"
        )
    raise ValueError(f"unknown callout kind: {kind!r}")


def banner(colour: str) -> str:
    """A solid full-width band. Used for the mode and execution banners, which
    state the two facts that change what every other number on screen means."""
    return (
        f"background-color: {colour}; color: {WHITE}; " f"padding: {SPACE_SM}px; font-weight: bold;"
    )


def label_axes(plot: Any, *, bottom: str, left: str) -> None:
    """Name both axes of a chart, with units (M55).

    Measured before this existed: ONE axis-label call in the whole presentation
    layer. Every other chart rendered bare axes and left the reader to infer
    whether the x-axis was dates, trading days or a sample count, and whether
    the y-axis was dollars, percent or an index. On screens whose purpose is
    deciding whether a strategy works, that is an invitation to read the wrong
    quantity confidently.

    Both labels are REQUIRED keyword arguments, and that is the point: a chart
    whose axes cannot be named is a finding about the chart, not something to
    label vaguely. "Time" is barely better than nothing - the unit is the part
    that carries the meaning.

    Lives here rather than in each screen for the same reason every colour
    does. Twenty hand-styled labels would recreate the inline-stylesheet problem
    this module exists to end.
    """
    plot.setLabel("bottom", bottom)
    plot.setLabel("left", left)
