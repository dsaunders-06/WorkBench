"""Drives historical bars through the PRODUCTION path (W2 step 2).

Not a backtester in the usual sense: nothing here re-implements a strategy, a
rail or a fill. It wires the real StrategyEngine, the real SignalToOrderBridge,
the real OMS and the real autonomy path to a SimulatedBroker, and moves a
clock. Every decision is made by the code that trades.

One simulated day, and the order matters:

  1. prime the day's true OHLC into BOTH aggregators - the engine keeps its own
     buffer and so does the bridge;
  2. publish MarketDataEvent at that day's close, which is what actually
     triggers evaluation;
  3. advance the broker, which fills yesterday's orders at today's open and
     fires any stop or target the day's range touched;
  4. absorb broker fills, which turns those protective executions into
     ClosedTrade rows through the real M88 path.

Step 3 is last because `advance` moves the broker's own clock: an order
submitted on day D fills on the advance that opens D+1, which is the next-open
rule the fill model already commits to.

**The autonomy path is wired, and it has to be.** `sign_off` is the sole route
to the broker and `AutonomousExecutor` is the only thing that calls it, so a
replay without it would submit orders that sat in `pending_signoff` forever and
report an honest-looking zero. The session therefore runs in `auto` execution
mode; a caller passing `recommend` gets a harness that cannot transact, which
is why the settings are read rather than assumed.

Step 2 scope: ONE symbol, no portfolio, no regime. A session loop that works
for one symbol and lies about ten is worse than one that only claims one.

**PRECONDITION: the frames must be DATE-ALIGNED.** The warm start seeds by
index POSITION - `ReplayHistorySource(bars, until_index=n)` - so position n has
to be the same date for every symbol. A universe where one symbol's history
starts a session earlier seeds that symbol past the replay boundary, and
`prime_bar` then refuses to move backwards. Found on the first ASX run: all 95
symbols carried 500 bars and only the benchmark covered the earliest one.

The error is loud rather than silent, which is why this is documented rather
than guarded here - but a caller assembling a universe from separate vendor
calls should intersect the indexes before handing them over.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pandas as pd

from qat.config import Settings
from qat.data.bars import Bar, floor_to_interval
from qat.data.broker.simulated_broker import OpeningPosition, SimulatedBroker
from qat.data.fundamentals import MockFundamentalsSource
from qat.data.macro_fred import MacroObservation
from qat.domain.autonomy.executor import AutonomousExecutor
from qat.domain.autonomy.gate import AutonomyGate
from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.replay_sources import ReplayHistorySource, ReplayMacroSource
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.events import MacroEvent, MarketDataEvent
from qat.domain.market_calendar import MARKET_TIMEZONES, regular_hours
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.regime_engine.engine import RegimeEngine
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.strategies.engine import StrategyEngine
from qat.domain.warm_start import WarmStart

_DAILY_SECONDS = 86_400.0
# How far into the session the simulated clock sits, as a fraction of it.
#
# NOT the midpoint, which is the obvious choice and the wrong one:
# `SESSION_PHASES` puts 0.33-0.68 in the "Midday Lull", and that phase is
# excluded from `AUTONOMOUS_ELIGIBLE_PHASES` for having the thinnest liquidity
# of the day. A replay clocked at exactly mid-session therefore has every order
# refused at sign-off, and produces no trades at all.
#
# 0.25 sits inside "Morning Trend" for both markets - 11:07 in New York and
# 11:30 in Sydney - and is where the old hardcoded 15:00 UTC happened to fall
# for the US, which is why that worked and why nothing noticed it was
# US-specific.
_SESSION_FRACTION = 0.25
# The executor's retry loop is wall-clock driven and has no meaning in a replay
# that crosses a decade in seconds. Pushed out of the way rather than disabled,
# so the production object is used exactly as it ships.
_INERT_RETRY_SECONDS = 86_400.0


def _as_of(observations: list[MacroObservation], when: datetime) -> float | None:
    """The reading current on `when`, carried forward rather than interpolated.

    MacroHistory's rule, applied to the live half of the replay so both halves
    agree: a series publishing on Friday is genuinely the market's best
    information all weekend, where an interpolated value is a number nobody
    could have seen.
    """
    latest: float | None = None
    for observation in observations:
        if observation.ts > when:
            break
        latest = observation.value
    return latest


class ReplaySession:
    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        strategies: Sequence[object],
        settings: Settings,
        warm_bars: int = 60,
        macro: dict[str, list[MacroObservation]] | None = None,
        benchmark: str = "SPY",
        opening_positions: dict[str, OpeningPosition] | None = None,
        start_regime: bool = True,
        evaluate_at: str = "close",
    ) -> None:
        self.bars = bars
        self.settings = settings
        self.warm_bars = warm_bars
        self._macro = macro or {}
        self.benchmark = benchmark
        # How the REGIME GATE is ablated, and the only rail that needs a seam
        # here (W2 step 6). Every other rail is a Settings value that can be set
        # beyond reach; this one arrives as `RegimeEvent.exposure_scalar`, so
        # switching it off means the engine never publishes and
        # `RiskEngine.regime_scalar` holds its 1.0 default.
        #
        # A parameter rather than the caller monkeypatching `regime_engine.start`
        # - which is what the plan proposed and what nothing could test.
        self.start_regime = start_regime
        # WHEN the strategy sees the day, which is the cadence difference G1
        # measured rather than the one it was blamed on.
        #
        # "close" - the day's true OHLC is primed and evaluation runs on it, so
        #   the decision for day D uses bars through D COMPLETE.
        # "open"  - one event carrying the day's OPEN, which rolls D-1 into the
        #   completed history and leaves D as a one-print stub. The decision
        #   then uses bars through D-1 plus that stub, WHICH IS EXACTLY WHAT
        #   LIVE HAS AT 13:30:10 - its aggregator has one print of today and a
        #   complete yesterday. The rest of the day is folded in afterwards
        #   without an event, so the daily history stays true and no extra
        #   evaluation is manufactured.
        #
        # The information sets differ by a full day, and that is a different
        # thing from evaluation FREQUENCY: live's 32 approvals on 31 July were
        # decisions about a frame the replay never evaluated against.
        if evaluate_at not in ("close", "open"):
            raise ValueError(f"evaluate_at must be 'close' or 'open', not {evaluate_at!r}")
        self.evaluate_at = evaluate_at
        self.bus = EventBus()
        self.kill_switch = KillSwitch()
        self.cost_model = CostModel.from_settings(settings)
        self.broker = SimulatedBroker(bars=bars, cost_model=self.cost_model)
        if opening_positions:
            # Before anything else reads the book: the governor's position count
            # and its aggregate risk-at-stop are both computed from what is
            # held, so a book adopted after the first evaluation would leave the
            # window's first decisions made against an empty account.
            self.broker.adopt_opening_book(opening_positions)
        self.oms = OMS(
            self.broker,
            RiskEngine(
                self.bus,
                self.kill_switch,
                settings=settings,
                # Or every audited decision is stamped with the day the replay
                # RAN rather than the day it simulated (W2 G1).
                clock=self._simulated_now,
            ),
            self.kill_switch,
            bus=self.bus,
            settings=settings,
            # Or the fill watermark starts at the WALL clock, every simulated
            # fill is older than that, and the absorb sweep in `run` records
            # nothing while reporting success (W2 step 6).
            clock=self._simulated_now,
        )
        # The only source of realised outcomes. Without it the harness opens
        # positions, watches stops fire, correctly drops the position count, and
        # measures nothing - which leaves an ablation able to compare which
        # rails BOUND but never whether the rails HELPED.
        self.ledger = TradeLedger(self.bus, settings.data_dir, settings=settings)
        self.engine = StrategyEngine(
            self.bus,
            list(strategies),  # type: ignore[arg-type]
            # Deterministic and synthetic, deliberately. A live vendor answers
            # as of TODAY, so a 2016 replay asking about a symbol would be
            # handed 2026's balance sheet - the same look-ahead the earnings
            # calendar has, and worse because it would look plausible. Swing is
            # technical and reads none of it; a fundamental strategy cannot be
            # replayed at all until point-in-time fundamentals exist, and that
            # is a stated limitation rather than a silent one.
            fundamentals_source=MockFundamentalsSource(),
            bar_interval_seconds=_DAILY_SECONDS,
        )
        self.bridge = SignalToOrderBridge(
            self.bus,
            self.oms,
            settings=settings,
            bar_interval_seconds=_DAILY_SECONDS,
            # The same callable the autonomy gate reads. Without it the minimum
            # hold and the weekly churn cap compare a simulated entry against
            # the wall clock and stop binding, silently - in the harness built
            # to measure whether rails help.
            clock=self._simulated_now,
        )
        self.regime_engine = RegimeEngine(
            self.bus,
            benchmark_symbol=benchmark,
            breadth_symbols=tuple(bars),
            bar_interval_seconds=_DAILY_SECONDS,
            # ⚠️ Milestone C. Without this the replay built the DEFAULT six
            # columns whatever `regime_features` said, so every `--feature` run
            # compared two identical arms and reported NOT EXERCISED - a
            # truthful statement about the arms and a meaningless one about the
            # feature. Four columns were "measured" that way on 28 August,
            # including an ASX control that should have differed.
            features=settings.regime_features,
        )
        self.journal = DecisionJournal(settings.data_dir)
        self.executor = AutonomousExecutor(
            self.bus,
            self.oms,
            AutonomyGate(settings, self.kill_switch, clock=self._simulated_now),
            self.journal,
            settings=settings,
            retry_interval_seconds=_INERT_RETRY_SECONDS,
        )

    async def _warm_start(self) -> None:
        """Seed every buffer AND the regime engine, through the production path.

        `WarmStart` is what the live application runs, and it already seeds the
        aggregators plus the regime engine from two ports. A second warm path
        here would be the duplication this whole harness exists to avoid, and
        would drift from the live one the first time either changed.

        The regime engine's own seed is point-in-time correct: it pairs each
        bar with `macro.as_of(series, ts)` rather than one constant reading,
        which is both look-ahead-safe and the reason its covariance matrix is
        not singular. `min_fit_bars` is 60 DAILY bars - roughly three months,
        the window over which VIX and credit spreads genuinely move - so a warm
        prefix shorter than that leaves the regime defaulted rather than
        measured.
        """
        if self.warm_bars <= 0:
            return
        start = min(self.warm_bars, len(self.broker.session_dates) - 1)
        warm = WarmStart(
            ReplayHistorySource(self.bars, until_index=start),
            ReplayMacroSource(self._macro, until=self.broker.session_dates[start].to_pydatetime()),
            symbols=tuple(self.bars),
            benchmark_symbol=self.benchmark,
            aggregators=(self.engine.bars, self.bridge.bars),
            regime_engine=self.regime_engine,
            macro_series=tuple(self._macro),
            n_bars=start,
        )
        await warm.seed()
        # The replayed period begins where the warm prefix ends. A day both
        # seeded and primed is counted twice, and a duplicated day silently
        # doubles its weight in every rolling window computed from it.
        self.broker._index = start

    def _simulated_now(self) -> datetime:
        """Mid-session on the day being replayed.

        The autonomy gate refuses outside market hours, and against the WALL
        clock a replay refuses every order it ever produces. Measured before
        this existed: the strategy emitted a correct buy, the bridge sized it,
        the order reached `pending_signoff`, and the journal recorded
        `blocked - US market is closed (before open)`. One row, and the run
        would otherwise have reported an honest-looking zero trades.

        The gate takes an injectable clock for precisely this reason - its own
        docstring says a market-hours gate read against the wall clock "passes
        or fails by time of day". The replay's clock is the simulated date.

        MID-SESSION IN THE MARKET'S OWN TIMEZONE, which this used to get wrong
        for every market but one. It returned a fixed 15:00 UTC, justified as
        *"inside the US session (13:30-20:00)"* - and the ASX trades 10:00-16:00
        SYDNEY, which is 00:00-06:00 UTC. 15:00 UTC is 01:00 the next day in
        Sydney, so every ASX order was refused by the market-hours gate, and on
        a Friday the gate reported a weekend.

        Measured on the first ASX run: seven entries approved by the risk
        engine, every one blocked at sign-off with *"ASX market is closed
        (weekend)"*, none reaching the broker. They then sat in `pending_signoff`
        counting as committed exposure, which drove the gap-risk budget to
        refuse the other six hundred and eighty candidates. **A whole run of
        rail measurements against a book that never existed.**

        The exact instant still does not matter to any decision - the fill
        happens at the NEXT bar's open regardless - but it has to be inside the
        session, or nothing transacts at all.
        """
        day = self.broker.current_date.date()
        tz = MARKET_TIMEZONES[self.settings.market]
        open_time, close_time = regular_hours(self.settings.market)
        opens = datetime.combine(day, open_time, tzinfo=tz)
        closes = datetime.combine(day, close_time, tzinfo=tz)
        return (opens + (closes - opens) * _SESSION_FRACTION).astimezone(UTC)

    async def run(self) -> None:
        await self._warm_start()
        # FIRST, and before the regime engine can publish anything. `start` is
        # the only place RiskEngine subscribes to RegimeEvent, and without it
        # `regime_scalar` holds its constructor default of 1.0 for the whole
        # replay - measured across the G1 window on 13 August: 1.0 on all 28
        # harness decisions while live varied 0.4/0.5/0.7/1.0. The harness was
        # therefore sizing up to 2.5x larger than the book it was being
        # compared against, and SPY on 31 July crossed the cost-to-risk limit
        # on that difference alone (13.8% live, 7.3% harness).
        #
        # A DIFFERENT FAMILY of defect from the three clock seams: the object
        # was correctly constructed and correctly wired, and simply never
        # started, so a subscription the live app has is one the harness
        # silently lacked. Nothing errors - the rail holds the permissive
        # default, which is the direction that hides the failure.
        await self.oms.risk_engine.start()
        # Before the executor, so no fill can be announced to a ledger that is
        # not yet subscribed to OrderFilledEvent.
        await self.ledger.start()
        if self.start_regime:
            await self.regime_engine.start()
        await self.engine.start()
        await self.bridge.start()
        await self.executor.start()
        try:
            while True:
                await self._one_day()
                if not self.broker.advance():
                    return
                # AFTER the advance, which is what fires stops and targets.
                # Sweeping before it would ask about a day on which nothing had
                # happened yet. This is also what makes the M88 absorb path
                # genuinely exercised rather than merely claimed to be.
                #
                # The final advance returns False and skips this by design: it
                # moved no clock, so no new fill can exist.
                await self.oms.absorb_broker_fills()
                # AFTER the advance, so an order the gate refused yesterday is
                # reconsidered against TODAY. The executor's own retry loop is
                # wall-clock driven and inert here by design, so without this a
                # single blocked day loses the order permanently - measured, a
                # time stop fired on Memorial Day 2024, the gate correctly
                # refused to trade a US holiday, and nothing asked again for the
                # remaining hundred sessions.
                await self.executor.retry_pending()
        finally:
            await self.executor.stop()
            await self.bridge.stop()
            await self.engine.stop()
            if self.start_regime:
                await self.regime_engine.stop()
            await self.ledger.stop()
            await self.oms.risk_engine.stop()

    async def _one_day(self) -> None:
        today = self.broker.current_date
        # Macro first, and every day. Seeding fills the matrix to the boundary;
        # after that the FRED columns freeze unless they keep arriving, and a
        # constant column across a decade is the singular covariance that made
        # the fit return NaN on 28 July - the same failure by a slower route.
        for series, observations in self._macro.items():
            value = _as_of(observations, today.to_pydatetime())
            if value is not None:
                await self.bus.publish(MacroEvent(series=series, value=value))
        for symbol, frame in self.bars.items():
            if today not in frame.index:
                continue
            # Normalised to plain floats in one pass. Indexing a row column by
            # column leaves every value typed as "scalar or Series", which is
            # true of a frame with a duplicated index - and a duplicated date
            # is a data defect that should surface as a type error here rather
            # than as a Bar holding a Series.
            selected = frame.loc[today]
            if not isinstance(selected, pd.Series):
                raise ValueError(
                    f"{symbol} has more than one bar dated {today}. A duplicated date silently "
                    "doubles a day's weight in every rolling window computed from it."
                )
            row = {str(name): float(value) for name, value in selected.items()}
            bar = Bar(
                ts=floor_to_interval(today.to_pydatetime(), _DAILY_SECONDS),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row.get("volume", 0.0),
            )
            if self.evaluate_at == "open":
                await self._open_cadence(symbol, bar)
                continue
            # BOTH buffers. The engine keeps its own and so does the bridge, and
            # a bar primed into only one would leave the other sizing against a
            # history that never moved.
            self.engine.bars.prime_bar(symbol, bar)
            self.bridge.bars.prime_bar(symbol, bar)
            await self.bus.publish(
                MarketDataEvent(
                    symbol=symbol,
                    price=bar.close,
                    volume=bar.volume,
                    ts=bar.ts,
                )
            )

    async def _open_cadence(self, symbol: str, bar: Bar) -> None:
        """Evaluate on the morning's information set, then fold the day in.

        One event carrying the OPEN. That rolls the previous day's forming bar
        into the completed history and leaves today as a one-print stub, which
        is precisely what the live aggregator holds seconds after the bell - and
        the frame the live book's decisions were computed from.

        `prime_bar` cannot be used for this. It refuses a bar on a boundary it
        has already reached, and that guard is right: an older bar landing after
        a newer one corrupts every rolling window computed from the buffer. So
        the day is completed through `add_tick` instead.

        NO EVENT IS PUBLISHED FOR THE REST OF THE DAY, and that is what makes
        this different from the four-synthetic-ticks idea the design rejected.
        That was rejected because mid-day ticks manufacture mid-day EVALUATIONS
        whose order decides which signals fire - "an arbitrary choice of whether
        the high or the low tick comes first". Evaluation is triggered by the
        event, not by the bar, so folding the range in silently creates none.
        Order cannot bias the result either: `add_tick` only takes `max` and
        `min`, so the finished bar is the same whichever way round they arrive.
        """
        await self.bus.publish(
            MarketDataEvent(symbol=symbol, price=bar.open, volume=0.0, ts=bar.ts)
        )
        for aggregator in (self.engine.bars, self.bridge.bars):
            buffer = aggregator.for_symbol(symbol)
            buffer.add_tick(bar.ts, bar.high)
            buffer.add_tick(bar.ts, bar.low)
            buffer.add_tick(bar.ts, bar.close, bar.volume)
