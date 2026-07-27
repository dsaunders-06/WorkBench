"""Top-level window: mode banners + tabs for the nine screens.

Paper vs live must be unmistakable at all times (spec §K/§13.3) - the banner
is always visible and colour-coded, not something a screen can hide. M13 adds
a second banner on the same principle for execution mode, since "is anything
trading without me right now" is exactly as important to know at a glance, and
it updates live as the kill-switch trips rather than only at startup.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from qat.domain.events import KillSwitchEvent, MarketDataFeedEvent
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.blotter import BlotterScreen
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.performance import PerformanceScreen
from qat.presentation.regime_monitor import RegimeMonitorScreen
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime
from qat.presentation.screener import ScreenerScreen
from qat.presentation.settings import SettingsScreen
from qat.presentation.workbench import WorkbenchScreen

_PAPER_STYLE = "background-color: #1b5e20; color: white; padding: 6px; font-weight: bold;"
_LIVE_STYLE = "background-color: #b71c1c; color: white; padding: 6px; font-weight: bold;"

_RECOMMEND_STYLE = "background-color: #1e3a5f; color: white; padding: 6px; font-weight: bold;"
_AUTO_STYLE = "background-color: #b45309; color: white; padding: 6px; font-weight: bold;"
_HALTED_STYLE = "background-color: #7f1d1d; color: white; padding: 6px; font-weight: bold;"
# Amber, not the halt red: an outage is a condition to notice, a halt is a
# decision that was taken. Painting them identically would blur the two.
_FEED_DOWN_STYLE = "background-color: #b45309; color: white; padding: 6px; font-weight: bold;"


class MainWindow(QMainWindow):
    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self.runtime = runtime
        settings = runtime.settings
        self.setWindowTitle("Quant Advisory Terminal")
        self.resize(1200, 800)

        central = QWidget()
        layout = QVBoxLayout(central)

        banner = QLabel(f"MODE: {settings.trading_mode.upper()}")
        banner.setStyleSheet(_LIVE_STYLE if settings.is_live else _PAPER_STYLE)
        layout.addWidget(banner)

        self._feed_down_reason: str | None = None
        self.execution_banner = QLabel()
        layout.addWidget(self.execution_banner)
        self._refresh_execution_banner()
        runtime.bus.subscribe(KillSwitchEvent, self._on_kill_switch)
        # Catches the paths that publish nothing - a staleness trip, and this
        # window's own Risk Console halting or resetting the switch.
        runtime.kill_switch.add_listener(self._refresh_execution_banner)
        runtime.bus.subscribe(MarketDataFeedEvent, self._on_feed_health)

        tabs = QTabWidget()
        tabs.addTab(DashboardScreen(runtime), "Dashboard")
        tabs.addTab(WorkbenchScreen(runtime), "Strategy Workbench")
        tabs.addTab(RegimeMonitorScreen(runtime), "Regime Monitor")
        tabs.addTab(RiskConsoleScreen(runtime), "Risk Console")
        tabs.addTab(AiAdvisorScreen(runtime), "AI Advisor")
        tabs.addTab(BlotterScreen(runtime), "Order Blotter")
        tabs.addTab(ScreenerScreen(runtime), "Screener")
        tabs.addTab(PerformanceScreen(runtime), "Performance")
        tabs.addTab(SettingsScreen(runtime), "Settings")
        layout.addWidget(tabs)

        self.setCentralWidget(central)

    async def _on_kill_switch(self, event: KillSwitchEvent) -> None:
        # The reason comes from the event, not from KillSwitch.reason: both
        # this and KillSwitchEngine subscribe to the same event and the bus
        # runs handlers concurrently, so reading shared state here would be a
        # race on whether the engine had tripped the switch yet.
        self._refresh_execution_banner(halt_reason=event.reason)

    async def _on_feed_health(self, event: MarketDataFeedEvent) -> None:
        """A dead feed has to be as visible as a halt.

        The first unattended session ran six hours with no market data while
        this banner read AUTO-TRADE ACTIVE. Nothing was trading - no ticks
        means no signals - but the screen asserted the opposite of the truth,
        which is the failure the banner exists to prevent.
        """
        self._feed_down_reason = None if event.healthy else event.reason
        self._refresh_execution_banner()

    def _refresh_execution_banner(self, halt_reason: str | None = None) -> None:
        """Three states, never two: off, active, and halted-with-a-reason.

        Collapsing "halted" into "off" would be the dangerous simplification -
        an operator needs to be able to tell "I turned this off" from "it
        stopped itself, and here is why".
        """
        settings = self.runtime.settings

        if halt_reason or self.runtime.kill_switch.tripped:
            reason = halt_reason or self.runtime.kill_switch.reason or "unknown reason"
            self.execution_banner.setText(f"EXECUTION HALTED - KILL-SWITCH: {reason}")
            self.execution_banner.setStyleSheet(_HALTED_STYLE)
            return

        if self._feed_down_reason:
            self.execution_banner.setText(f"MARKET DATA DOWN - {self._feed_down_reason}")
            self.execution_banner.setStyleSheet(_FEED_DOWN_STYLE)
            return

        if settings.autonomy_enabled:
            promoted = ", ".join(settings.autonomous_strategies_tuple) or "none promoted"
            self.execution_banner.setText(
                f"EXECUTION: AUTO-TRADE ACTIVE - orders self-sign ({promoted})"
            )
            self.execution_banner.setStyleSheet(_AUTO_STYLE)
            return

        self.execution_banner.setText("EXECUTION: RECOMMEND - every order awaits your sign-off")
        self.execution_banner.setStyleSheet(_RECOMMEND_STYLE)
