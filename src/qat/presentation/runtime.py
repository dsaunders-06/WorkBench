"""Constructs the full engine graph for a live/demo run (spec §M9/M10): wires
MarketDataFeed -> FeatureEngine -> StrategyEngine -> SignalToOrderBridge ->
OMS, plus RegimeEngine and AIAdvisoryService, all sharing one EventBus -
with the same synthetic/mock defaults used throughout testing
(SyntheticMarketDataSource, MockBroker, MockFundamentalsSource,
MockMacroSource). Consistent with every prior milestone's "no real
credentials here" stance.

A real paper or live session swaps IBAdapter in for MockBroker via
build_demo()'s broker argument - the same swap-the-implementation pattern
every milestone since M2 has used, not a rewrite. The AI engines are
resolved from Settings (see resolve_llm_engines) rather than being a
constructor swap, since M10 made the provider a user-facing Settings choice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import requests

from qat.config import Settings
from qat.data import universe
from qat.data.broker.adapter import BrokerAdapter
from qat.data.broker.mock_broker import MockBroker
from qat.data.feature_engine import FeatureEngine
from qat.data.fundamentals import FundamentalsSource, MockFundamentalsSource
from qat.data.macro_fred import MacroDataSource, MacroFeed, MockMacroSource
from qat.data.market_data import MarketDataFeed, MarketDataSource, SyntheticMarketDataSource
from qat.domain.ai_advisory.llm_engine import AnthropicEngine, DemoLLMEngine, LLMEngine, LocalEngine
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.orchestrator import Orchestrator
from qat.domain.regime_engine.engine import RegimeEngine
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch, KillSwitchEngine
from qat.domain.strategies.base import Strategy
from qat.domain.strategies.breakout import BreakoutStrategy
from qat.domain.strategies.can_slim import CanSlimStrategy
from qat.domain.strategies.dividend_growth import DividendGrowthStrategy
from qat.domain.strategies.engine import StrategyEngine
from qat.domain.strategies.garp import GarpStrategy
from qat.domain.strategies.growth import GrowthStrategy
from qat.domain.strategies.mean_reversion import MeanReversionStrategy
from qat.domain.strategies.momentum import MomentumStrategy
from qat.domain.strategies.multi_factor import MultiFactorStrategy
from qat.domain.strategies.pairs_stat_arb import PairsStatArbStrategy
from qat.domain.strategies.quality import QualityStrategy
from qat.domain.strategies.sector_rotation import SectorRotationStrategy
from qat.domain.strategies.swing import SwingStrategy
from qat.domain.strategies.trend_following import TrendFollowingStrategy
from qat.domain.strategies.value import ValueStrategy
from qat.domain.strategies.volatility import VolatilityStrategy
from qat.security import get_secret

logger = logging.getLogger(__name__)

_REACHABILITY_TIMEOUT_SECONDS = 2.0


def default_strategies() -> list[Strategy]:
    return [
        TrendFollowingStrategy(),
        MomentumStrategy(),
        CanSlimStrategy(),
        GrowthStrategy(),
        ValueStrategy(),
        GarpStrategy(),
        QualityStrategy(),
        DividendGrowthStrategy(),
        MeanReversionStrategy(),
        SwingStrategy(),
        BreakoutStrategy(),
        VolatilityStrategy(),
        PairsStatArbStrategy(),
        SectorRotationStrategy(),
        MultiFactorStrategy(),
    ]


def _local_llm_reachable(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/models", timeout=_REACHABILITY_TIMEOUT_SECONDS)
        return response.ok
    except requests.RequestException:
        return False


def _resolve_engine(choice: Literal["anthropic", "local", "demo"], settings: Settings) -> LLMEngine:
    """Backs one LLMRouter slot per the user's Settings choice (spec M10) -
    never guesses/auto-detects, since the provider is meant to be an explicit,
    selectable choice, not silently inferred from what happens to be configured."""
    if choice == "anthropic":
        if get_secret("ANTHROPIC_API_KEY"):
            return AnthropicEngine(settings=settings)
        logger.warning(
            "AI provider set to anthropic but no ANTHROPIC_API_KEY is configured - using demo"
        )
        return DemoLLMEngine()
    if choice == "local":
        if _local_llm_reachable(settings.local_llm_base_url):
            return LocalEngine(settings=settings)
        logger.warning("Local LLM at %s is not reachable - using demo", settings.local_llm_base_url)
        return DemoLLMEngine()
    return DemoLLMEngine()


def resolve_llm_engines(settings: Settings) -> tuple[LLMEngine, LLMEngine]:
    """Returns (anthropic_slot_engine, local_slot_engine) for LLMRouter.
    LLMRouter.choose() (domain/ai_advisory/router.py) decides which slot
    handles which request - position-sensitive requests always route to the
    local slot as an absolute privacy override, general requests (e.g. the
    regime narrative) route to the anthropic slot when available. Each slot's
    real backing engine is an independent Settings choice (spec M10) rather
    than a single app-wide provider toggle, so the sensitive slot can be kept
    local-only even when the general slot uses Anthropic's cloud API."""
    return (
        _resolve_engine(settings.general_request_provider, settings),
        _resolve_engine(settings.sensitive_request_provider, settings),
    )


