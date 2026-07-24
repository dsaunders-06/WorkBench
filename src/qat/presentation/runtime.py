"""Constructs the full engine graph for a live/demo run (spec §M9): wires
MarketDataFeed -> FeatureEngine -> StrategyEngine -> SignalToOrderBridge ->
OMS, plus RegimeEngine and AIAdvisoryService, all sharing one EventBus -
with the same synthetic/mock defaults used throughout testing
(SyntheticMarketDataSource, MockBroker, MockFundamentalsSource,
MockMacroSource, DemoLLMEngine). Consistent with every prior milestone's
"no real credentials here" stance.

A real paper or live session swaps IBAdapter in for MockBroker and
AnthropicEngine/LocalEngine in for DemoLLMEngine via build_demo()'s
constructor arguments - the same swap-the-implementation pattern every
milestone since M2 has used, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

from qat.config import Settings
from qat.data.broker.adapter import BrokerAdapter
from qat.data.broker.mock_broker import MockBroker
from qat.data.feature_engine import FeatureEngine
from qat.data.fundamentals import FundamentalsSource, MockFundamentalsSource
from qat.data.macro_fred import MacroDataSource, MacroFeed, MockMacroSource
from qat.data.market_data import MarketDataFeed, MarketDataSource, SyntheticMarketDataSource
from qat.domain.ai_advisory.llm_engine import DemoLLMEngine, LLMEngine
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

_DEFAULT_WATCHLIST = ("SPY", "AAPL", "MSFT", "GOOGL")


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

    @classmethod
    def build_demo(
        cls,
        settings: Settings | None = None,
        watchlist: tuple[str, ...] = _DEFAULT_WATCHLIST,
        market_data_source: MarketDataSource | None = None,
        broker: BrokerAdapter | None = None,
        fundamentals_source: FundamentalsSource | None = None,
        macro_source: MacroDataSource | None = None,
        anthropic_engine: LLMEngine | None = None,
        local_engine: LLMEngine | None = None,
    ) -> Runtime:
        settings = settings or Settings()
        bus = EventBus()
        orchestrator = Orchestrator(bus)

        kill_switch = KillSwitch()
        kill_switch_engine = KillSwitchEngine(bus, kill_switch)

        risk_engine = RiskEngine(bus, kill_switch, settings=settings)
        broker = broker or MockBroker(seed=1)
        oms = OMS(broker, risk_engine, kill_switch)
        signal_bridge = SignalToOrderBridge(bus, oms)

        source = market_data_source or SyntheticMarketDataSource(seed=1, interval_seconds=1.0)
        market_data_feed = MarketDataFeed(
            bus, source, watchlist, staleness_seconds=settings.data_staleness_seconds
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
            bus, benchmark_symbol=watchlist[0], breadth_symbols=watchlist[1:]
        )

        demo_engine = DemoLLMEngine()
        router = LLMRouter(
            anthropic_engine or demo_engine, local_engine or demo_engine, settings=settings
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
        )
