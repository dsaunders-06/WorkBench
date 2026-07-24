"""Drives the main window and all six real screens with a demo Runtime
built on mocks/synthetic sources (spec §K smoke test) - the placeholder-era
smoke test upgraded once M9 wired real data into every screen.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.blotter import BlotterScreen
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.main_window import MainWindow
from qat.presentation.regime_monitor import RegimeMonitorScreen
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen

_EXPECTED_TABS = [
    "Dashboard",
    "Strategy Workbench",
    "Regime Monitor",
    "Risk Console",
    "AI Advisor",
    "Order Blotter",
    "Screener",
    "Settings",
]


def _build_runtime(**settings_kwargs: object) -> Runtime:
    return Runtime.build_demo(settings=Settings(_env_file=None, **settings_kwargs))  # type: ignore[arg-type]


def test_main_window_renders_all_screens_in_paper_mode(qtbot):
    window = MainWindow(_build_runtime())
    qtbot.addWidget(window)

    tab_widget = next(
        child for child in window.centralWidget().children() if hasattr(child, "tabText")
    )
    labels = [tab_widget.tabText(i) for i in range(tab_widget.count())]

    assert labels == _EXPECTED_TABS


def test_main_window_shows_live_banner_when_live(qtbot):
    window = MainWindow(_build_runtime(trading_mode="live"))
    qtbot.addWidget(window)

    banner = next(child for child in window.centralWidget().children() if hasattr(child, "text"))
    assert "LIVE" in banner.text()


def test_all_six_real_screens_construct_without_error(qtbot):
    runtime = _build_runtime()

    for screen_cls in (
        DashboardScreen,
        WorkbenchScreen,
        RegimeMonitorScreen,
        RiskConsoleScreen,
        AiAdvisorScreen,
        BlotterScreen,
    ):
        screen = screen_cls(runtime)
        qtbot.addWidget(screen)


async def test_dashboard_refresh_populates_nav_tile(qtbot):
    runtime = _build_runtime()
    dashboard = DashboardScreen(runtime)
    qtbot.addWidget(dashboard)

    await dashboard._refresh()

    assert dashboard.nav_tile._value.text() != "-"


async def test_regime_monitor_updates_on_regime_event(qtbot):
    from qat.domain.events import RegimeEvent

    runtime = _build_runtime()
    screen = RegimeMonitorScreen(runtime)
    qtbot.addWidget(screen)

    await screen._on_regime(
        RegimeEvent(label="bull", probs={"bull": 0.7, "bear": 0.3}, exposure_scalar=1.0)
    )

    assert "bull" in screen.regime_label.text()
    assert screen.history_list.count() == 1