@dataclass
class Runtime:
    """Everything a screen needs: the bus, the engines, and the settings.
    Built once in main_window.py and handed to every screen."""

    settings: Settings
    bus: EventBus
    orchestrator: Orchestrator
    broker: BrokerAdapter
    kill_switch: KillSwitch
    risk_engine: RiskEngine
    oms: OMS
    strategy_engine: StrategyEngine
    available_strategies: list[Strategy]
    regime_engine: RegimeEngine
    ai_service: AIAdvisoryService
    watchlist: tuple[str, ...]
    benchmark_symbol: str

    @classmethod
    def build_demo(
        cls,
        settings: Settings | None = None,
        watchlist: tuple[str, ...] | None = None,
        market_data_source: MarketDataSource | None = None,
        broker: BrokerAdapter | None = None,
        fundamentals_source: FundamentalsSource | None = None,
        macro_source: MacroDataSource | None = None,
        anthropic_engine: LLMEngine | None = None,
        local_engine: LLMEngine | None = None,
    ) -> Runtime:
        settings = settings or Settings()
        watchlist = watchlist if watchlist is not None else universe.resolve_watchlist(settings)
        benchmark_symbol = universe.MARKET_BENCHMARKS[settings.market]

        bus = EventBus()
        orchestrator = Orchestrator(bus)

        kill_switch = KillSwitch()
        kill_switch_engine = KillSwitchEngine(bus, kill_switch)

        risk_engine = RiskEngine(bus, kill_switch, settings=settings)
        broker = broker or MockBroker(seed=1)
        oms = OMS(broker, risk_engine, kill_switch)
        signal_bridge = SignalToOrderBridge(bus, oms)

        # The benchmark must always be streamed even if it isn't part of the
        # configured watchlist (e.g. a mega-cap category that doesn't happen
        # to include the market's benchmark ETF) - otherwise RegimeEngine
        # would never receive a MarketDataEvent for it and regime detection
        # would never fire. dict.fromkeys de-dupes while preserving order.
        feed_symbols = tuple(dict.fromkeys((benchmark_symbol, *watchlist)))

        source = market_data_source or SyntheticMarketDataSource(seed=1, interval_seconds=1.0)
        market_data_feed = MarketDataFeed(
            bus, source, feed_symbols, staleness_seconds=settings.data_staleness_seconds
        )
        feature_engine = FeatureEngine(bus)

        macro = macro_source or MockMacroSource(seed=1)
        macro_feed = MacroFeed(bus, macro, settings.fred_series, poll_interval_seconds=3600.0)

        fundamentals = fundamentals_source or MockFundamentalsSource(seed=1)
        available_strategies = default_strategies()
        # Live-deployed set starts empty (spec §K: nothing trades until a human
        # vets it via the Workbench and clicks "Deploy to Paper") - Workbench
        # appends to strategy_engine.strategies, it never starts pre-populated.
        strategy_engine = StrategyEngine(bus, [], fundamentals)

        regime_engine = RegimeEngine(
            bus, benchmark_symbol=benchmark_symbol, breadth_symbols=watchlist
        )

        anthropic_slot, local_slot = resolve_llm_engines(settings)
        router = LLMRouter(
            anthropic_engine or anthropic_slot, local_engine or local_slot, settings=settings
        )
        ai_service = AIAdvisoryService(router, risk_engine, settings=settings)

        for engine in (
            kill_switch_engine,
            risk_engine,
            market_data_feed,
            feature_engine,
            macro_feed,
            strategy_engine,
            signal_bridge,
            regime_engine,
        ):
            orchestrator.register(engine)

        return cls(
            settings=settings,
            bus=bus,
            orchestrator=orchestrator,
            broker=broker,
            kill_switch=kill_switch,
            risk_engine=risk_engine,
            oms=oms,
            strategy_engine=strategy_engine,
            available_strategies=available_strategies,
            regime_engine=regime_engine,
            ai_service=ai_service,
            watchlist=watchlist,
            benchmark_symbol=benchmark_symbol,
        )
