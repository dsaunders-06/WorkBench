"""Constructs the full engine graph for a live/demo run (spec §M9/M10): wires
MarketDataFeed -> FeatureEngine -> StrategyEngine -> SignalToOrderBridge ->
OMS, plus RegimeEngine and AIAdvisoryService, all sharing one EventBus -
with the same synthetic/mock defaults used throughout testing
(SyntheticMarketDataSource, MockBroker, MockFundamentalsSource).
Consistent with every prior milestone's "no real credentials here" stance.

Every one of those defaults is reached through a resolve_* function that
says so in the log when it falls back. Wiring a mock in directly, as the
macro source was until M27a, is what let synthetic data pass for real data
for twenty-five milestones.

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
from qat.data.broker.account_poller import AccountPoller
from qat.data.broker.adapter import BrokerAdapter
from qat.data.broker.mock_broker import MockBroker
from qat.data.earnings import EarningsCalendar, NullEarningsCalendar, YFinanceEarningsCalendar
from qat.data.feature_engine import FeatureEngine
from qat.data.fundamentals import FundamentalsSource, MockFundamentalsSource
from qat.data.history import HistoricalBarSource, resolve_history_source
from qat.data.macro_fred import FredMacroSource, MacroDataSource, MacroFeed, MockMacroSource
from qat.data.market_data import MarketDataFeed, MarketDataSource, SyntheticMarketDataSource
from qat.domain.ai_advisory.llm_engine import (
    AnthropicEngine,
    DemoLLMEngine,
    LLMEngine,
    LocalEngine,
    normalize_openai_base_url,
)
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.autonomy import (
    AutonomousExecutor,
    AutonomyGate,
    DecisionJournal,
    EquityMonitor,
)
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.reconciliation import ReconciliationMonitor
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.orchestrator import Orchestrator
from qat.domain.performance import (
    EquityCurve,
    PerformanceReport,
    PerformanceReporter,
    TradeLedger,
)
from qat.domain.performance.scorecard import StrategyScorecard, build_scorecard
from qat.domain.regime_engine.engine import RegimeEngine
from qat.domain.risk_engine.delever import DeleverSweep
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch, KillSwitchEngine
from qat.domain.session_controller import SessionController
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
from qat.domain.warm_start import WarmStart
from qat.security import get_secret

logger = logging.getLogger(__name__)

# Generous: a local server that is loading/holding a large model can take a
# couple of seconds just to answer /models, and timing out here silently
# downgrades the user's chosen provider to the canned demo engine.
_REACHABILITY_TIMEOUT_SECONDS = 10.0


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
        normalized = normalize_openai_base_url(base_url)
        response = requests.get(f"{normalized}/models", timeout=_REACHABILITY_TIMEOUT_SECONDS)
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


def resolve_market_data_source(settings: Settings) -> MarketDataSource:
    """Real or synthetic ticks (spec M14).

    A failure to construct the real source degrades to synthetic with a loud
    warning rather than refusing to start - but it is never silent, because
    believing you are trading against real prices while running on a random
    walk would be the worst of the available outcomes.
    """
    if settings.market_data_source == "alpaca":
        if settings.market != "US":
            logger.warning(
                "market_data_source=alpaca but market=%s - Alpaca serves US equities only",
                settings.market,
            )
        try:
            from qat.data.alpaca_source import AlpacaMarketDataSource

            logger.info(
                "Using real market data (Alpaca, feed=%s, poll=%.0fs).%s",
                settings.alpaca_data_feed,
                settings.alpaca_poll_seconds,
                (
                    " IEX is a single exchange carrying a small share of consolidated volume."
                    if settings.alpaca_data_feed == "iex"
                    else ""
                ),
            )
            return AlpacaMarketDataSource(
                feed=settings.alpaca_data_feed,
                poll_seconds=settings.alpaca_poll_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, but loudly
            logger.warning(
                "Could not build the Alpaca market data source (%s) - falling back to "
                "SYNTHETIC data. Prices shown are not real.",
                exc,
            )
        return SyntheticMarketDataSource(seed=1, interval_seconds=1.0)

    if settings.market_data_source == "yfinance":
        try:
            from qat.data.yfinance_source import YFinanceMarketDataSource

            logger.info(
                "Using real market data (yfinance, poll=%.0fs). This feed is free, "
                "delayed and rate-limited.",
                settings.yfinance_poll_seconds,
            )
            return YFinanceMarketDataSource(poll_seconds=settings.yfinance_poll_seconds)
        except Exception as exc:  # noqa: BLE001 - degrade, but loudly
            logger.warning(
                "Could not build the yfinance market data source (%s) - falling back to "
                "SYNTHETIC data. Prices shown are not real.",
                exc,
            )
    return SyntheticMarketDataSource(seed=1, interval_seconds=1.0)


def resolve_broker(settings: Settings) -> BrokerAdapter:
    """Builds the configured broker, falling back to MockBroker with a logged
    warning rather than failing to start (spec M12).

    A missing key or an absent SDK is a configuration problem, not a reason to
    leave the operator with no application - but it is never silent, because
    quietly paper-trading against a simulator while believing you are
    connected to a real account would be worse than either.
    """
    if settings.broker == "alpaca":
        if settings.market != "US":
            logger.warning(
                "broker=alpaca but market=%s - Alpaca trades US equities only, so this "
                "watchlist cannot be traded through it",
                settings.market,
            )
        try:
            from qat.data.broker.alpaca_adapter import AlpacaAdapter

            return AlpacaAdapter(settings=settings)
        except Exception as exc:  # noqa: BLE001 - degrade to mock, but loudly
            logger.warning("Could not build the Alpaca broker (%s) - using MockBroker", exc)
            return MockBroker(seed=1)
    if settings.broker == "ibkr":
        logger.warning(
            "broker=ibkr is configured but IBAdapter needs a running Gateway/TWS and is not "
            "auto-wired here - using MockBroker"
        )
        return MockBroker(seed=1)
    return MockBroker(seed=1)


def resolve_macro_source(settings: Settings) -> MacroDataSource:
    """Real FRED when a key is configured, the seeded mock otherwise (M27a).

    This resolver is the point of the change. MockMacroSource was wired in
    directly here from M2 to M27 with no resolver and no warning, so three of
    the regime engine's six features - VIX, yield-curve slope, credit spread -
    were `random.uniform(-1, 5)` for twenty-five milestones and nothing said
    so. On 29 July that fabricated data classified the market as low-vol,
    which gated the only promoted strategy off for a full session, and the
    system reported it as normal operation.

    So the fallback is loud about the consequence rather than the mechanism: a
    regime classified from invented macro data is itself invented, and it
    decides which strategies are allowed to trade.
    """
    if get_secret("FRED_API_KEY"):
        try:
            source = FredMacroSource()
            logger.info(
                "Using real macro data (FRED): %s", ", ".join(settings.fred_series) or "no series"
            )
            return source
        except Exception as exc:  # noqa: BLE001 - degrade, but loudly
            logger.warning("Could not build the FRED macro source (%s)", exc)

    logger.warning(
        "No FRED_API_KEY is configured - falling back to SYNTHETIC macro data. VIX, the "
        "yield-curve slope and the credit spread will be RANDOM NUMBERS, so every regime "
        "classified from them is fabricated, and the regime gate decides which strategies "
        "are allowed to trade. Set it with qat.security.set_secret('FRED_API_KEY', ...)."
    )
    return MockMacroSource(seed=1)


def _build_earnings_calendar(settings: Settings) -> EarningsCalendar:
    """The real calendar when the rail is on and a real vendor is configured.

    Follows `fundamentals_source` rather than taking a switch of its own: both
    answer "is this run talking to a real vendor", and a mock run inventing
    earnings dates would size positions down on fabricated events.

    Failure returns the null calendar rather than raising. This rail can only
    make a position smaller, so losing it costs the protection - where failing
    to start would cost the session.
    """
    if not settings.enforce_earnings_event_risk or settings.fundamentals_source != "yfinance":
        return NullEarningsCalendar()
    try:
        return YFinanceEarningsCalendar(settings.data_dir)
    except Exception as exc:  # noqa: BLE001 - degrade, but say so
        logger.warning(
            "Could not build the earnings calendar (%s) - trades will be sized without the "
            "event-risk rail, which is the pre-M57 behaviour.",
            exc,
        )
        return NullEarningsCalendar()


def resolve_fundamentals_source(
    settings: Settings,
    history_source: HistoricalBarSource,
    universe: tuple[str, ...],
) -> FundamentalsSource:
    """Real fundamentals when configured, the seeded mock otherwise (spec M18).

    The real source is wrapped in the TTL disk cache, and given a relative
    strength ranker built over the same universe the strategies see - the rank
    is a percentile, so it only means anything relative to the set it was
    measured against.

    A failure to construct it degrades to the mock, loudly. The mock answers
    every field, so a silent fallback would turn "we could not reach the
    vendor" into a screen of confident invented figures.
    """
    if settings.fundamentals_source != "yfinance":
        return MockFundamentalsSource(seed=1)  # the earnings calendar follows the same switch

    try:
        from qat.data.fundamentals_cache import CachingFundamentalsSource, FundamentalsCache
        from qat.data.relative_strength import UniverseRelativeStrength
        from qat.data.yfinance_fundamentals import YFinanceFundamentalsSource

        real = YFinanceFundamentalsSource(
            relative_strength=UniverseRelativeStrength(history_source, universe)
        )
        cache = FundamentalsCache(settings.data_dir, ttl_days=settings.fundamentals_cache_days)
        return CachingFundamentalsSource(real, cache)
    except Exception as exc:  # noqa: BLE001 - degrade, but loudly
        logger.warning(
            "Could not build the real fundamentals source (%s) - falling back to SYNTHETIC "
            "fundamentals. Every fundamental figure shown or traded on will be INVENTED.",
            exc,
        )
        return MockFundamentalsSource(seed=1)


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
    equity_monitor: EquityMonitor
    reconciliation_monitor: ReconciliationMonitor
    delever_sweep: DeleverSweep
    trade_ledger: TradeLedger
    equity_curve: EquityCurve
    performance_reporter: PerformanceReporter
    session_controller: SessionController
    account_poller: AccountPoller
    autonomy_gate: AutonomyGate
    decision_journal: DecisionJournal
    strategy_engine: StrategyEngine
    available_strategies: list[Strategy]
    regime_engine: RegimeEngine
    ai_service: AIAdvisoryService
    watchlist: tuple[str, ...]
    benchmark_symbol: str
    history_source: HistoricalBarSource
    # Optional so every existing construction, including the tests, is
    # unaffected. Only the adoption banner reads it.
    signal_bridge: SignalToOrderBridge | None = None

    def opened_position_symbols(self) -> set[str]:
        """Symbols this app opened itself, from its own entry record (M33e).

        The adoption banner had no way to tell "someone else traded this
        account" from "this is my own position after a restart", and said the
        former for both. The second is the normal case now.
        """
        if self.signal_bridge is None:
            return set()
        return self.signal_bridge.opened_symbols()

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
        broker = broker or resolve_broker(settings)
        # Built before the OMS because the OMS writes to it: every order
        # decision is journalled in every execution mode (M20), not only the
        # unattended ones.
        decision_journal = DecisionJournal(settings.data_dir)
        oms = OMS(
            broker,
            risk_engine,
            kill_switch,
            bus=bus,
            journal=decision_journal,
            # Gives the fill watermark somewhere to survive a restart (M50).
            settings=settings,
        )
        # Shared by every screen so the account is read once per interval
        # regardless of how many are watching (M21).
        account_poller = AccountPoller(broker, interval_seconds=settings.account_poll_seconds)
        # Built before the bridge, because sizing reads from it (M35). The
        # ledger is the only source of truth about whether anything worked;
        # the journal records only what was decided.
        trade_ledger = TradeLedger(bus, settings.data_dir, settings=settings)
        signal_bridge = SignalToOrderBridge(
            bus,
            oms,
            settings=settings,
            bar_interval_seconds=settings.bar_interval_seconds,
            # Closes the loop: what a strategy actually achieved decides how
            # much its next trade risks. Falls back to the documented defaults
            # until it has edge_min_trades to measure.
            trade_ledger=trade_ledger,
            # Event risk (M57). Built here rather than inside the bridge so a
            # paper or mock run gets the null calendar and the rail abstains,
            # exactly as it did before the rail existed.
            earnings_calendar=_build_earnings_calendar(settings),
        )

        # Autonomy (spec M13). All four pieces are constructed regardless of
        # execution_mode so the UI can always show the journal and the rails,
        # but AutonomousExecutor short-circuits unless Settings.autonomy_enabled
        # - the engine graph does not change shape when the mode does.
        equity_monitor = EquityMonitor(broker, kill_switch, settings=settings, bus=bus)
        # Adopts whatever the account already holds as the reconciliation
        # baseline, then polls (spec M15). Without adoption, an account with any
        # pre-existing position reads as a mismatch and trips the kill-switch on
        # every startup.
        reconciliation_monitor = ReconciliationMonitor(oms, settings=settings, bus=bus)
        delever_sweep = DeleverSweep(oms, risk_engine.governor, settings=settings, bus=bus)

        # Evidence layer (spec M16): the equity curve and the reports built
        # from it. The ledger itself is constructed earlier, because sizing now
        # reads from it.
        equity_curve = EquityCurve(settings.data_dir)
        # The equity monitor already polls the account on a timer, so it doubles
        # as the curve's sampler rather than adding a second poller for the
        # same number.
        equity_monitor.equity_curve = equity_curve
        performance_reporter = PerformanceReporter(
            trade_ledger,
            equity_curve,
            settings=settings,
            journal=decision_journal,
        )

        def _scorecard_for(strategy: str) -> StrategyScorecard | None:
            """Evidence lookup for the autonomy gate (M16). Computed on demand
            from the ledger rather than cached, so a strategy that degrades
            stops qualifying on its very next order rather than at some later
            refresh."""
            trades = trade_ledger.closed_trades(strategy)
            return build_scorecard(strategy, trades, settings)

        autonomy_gate = AutonomyGate(settings, kill_switch, scorecard_source=_scorecard_for)
        autonomous_executor = AutonomousExecutor(
            bus,
            oms,
            autonomy_gate,
            decision_journal,
            equity_monitor=equity_monitor,
            settings=settings,
        )
        if settings.autonomy_enabled:
            logger.warning(
                "AUTONOMOUS EXECUTION IS ENABLED - qualifying orders will be signed off "
                "without confirmation. Promoted strategies: %s",
                ", ".join(settings.autonomous_strategies_tuple) or "none",
            )

        # The benchmark must always be streamed even if it isn't part of the
        # configured watchlist (e.g. a mega-cap category that doesn't happen
        # to include the market's benchmark ETF) - otherwise RegimeEngine
        # would never receive a MarketDataEvent for it and regime detection
        # would never fire. dict.fromkeys de-dupes while preserving order.
        feed_symbols = tuple(dict.fromkeys((benchmark_symbol, *watchlist)))

        source = market_data_source or resolve_market_data_source(settings)
        market_data_feed = MarketDataFeed(
            bus, source, feed_symbols, staleness_seconds=settings.data_staleness_seconds
        )
        feature_engine = FeatureEngine(bus, bar_interval_seconds=settings.bar_interval_seconds)
        history_source = resolve_history_source(settings)

        macro = macro_source or resolve_macro_source(settings)
        macro_feed = MacroFeed(bus, macro, settings.fred_series, poll_interval_seconds=3600.0)

        fundamentals = fundamentals_source or resolve_fundamentals_source(
            settings, history_source, watchlist
        )
        available_strategies = default_strategies()

        def _deploy_configured(engine: StrategyEngine) -> None:
            """Puts the configured strategies live before the feed starts.

            The live set was in-memory only and filled by a Workbench click,
            which cannot work for an unattended session: the run of 30 July
            went nine hours with an empty set under a banner reading AUTO-TRADE
            ACTIVE. A name that matches nothing is reported rather than
            ignored - a typo here costs an entire session, and the failure is
            otherwise indistinguishable from a market with no setups.
            """
            by_name = {s.name: s for s in available_strategies}
            unknown = [n for n in settings.deployed_strategies_tuple if n not in by_name]
            if unknown:
                logger.error(
                    "QAT_DEPLOYED_STRATEGIES names %s, which do not exist and will NOT trade. "
                    "Known strategies: %s",
                    ", ".join(unknown),
                    ", ".join(sorted(by_name)),
                )
            for name in settings.deployed_strategies_tuple:
                if name in by_name:
                    engine.deploy(by_name[name])

        # Live-deployed set starts empty (spec §K: nothing trades until a human
        # Live set starts empty and is filled from QAT_DEPLOYED_STRATEGIES
        # below (M27b). Spec §K's rule - nothing trades until a human vets it -
        # is preserved in substance: the human act is now declaring the
        # strategy in configuration rather than clicking a button that no
        # unattended session can reach. Workbench deployments still work and
        # remain session-only.
        strategy_engine = StrategyEngine(
            bus,
            [],
            fundamentals,
            bar_interval_seconds=settings.bar_interval_seconds,
            regime_eligibility_mass=settings.regime_eligibility_mass,
            # Read-only position access, so strategies can emit exits (M14).
            # Narrowed to the PositionSource protocol - a strategy engine is
            # never handed something that can place an order.
            position_source=broker,
        )
        _deploy_configured(strategy_engine)

        regime_engine = RegimeEngine(
            bus,
            benchmark_symbol=benchmark_symbol,
            breadth_symbols=watchlist,
            bar_interval_seconds=settings.bar_interval_seconds,
        )

        # Seeds every rolling buffer from daily history before the feed starts
        # (M27a). Registered first below, because BarAggregator.seed refuses to
        # run once a live tick has been recorded. All three aggregators are
        # seeded, not just the strategy engine's: the bridge's ATR sets the
        # stop distance and the stop distance sets the position size, so a
        # daily strategy sized off an unseeded buffer is a sizing bug.
        warm_start = WarmStart(
            history_source,
            macro,
            feed_symbols,
            benchmark_symbol,
            aggregators=(strategy_engine.bars, signal_bridge.bars, feature_engine.bars),
            regime_engine=regime_engine,
            macro_series=settings.fred_series,
        )

        anthropic_slot, local_slot = resolve_llm_engines(settings)
        router = LLMRouter(
            anthropic_engine or anthropic_slot, local_engine or local_slot, settings=settings
        )
        ai_service = AIAdvisoryService(router, risk_engine, settings=settings)

        async def _narrate_report(report: PerformanceReport) -> str:
            """AI commentary on a report whose figures are already final. The
            reporter treats a failure here as cosmetic, so a model outage costs
            the commentary and never the report itself."""
            return await ai_service.get_performance_narrative(report.to_markdown())

        # Attached after the AI service exists rather than passed at
        # construction, so the dependency order reads in the order it happens.
        performance_reporter.narrator = _narrate_report

        # Simulated prices have no trading hours, so gating on them would make
        # the demo app look dead all weekend. Real data is the case the gate
        # exists for.
        session_gating = (
            settings.session_follows_market_hours and settings.market_data_source != "synthetic"
        )
        session_controller = SessionController(
            market_data_feed,
            strategy_engine,
            market=settings.market,
            enabled=session_gating,
            poll_seconds=settings.session_poll_seconds,
        )

        for engine in (
            # First: the orchestrator starts engines in order, and every buffer
            # must be seeded before the feed delivers a tick into it.
            warm_start,
            kill_switch_engine,
            risk_engine,
            equity_monitor,
            reconciliation_monitor,
            delever_sweep,
            trade_ledger,
            performance_reporter,
            market_data_feed,
            feature_engine,
            macro_feed,
            strategy_engine,
            # The executor subscribes before the bridge can publish, so no
            # pending order can slip past it during startup.
            autonomous_executor,
            signal_bridge,
            regime_engine,
            # Last: the orchestrator has started the feed by now, so this
            # engine's first check stands the session down if the market is
            # shut rather than racing a feed that has not started yet.
            session_controller,
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
            equity_monitor=equity_monitor,
            reconciliation_monitor=reconciliation_monitor,
            delever_sweep=delever_sweep,
            trade_ledger=trade_ledger,
            equity_curve=equity_curve,
            performance_reporter=performance_reporter,
            session_controller=session_controller,
            account_poller=account_poller,
            autonomy_gate=autonomy_gate,
            decision_journal=decision_journal,
            strategy_engine=strategy_engine,
            available_strategies=available_strategies,
            signal_bridge=signal_bridge,
            regime_engine=regime_engine,
            ai_service=ai_service,
            watchlist=watchlist,
            benchmark_symbol=benchmark_symbol,
            history_source=history_source,
        )
