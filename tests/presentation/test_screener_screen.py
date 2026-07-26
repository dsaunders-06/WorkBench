"""ScreenerScreen (spec §K/M10): filters narrow the result set, and results
reflect the same MockFundamentalsSource data the live StrategyEngine uses -
no separate fundamentals plumbing was introduced for this screen."""

from __future__ import annotations

from qat.config import Settings
from qat.data import instruments
from qat.presentation.runtime import Runtime
from qat.presentation.screener import ScreenerScreen, _trend_label


def _build_screen(qtbot) -> ScreenerScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = ScreenerScreen(runtime)
    qtbot.addWidget(screen)
    return screen


async def test_run_screen_populates_results_for_megacap_category(qtbot):
    screen = _build_screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)

    await screen._run_screen()

    assert screen.results_table.rowCount() > 0
    assert "candidates matched" in screen.status_label.text()


async def test_dividend_yield_filter_narrows_results(qtbot):
    screen = _build_screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)
    await screen._run_screen()
    unfiltered_count = screen.results_table.rowCount()

    screen.min_div_yield_input.setValue(3.0)
    await screen._run_screen()

    assert 0 < screen.results_table.rowCount() < unfiltered_count


async def test_sector_filter_only_returns_matching_sector(qtbot):
    screen = _build_screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)
    # Real GICS-style sector names since M12 replaced the invented ones.
    screen.sector_combo.setCurrentText("Information Technology")

    await screen._run_screen()

    # Resolved from the header rather than hardcoded - a new column shifting
    # the index is exactly what silently broke this test before.
    sector_column = _column_index(screen, "Sector")
    assert screen.results_table.rowCount() > 0
    for row in range(screen.results_table.rowCount()):
        assert screen.results_table.item(row, sector_column).text() == "Information Technology"


async def test_results_show_the_listed_entity_name_beside_the_symbol(qtbot):
    screen = _build_screen(qtbot)
    screen.category_combo.setCurrentText("megacap")
    screen.min_avg_volume_input.setValue(0)

    await screen._run_screen()

    symbol_column = _column_index(screen, "Symbol")
    name_column = _column_index(screen, "Name")
    assert screen.results_table.rowCount() > 0
    for row in range(screen.results_table.rowCount()):
        symbol = screen.results_table.item(row, symbol_column).text()
        name = screen.results_table.item(row, name_column).text()
        assert name == instruments.name_for(symbol)
        # Every megacap symbol is a known one, so the name must be a real name
        # rather than name_for()'s symbol-echo fallback.
        assert name != symbol


async def test_unknown_symbol_falls_back_to_the_symbol_itself(qtbot):
    """A curated watchlist can contain anything the operator typed, so the
    name column must degrade rather than blank out or raise."""
    screen = _build_screen(qtbot)
    screen.runtime.settings.watchlist_curated_us = "ZZZZ"
    screen.category_combo.setCurrentText("curated")
    screen.market_combo.setCurrentText("US")
    screen.min_avg_volume_input.setValue(0)

    await screen._run_screen()

    name_column = _column_index(screen, "Name")
    assert screen.results_table.rowCount() == 1
    assert screen.results_table.item(0, name_column).text() == "ZZZZ"


def _column_index(screen: ScreenerScreen, header: str) -> int:
    for index in range(screen.results_table.columnCount()):
        if screen.results_table.horizontalHeaderItem(index).text() == header:
            return index
    raise AssertionError(f"No {header!r} column in the results table")


def test_trend_label_thresholds():
    assert _trend_label(0.01) == "Up"
    assert _trend_label(-0.01) == "Down"
    assert _trend_label(0.0) == "Flat"
    assert _trend_label(float("nan")) == "-"
