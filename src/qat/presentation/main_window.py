"""Top-level window: mode banner + tabs for the eight screens.

Paper vs live must be unmistakable at all times (spec §K/§13.3) - the banner
is always visible and colour-coded, not something a screen can hide.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from qat.config import Settings
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.blotter import BlotterScreen
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.regime_monitor import RegimeMonitorScreen
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.screener import ScreenerScreen
from qat.presentation.settings import SettingsScreen
from qat.presentation.workbench import WorkbenchScreen

_PAPER_STYLE = "background-color: #1b5e20; color: white; padding: 6px; font-weight: bold;"
_LIVE_STYLE = "background-color: #b71c1c; color: white; padding: 6px; font-weight: bold;"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.setWindowTitle("Quant Advisory Terminal")
        self.resize(1200, 800)

        central = QWidget()
        layout = QVBoxLayout(central)

        banner = QLabel(f"MODE: {settings.trading_mode.upper()}")
        banner.setStyleSheet(_LIVE_STYLE if settings.is_live else _PAPER_STYLE)
        layout.addWidget(banner)

        tabs = QTabWidget()
        tabs.addTab(DashboardScreen(), "Dashboard")
        tabs.addTab(WorkbenchScreen(), "Strategy Workbench")
        tabs.addTab(RegimeMonitorScreen(), "Regime Monitor")
        tabs.addTab(RiskConsoleScreen(), "Risk Console")
        tabs.addTab(AiAdvisorScreen(), "AI Advisor")
        tabs.addTab(BlotterScreen(), "Order Blotter")
        tabs.addTab(ScreenerScreen(), "Screener")
        tabs.addTab(SettingsScreen(), "Settings")
        layout.addWidget(tabs)

        self.setCentralWidget(central)
