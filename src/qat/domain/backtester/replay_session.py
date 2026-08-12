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
  3. advance the broker, which fills yesterday's orders at today's open.

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
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pandas as pd

from qat.config import Settings
from qat.data.bars import BAR_COLUMNS, Bar, floor_to_interval
from qat.data.broker.simulated_broker import SimulatedBroker
from qat.data.fundamentals import MockFundamentalsSource
from qat.domain.autonomy.executor import AutonomousExecutor
from qat.domain.autonomy.gate import AutonomyGate
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.events import MarketDataEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.strategies.engine import StrategyEngine

_DAILY_SECONDS = 86_400.0
# The executor's retry loop is wall-clock driven and has no meaning in a replay
# that crosses a decade in seconds. Pushed out of the way rather than disabled,
# so the production object is used exactly as it ships.
_INERT_RETRY_SECONDS = 86_400.0


class ReplaySession:
    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        strategies: Sequence[object],
        settings: Settings,
        warm_bars: int = 60,
    ) -> None:
        self.bars = bars
        self.settings = settings
        self.warm_bars = warm_bars
        self.bus = EventBus()
        self.kill_switch = KillSwitch()
        self.cost_model = CostModel.from_settings(settings)
        self.broker = SimulatedBroker(bars=bars, cost_model=self.cost_model)
        self.oms = OMS(
            self.broker,
            RiskEngine(self.bus, self.kill_switch, settings=settings),
            self.kill_switch,
            bus=self.bus,
        )
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
        self._warm_start()

    def _warm_start(self) -> None:
        """Seed both buffers with a prefix, and start the clock after it.

        Without this the first ~50 replayed days are blind - a 50-EMA needs 50
        bars - so the front of every measured period is systematically quiet
        and the quiet is an artefact of the instrument rather than the market.

        `seed` refuses once any bar exists, which is why the prefix cannot
        simply be primed like any other day: seeded history must sit strictly
        before anything live, and that rule is the aggregator's, not this
        module's.
        """
        if self.warm_bars <= 0:
            return
        start = min(self.warm_bars, len(self.broker.session_dates) - 1)
        as_of = self.broker.session_dates[start].to_pydatetime()
        for symbol, frame in self.bars.items():
            prefix = frame.iloc[:start]
            if prefix.empty:
                continue
            seeded = prefix.reset_index()
            seeded = seeded.rename(columns={seeded.columns[0]: "ts"})
            if "volume" not in seeded.columns:
                seeded["volume"] = 0.0
            seeded = seeded[list(BAR_COLUMNS)]
            self.engine.bars.seed(symbol, seeded, now=as_of)
            self.bridge.bars.seed(symbol, seeded, now=as_of)
        # The replayed period begins where the warm prefix ends. A day that has
        # been seeded must not also be primed, or it is counted twice - and a
        # duplicated day silently doubles its weight in every rolling window.
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

        15:00 UTC is inside the US session (13:30-20:00) on the day whose close
        produced the signal. The exact instant does not matter to any decision:
        the fill happens at the NEXT bar's open regardless, which is the rule
        the fill model already commits to.
        """
        return (
            self.broker.current_date.to_pydatetime()
            .replace(hour=15, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
        )

    async def run(self) -> None:
        await self.engine.start()
        await self.bridge.start()
        await self.executor.start()
        try:
            while True:
                await self._one_day()
                if not self.broker.advance():
                    return
        finally:
            await self.executor.stop()
            await self.bridge.stop()
            await self.engine.stop()

    async def _one_day(self) -> None:
        today = self.broker.current_date
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
