"""Seeds every rolling buffer from daily history before the feed starts (M27a).

Until this existed, `StrategyEngine.bars`, `SignalToOrderBridge.bars` and
`RegimeFeatureBuilder` were all populated purely from live ticks, from zero, at
every process start. That is survivable on one-minute bars and fatal on daily
ones: swing's EMA50 would need ten weeks of sessions and the regime HMM about
three months before either could say anything. The decision to run the live
path on daily bars (M27a) is only possible with a warm start.

Registered first with the Orchestrator, which starts engines in order, so this
completes before the market data feed delivers its first tick. That ordering is
load-bearing - `BarAggregator.seed` refuses to run once any bar exists, because
seeded history appended after live bars would corrupt every rolling window
computed from the buffer.

Two things it will not do:

* It never seeds a symbol whose real bars could not be fetched. Both real
  history sources answer a failed request with a seeded random walk, which is
  a reasonable degradation for a screen and an unacceptable one for a buffer
  that positions are sized from.
* It never blocks startup. A warm start that fails leaves the application
  running cold, which is the state every previous milestone ran in, and says
  so loudly.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pandas as pd

from qat.data.bars import MultiSymbolAggregator
from qat.data.history import DEFAULT_BARS, HistoricalBarSource, fetch_daily_panel
from qat.data.macro_fred import MacroDataSource, load_macro_history
from qat.domain.regime_engine.engine import RegimeEngine

logger = logging.getLogger(__name__)


class WarmStart:
    name = "warm-start"

    def __init__(
        self,
        history_source: HistoricalBarSource,
        macro_source: MacroDataSource,
        symbols: Sequence[str],
        benchmark_symbol: str,
        aggregators: Sequence[MultiSymbolAggregator] = (),
        regime_engine: RegimeEngine | None = None,
        macro_series: Sequence[str] = (),
        n_bars: int = DEFAULT_BARS,
    ) -> None:
        self.history_source = history_source
        self.macro_source = macro_source
        self.symbols = list(dict.fromkeys((benchmark_symbol, *symbols)))
        self.benchmark_symbol = benchmark_symbol
        self.aggregators = list(aggregators)
        self.regime_engine = regime_engine
        self.macro_series = list(macro_series)
        self.n_bars = n_bars
        self.seeded_symbols: tuple[str, ...] = ()

    async def start(self) -> None:
        try:
            await self.seed()
        except Exception:  # noqa: BLE001 - a cold start beats no application
            logger.exception(
                "Warm start FAILED - every buffer starts empty, so no strategy can signal "
                "and no regime can be classified until enough live bars accumulate"
            )

    async def stop(self) -> None:
        return None

    async def seed(self) -> None:
        logger.info(
            "Warm start: fetching %d daily bars for %d symbols", self.n_bars, len(self.symbols)
        )
        panel = await fetch_daily_panel(self.history_source, self.symbols, self.n_bars)
        if not panel.frames:
            logger.error(
                "Warm start got no daily bars at all - the application starts cold. Check the "
                "history source and its credentials"
            )
            return

        for symbol, frame in panel.frames.items():
            for aggregator in self.aggregators:
                aggregator.seed(symbol, frame)

        self.seeded_symbols = tuple(panel.frames)
        bar_counts = {symbol: len(frame) for symbol, frame in panel.frames.items()}
        logger.info(
            "Warm start seeded %d symbols across %d buffers with %d-%d daily bars each",
            len(panel.frames),
            len(self.aggregators),
            min(bar_counts.values()),
            max(bar_counts.values()),
        )

        await self._seed_regime(panel.frames)

    async def _seed_regime(self, frames: dict[str, pd.DataFrame]) -> None:
        if self.regime_engine is None:
            return

        benchmark = frames.get(self.benchmark_symbol)
        if benchmark is None:
            logger.error(
                "No daily bars for the benchmark %s - the regime engine starts cold and every "
                "strategy runs on the default regime until it warms up",
                self.benchmark_symbol,
            )
            return

        macro = await load_macro_history(self.macro_source, self.macro_series)
        for series in self.macro_series:
            coverage = macro.coverage(series)
            if coverage is None:
                logger.warning("Macro series %s has no history to seed from", series)
            else:
                logger.info(
                    "Macro %s history: %s to %s",
                    series,
                    coverage[0].date().isoformat(),
                    coverage[1].date().isoformat(),
                )

        breadth = {
            symbol: frame for symbol, frame in frames.items() if symbol != self.benchmark_symbol
        }
        self.regime_engine.seed(benchmark, macro, breadth)
