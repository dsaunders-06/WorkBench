"""A dead regime classifier must not look like one that agrees (M27a).

StrategyEngine falls open to its default regime, so a crashed classifier keeps
the application trading with the regime gate silently disabled. On 28 July the
HMM crashed on every fit for a whole session and nothing on screen changed;
the gate being off had to be reconstructed afterwards.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.events import MarketDataFeedEvent, RegimeHealthEvent
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


async def test_the_banner_reports_a_classifier_that_is_not_classifying(qtbot):
    window = _window(qtbot)
    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()

    await window._on_regime_health(
        RegimeHealthEvent(healthy=False, reason="HMM fit failed on 301 bars")
    )

    text = window.execution_banner.text()
    assert "REGIME ENGINE DOWN" in text
    assert "HMM fit failed on 301 bars" in text
    # The consequence, not just the fault: strategies are still being gated,
    # just on a default rather than on a reading of the market.
    assert "default" in text


async def test_the_banner_is_silent_until_the_engine_says_something(qtbot):
    """Warning before the first bar would warn on every launch, and a banner
    that always warns is one nobody reads."""
    window = _window(qtbot)

    assert "REGIME ENGINE DOWN" not in window.execution_banner.text()


async def test_the_banner_clears_when_classification_resumes(qtbot):
    window = _window(qtbot)
    await window._on_regime_health(RegimeHealthEvent(healthy=False, reason="posterior failed"))
    assert "REGIME ENGINE DOWN" in window.execution_banner.text()

    await window._on_regime_health(RegimeHealthEvent(healthy=True, reason="classifying - bull"))

    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()


async def test_a_dead_feed_outranks_a_dead_classifier(qtbot):
    """Both are true at once, and no prices is the larger fact: a classifier
    cannot classify what it is not being sent."""
    window = _window(qtbot)
    await window._on_regime_health(RegimeHealthEvent(healthy=False, reason="warming up"))
    await window._on_feed_health(
        MarketDataFeedEvent(healthy=False, reason="no market data for 12 minutes")
    )

    assert "MARKET DATA DOWN" in window.execution_banner.text()

    # And with the feed restored, the classifier underneath is still reported.
    await window._on_feed_health(MarketDataFeedEvent(healthy=True, reason="flowing again"))
    assert "REGIME ENGINE DOWN" in window.execution_banner.text()


async def test_a_halt_outranks_both(qtbot):
    window = _window(qtbot)
    await window._on_regime_health(RegimeHealthEvent(healthy=False, reason="warming up"))

    window.runtime.kill_switch.trigger_manual("operator")

    assert "EXECUTION HALTED" in window.execution_banner.text()
