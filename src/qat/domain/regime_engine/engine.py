"""Wires the regime engine to the EventBus (spec §E): MarketDataEvent
(benchmark symbol + optional breadth-universe symbols) and MacroEvent
(VIX/yield-curve/credit-spread) -> periodic HMM refit -> fusion + hysteresis
-> RegimeEvent.

Refits the HMM every refit_interval_bars bars rather than on every tick -
refitting per-tick would be wasteful and the regime doesn't need
tick-level responsiveness. The posterior is computed from the *full*
accumulated feature sequence each time (not just the latest row) so the
model's transition dynamics actually inform the current-state estimate -
a single isolated observation would defeat the point of a Markov model.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.regime_engine.feature_matrix import RegimeFeatureBuilder
from qat.domain.regime_engine.fusion import HysteresisGate, RegimeFusion, exposure_scalar_for
from qat.domain.regime_engine.hmm_core import HMMRegimeModel

_SMA_WINDOW = 200
_VIX_COL = 2
_YIELD_CURVE_COL = 3


class RegimeEngine:
    name = "regime-engine"

    def __init__(
        self,
        bus: EventBus,
        benchmark_symbol: str,
        breadth_symbols: Sequence[str] = (),
        n_states: int = 4,
        refit_interval_bars: int = 20,
        min_fit_bars: int = 60,
    ) -> None:
        self.bus = bus
        self.benchmark_symbol = benchmark_symbol
        self.breadth_symbols = set(breadth_symbols)
        self.refit_interval_bars = refit_interval_bars
        self.min_fit_bars = min_fit_bars

        self._feature_builder = RegimeFeatureBuilder()
        self._hmm = HMMRegimeModel(n_states=n_states)
        self._fusion = RegimeFusion()
        self._hysteresis = HysteresisGate()

        self._benchmark_closes: list[float] = []
        self._breadth_latest: dict[str, float] = {}
        self._bars_since_fit = 0
        self._prev_yield_curve_slope = 0.0
        self._prev_sma_200 = 0.0

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(MacroEvent, self._on_macro)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(MacroEvent, self._on_macro)

    async def _on_macro(self, event: MacroEvent) -> None:
        self._feature_builder.update_macro(event.series, event.value)

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        if event.symbol in self.breadth_symbols:
            self._breadth_latest[event.symbol] = event.price
        if event.symbol != self.benchmark_symbol:
            return

        self._benchmark_closes.append(event.price)
        breadth_snapshot = dict(self._breadth_latest) if self._breadth_latest else None
        self._feature_builder.add_benchmark_bar(event.price, breadth_snapshot)
        self._bars_since_fit += 1

        matrix = self._feature_builder.feature_matrix()
        if len(matrix) < self.min_fit_bars:
            return

        if not self._hmm.is_fitted or self._bars_since_fit >= self.refit_interval_bars:
            self._hmm.fit(matrix)
            self._bars_since_fit = 0

        posterior = self._hmm.predict_proba(matrix)[-1].tolist()
        latest_row = matrix[-1]
        vix_level = float(latest_row[_VIX_COL])
        yield_curve_slope = float(latest_row[_YIELD_CURVE_COL])
        sma_200 = self._current_sma()

        probs = self._fusion.compute(
            posterior=posterior,
            signatures=self._hmm.state_signatures,
            yield_curve_slope=yield_curve_slope,
            yield_curve_slope_prev=self._prev_yield_curve_slope,
            vix_level=vix_level,
            price=event.price,
            sma_200=sma_200,
            sma_200_prev=self._prev_sma_200,
        )
        label = self._hysteresis.update(probs)

        self._prev_yield_curve_slope = yield_curve_slope
        self._prev_sma_200 = sma_200

        await self.bus.publish(
            RegimeEvent(
                label=label.value,
                probs={regime.value: prob for regime, prob in probs.items()},
                exposure_scalar=exposure_scalar_for(label),
                ts=event.ts,
            )
        )

    def _current_sma(self) -> float:
        if len(self._benchmark_closes) < _SMA_WINDOW:
            return 0.0  # not enough history - bull-block rule is a no-op (sma_200 <= 0 check)
        return float(pd.Series(self._benchmark_closes[-_SMA_WINDOW:]).mean())
