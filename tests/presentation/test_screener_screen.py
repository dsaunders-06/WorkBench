"""ScreenerScreen (spec §K/M10): filters narrow the result set, and results
reflect the same MockFundamentalsSource data the live StrategyEngine uses -
no separate fundamentals plumbing was introduced for this screen."""

from __future__ import annotations

from qat.config import Settings
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
    screen.sector_combo.setCurrentText("Technology")

    await screen._run_screen()

    sector_column = 1
    for row in range(screen.results_table.rowCount()):
        assert screen.results_table.item(row, sector_column).text() == "Technology"


def test_trend_label_thresholds():
    assert _trend_label(0.01) == "Up"
    assert _trend_label(-0.01) == "Down"
    assert _trend_label(0.0) == "Flat"
    assert _trend_label(float("nan")) == "-"
