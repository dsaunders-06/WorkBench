"""The banner must not claim to be trading when no prices are arriving.

The first unattended session held AUTO-TRADE ACTIVE for six hours with a dead
feed. Nothing traded - no ticks means no signals - but the most prominent
statement on the screen was the opposite of the truth, which is exactly what
the banner exists to prevent.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.events import MarketDataFeedEvent
from qat.domain.strategies.swing import SwingStrategy
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime


def _window(qtbot) -> MainWindow:
    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, execution_mode="auto", autonomous_strategies="swing")
    )
    # A strategy is deployed because these tests are about what the banner says
    # when something happens to an app that CAN trade. With an empty deployed
    # set the banner correctly reports that nothing can (M27b).
    runtime.strategy_engine.deploy(SwingStrategy())
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    return window


async def test_banner_reports_a_dead_feed(qtbot):
    window = _window(qtbot)
    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()

    await window._on_feed_health(
        MarketDataFeedEvent(healthy=False, reason="no market data for 12 minutes")
    )

    assert "MARKET DATA DOWN" in window.execution_banner.text()
    assert "12 minutes" in window.execution_banner.text()


async def test_banner_clears_when_the_feed_recovers(qtbot):
    window = _window(qtbot)
    await window._on_feed_health(MarketDataFeedEvent(healthy=False, reason="no market data"))
    assert "MARKET DATA DOWN" in window.execution_banner.text()

    await window._on_feed_health(
        MarketDataFeedEvent(healthy=True, reason="market data is flowing again")
    )

    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()


async def test_a_halt_outranks_a_dead_feed(qtbot):
    """Both are true at once; the operator needs the decision, not the weather.

    A halt is something the system chose to do and which needs a human to
    undo. An outage is a condition that may clear itself. Showing the outage
    over the halt would hide the state that requires action.
    """
    window = _window(qtbot)
    await window._on_feed_health(MarketDataFeedEvent(healthy=False, reason="no market data"))

    window.runtime.kill_switch.trigger_manual("operator")

    assert "EXECUTION HALTED" in window.execution_banner.text()
    assert "Manual trigger" in window.execution_banner.text()

    # And once the halt is cleared, the outage underneath is still reported.
    window.runtime.kill_switch.reset("operator")
    assert "MARKET DATA DOWN" in window.execution_banner.text()
