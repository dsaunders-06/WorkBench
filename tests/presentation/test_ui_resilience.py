"""Regressions for the two field failures found after M10 shipped.

1. A failing LLM produced *no* visible feedback at all: the coroutine was
   launched with asyncio.ensure_future and its exception died inside an
   un-awaited Task, so the user just saw a button that did nothing.
2. Correlation was recomputed on every market-data tick, which is O(n^2)
   pandas work per tick (O(n^3) per second) and saturated the event loop
   at realistic watchlist sizes.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.events import MarketDataEvent
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen


class _ExplodingAiService:
    """Stands in for an unreachable/misconfigured local LLM."""

    async def get_regime_narrative(self, context, anthropic_available: bool = True):
        raise RuntimeError("local LLM unreachable")


def _runtime(**kwargs: object) -> Runtime:
    return Runtime.build_demo(settings=Settings(_env_file=None), **kwargs)  # type: ignore[arg-type]


async def test_backtest_shows_ai_failure_but_keeps_its_results(qtbot):
    runtime = _runtime()
    runtime.ai_service = _ExplodingAiService()  # type: ignore[assignment]
    screen = WorkbenchScreen(runtime)
    qtbot.addWidget(screen)

    await screen._run_backtest()

    assert "unavailable" in screen.ai_note_label.text().lower()
    assert "local LLM unreachable" in screen.ai_note_label.text()
    # The backtest itself succeeded, so its metrics must survive the AI failure.
    assert screen._last_result is not None
    assert screen.run_button.isEnabled()


async def test_ai_advisor_reports_failure_in_the_conversation(qtbot):
    runtime = _runtime()
    runtime.ai_service = _ExplodingAiService()  # type: ignore[assignment]
    screen = AiAdvisorScreen(runtime)
    qtbot.addWidget(screen)

    await screen._ask("what is the regime?")

    transcript = screen.conversation.toPlainText()
    assert "unavailable" in transcript.lower()
    assert "local LLM unreachable" in transcript
    assert screen.ask_button.isEnabled()


async def test_market_data_tick_does_not_recompute_correlations(qtbot):
    runtime = _runtime()
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    calls = 0
    original = screen._refresh_correlation_table

    def counting() -> None:
        nonlocal calls
        calls += 1
        original()

    screen._refresh_correlation_table = counting  # type: ignore[method-assign]

    for _ in range(20):
        for symbol in runtime.watchlist:
            await screen._on_market_data(MarketDataEvent(symbol=symbol, price=100.0, volume=1000))

    assert calls == 0, "correlation must be refreshed by the timer, not per tick"

    screen._on_timer_tick()
    assert calls == 1


async def test_correlation_table_is_populated_by_the_timer(qtbot):
    runtime = _runtime()
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)

    for step in range(20):
        for symbol in runtime.watchlist:
            await screen._on_market_data(
                MarketDataEvent(symbol=symbol, price=100.0 + step, volume=1000)
            )
    screen._on_timer_tick()

    diagonal = screen.correlation_table.item(0, 0)
    assert diagonal is not None
    assert diagonal.text() == "1.00"  # a symbol is perfectly correlated with itself


@pytest.mark.parametrize("deployed", [False, True])
async def test_strategy_engine_only_rebuilds_the_ticked_symbol(qtbot, deployed):
    runtime = _runtime()
    engine = runtime.strategy_engine
    if deployed:
        engine.strategies.append(runtime.available_strategies[0])
    await engine.start()

    for symbol in runtime.watchlist:
        await engine._on_market_data(MarketDataEvent(symbol=symbol, price=100.0, volume=1000))

    if deployed:
        # Every symbol that ticked is present, so cross-sectional strategies
        # still see the full universe.
        assert set(engine._context_cache) == set(runtime.watchlist)
    else:
        # Nothing deployed - the expensive feature rebuild is skipped entirely.
        assert engine._context_cache == {}
