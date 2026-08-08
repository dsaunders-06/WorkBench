"""The Screener says where its figures came from, and what its filters mean (M72).

Two things, and the first is the one that matters.

**Provenance.** `FundamentalSnapshot.is_synthetic` has ridden on every snapshot
since M18, and its docstring gives the reason in as many words - "so anything
downstream that displays or reasons about a number can say where it came from".
`available_figures()` duly passes it to the LLM, so the AI Advisor has known the
provenance of these figures all along. The Screener, which renders nine
fundamental columns in a table, never asked.

That is not hypothetical. `fundamentals_source` defaults to "mock", and
`resolve_fundamentals_source` degrades to the same seeded source when the real
one cannot be built - logging that "every fundamental figure shown or traded on
will be INVENTED" and then rendering a table indistinguishable from a real one.

**Presets.** §4.8: the filters are raw factor inputs, and a PEG spinbox says
nothing about what a PEG of 1.5 implies. Each preset therefore carries the
sentence explaining its threshold, not merely a name for it.

Three levels must produce three outcomes. The Balances design reached review
rendering Guided and Standard identically because `explains()` is true for both
- M58a in miniature - so the level assertions here are explicit about all three.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.presentation.runtime import Runtime
from qat.presentation.screener import (
    _PRESETS,
    CUSTOM_PRESET,
    NOT_AVAILABLE,
    ScreenerScreen,
    ScreenResult,
    _provenance_caption,
)


def _screen(qtbot, level: str = "standard") -> ScreenerScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, ui_level=level))
    screen = ScreenerScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _row(symbol: str = "AMD", *, synthetic: bool, missing: bool = False) -> ScreenResult:
    return ScreenResult(
        symbol=symbol,
        name=symbol,
        sector="Information Technology",
        price=100.0,
        avg_volume=1_000_000,
        eps_growth_yoy=None if missing else 0.15,
        peg_ratio=None if missing else 1.5,
        dividend_yield=None if missing else 0.02,
        roe=None if missing else 0.2,
        trend="Up",
        is_synthetic=synthetic,
    )


# --- provenance ---------------------------------------------------------------


def test_an_entirely_synthetic_screen_says_the_figures_are_invented():
    """The default configuration, and the degraded fallback, look identical to
    a real run without this."""
    caption = _provenance_caption([_row(synthetic=True)], explains=False)

    assert "INVENTED" in caption
    assert "1 row(s)" in caption


def test_the_synthetic_warning_says_what_to_do_about_it_when_explaining():
    """Guided and Standard get the remedy; Professional is told the fact and
    trusted to know where the setting is."""
    rows = [_row(synthetic=True)]

    assert "Settings" in _provenance_caption(rows, explains=True)
    assert "Settings" not in _provenance_caption(rows, explains=False)


def test_a_real_screen_says_so_quietly():
    """Loud when invented, quiet when real. A line that reads the same either
    way is the disclaimer M69 replaced."""
    caption = _provenance_caption([_row(synthetic=False)], explains=True)

    assert "INVENTED" not in caption
    assert "real vendor" in caption


def test_a_mixed_screen_is_called_out_as_mixed():
    """Losing the vendor mid-session leaves a cached real snapshot beside a
    freshly invented one, and the table cannot show which is which."""
    rows = [_row("AMD", synthetic=True), _row("GS", synthetic=False)]

    caption = _provenance_caption(rows, explains=False)

    assert "MIXED" in caption
    assert "1 of 2" in caption


def test_missing_figures_are_counted_rather_than_left_to_be_scanned_for():
    """An em dash per cell is right and does not scale - a table that is mostly
    dashes should say so once."""
    caption = _provenance_caption([_row(synthetic=False, missing=True)], explains=False)

    assert "4 figure(s)" in caption
    assert NOT_AVAILABLE in caption
    assert "absent, not zero" in caption


def test_a_missing_figure_is_not_reported_as_a_provenance_problem():
    """Unanswerable and invented are different failures. An ETF with no
    earnings growth is not a synthetic row."""
    caption = _provenance_caption([_row(synthetic=False, missing=True)], explains=False)

    assert "INVENTED" not in caption
    assert "MIXED" not in caption


def test_an_empty_result_set_says_nothing():
    """Nothing was shown, so there is no provenance to state - and the status
    line already says the screen matched nothing."""
    assert _provenance_caption([], explains=True) == ""


@pytest.mark.asyncio
async def test_running_the_screen_fills_the_provenance_line(qtbot):
    """The seam. A caption function nothing calls is the M45 pattern."""
    screen = _screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)

    await screen._run_screen()

    assert screen.results_table.rowCount() > 0
    assert screen.provenance_label.text() != ""


@pytest.mark.asyncio
async def test_the_demo_runtime_is_reported_as_synthetic(qtbot):
    """`build_demo` uses the seeded mock, so the screen must say so. If this
    ever starts failing, the demo runtime has quietly acquired a real vendor."""
    screen = _screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)

    await screen._run_screen()

    assert "INVENTED" in screen.provenance_label.text()


# --- presets ------------------------------------------------------------------


def test_every_preset_explains_its_threshold_rather_than_only_naming_it():
    """§4.8's actual complaint. A named preset with no explanation moves the
    problem rather than solving it."""
    for preset in _PRESETS:
        assert len(preset.summary) > 40, f"{preset.name} has no explanation"


def test_choosing_a_preset_sets_the_thresholds(qtbot):
    screen = _screen(qtbot)

    screen.preset_combo.setCurrentText("Growth at a reasonable price")

    assert screen.min_eps_growth_input.value() == pytest.approx(10.0)
    assert screen.max_peg_input.value() == pytest.approx(2.0)


def test_switching_presets_clears_the_previous_ones_thresholds(qtbot):
    """A filter the new preset does not set must go back to its widest bound,
    or the screen silently keeps a constraint from a screen no longer chosen."""
    screen = _screen(qtbot)
    screen.preset_combo.setCurrentText("Growth at a reasonable price")

    screen.preset_combo.setCurrentText("Steady dividend payers")

    assert screen.min_eps_growth_input.value() == screen.min_eps_growth_input.minimum()
    assert screen.max_peg_input.value() == screen.max_peg_input.maximum()
    assert screen.min_div_yield_input.value() == pytest.approx(2.5)


def test_editing_a_threshold_by_hand_stops_calling_it_a_named_screen(qtbot):
    """Leaving the name in place is the worse failure - the operator would read
    "Steady dividend payers" above a result set that is no longer that."""
    screen = _screen(qtbot)
    screen.preset_combo.setCurrentText("Steady dividend payers")

    screen.min_div_yield_input.setValue(4.0)

    assert screen.preset_combo.currentText() == CUSTOM_PRESET


def test_the_default_preset_filters_nothing(qtbot):
    """The screen must open showing everything, as it did before presets
    existed - a default that silently filtered would change what the operator
    sees without being asked."""
    screen = _screen(qtbot)

    assert screen.preset_combo.currentText() == _PRESETS[0].name
    assert screen.min_eps_growth_input.value() == screen.min_eps_growth_input.minimum()
    assert screen.max_peg_input.value() == screen.max_peg_input.maximum()
    assert screen.min_div_yield_input.value() == screen.min_div_yield_input.minimum()


# --- three levels, three outcomes ---------------------------------------------


def test_guided_gets_named_screens_and_no_raw_thresholds(qtbot):
    screen = _screen(qtbot, "guided")

    assert screen.preset_row_widget.isVisibleTo(screen)
    assert screen.preset_summary.isVisibleTo(screen)
    assert not screen.threshold_row_widget.isVisibleTo(screen)


def test_standard_gets_both(qtbot):
    screen = _screen(qtbot, "standard")

    assert screen.preset_row_widget.isVisibleTo(screen)
    assert screen.preset_summary.isVisibleTo(screen)
    assert screen.threshold_row_widget.isVisibleTo(screen)


def test_professional_gets_the_raw_filters_alone(qtbot):
    screen = _screen(qtbot, "professional")

    assert not screen.preset_row_widget.isVisibleTo(screen)
    assert not screen.preset_summary.isVisibleTo(screen)
    assert screen.threshold_row_widget.isVisibleTo(screen)


def test_the_three_levels_do_not_render_identically(qtbot):
    """M58a in miniature, stated as one assertion. The Balances design reached
    review rendering Guided and Standard the same because `explains()` is true
    for both, and every test of it passed."""
    shapes = set()
    for level in ("guided", "standard", "professional"):
        screen = _screen(qtbot, level)
        shapes.add(
            (
                screen.preset_row_widget.isVisibleTo(screen),
                screen.preset_summary.isVisibleTo(screen),
                screen.threshold_row_widget.isVisibleTo(screen),
            )
        )

    assert len(shapes) == 3
