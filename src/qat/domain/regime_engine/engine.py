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

Everything this engine decides is logged, because the label it publishes
gates which strategies may trade at all. Until M27a it had no logger of any
kind, so its only visible traces were hmmlearn's own warnings and whatever
the bus caught when it crashed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
import pandas as pd

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.regime import Regime
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES, RegimeFeatureBuilder
from qat.domain.regime_engine.fusion import HysteresisGate, RegimeFusion, exposure_scalar_for
from qat.domain.regime_engine.hmm_core import HMMRegimeModel

logger = logging.getLogger(__name__)

_SMA_WINDOW = 200
_VIX_COL = 2
_YIELD_CURVE_COL = 3

# How often to say "still warming up" while below min_fit_bars. Every bar
# would be noise; never saying it is how a blank regime field on screen came
# to be indistinguishable from a dead classifier.
_WARMUP_LOG_EVERY_BARS = 20


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
        self._last_label: str | None = None

    async def start(self) -> None:
        logger.info(
            "Regime engine starting: benchmark=%s, %d breadth symbols, %d states, "
            "min_fit_bars=%d, refit every %d bars",
            self.benchmark_symbol,
            len(self.breadth_symbols),
            self._hmm.n_states,
            self.min_fit_bars,
            self.refit_interval_bars,
        )
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
            if len(matrix) % _WARMUP_LOG_EVERY_BARS == 0:
                logger.info(
                    "Regime engine warming up: %d/%d bars, no regime published yet",
                    len(matrix),
                    self.min_fit_bars,
                )
            return

        if not self._hmm.is_fitted or self._bars_since_fit >= self.refit_interval_bars:
            if not self._fit(matrix):
                return
            self._bars_since_fit = 0

        try:
            posterior = self._hmm.predict_proba(matrix)[-1].tolist()
        except Exception:  # noqa: BLE001 - diagnose, then stay quiet rather than classify
            logger.exception(
                "Regime posterior failed on a %dx%d matrix - no regime published this bar",
                *matrix.shape,
            )
            return

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
        scalar = exposure_scalar_for(label)

        self._prev_yield_curve_slope = yield_curve_slope
        self._prev_sma_200 = sma_200

        self._log_classification(label.value, probs, scalar, vix_level, yield_curve_slope)
        self._last_label = label.value

        await self.bus.publish(
            RegimeEvent(
                label=label.value,
                probs={regime.value: prob for regime, prob in probs.items()},
                exposure_scalar=scalar,
                ts=event.ts,
            )
        )

    def _fit(self, matrix: np.ndarray) -> bool:
        """Refit, reporting a failure with the numbers that explain it.

        A singular covariance matrix is the failure this engine actually
        produces (28 July: `startprob_ must sum to 1 (got nan)`), and its cause
        is a feature column that does not move across the fitted window -
        macro columns held constant because the bars are far shorter than the
        daily cadence those series update on. Naming those columns turns an
        hmmlearn traceback into a diagnosis.

        Movement is measured as max - min, not as standard deviation. A column
        of identical values has a peak-to-peak range of exactly zero whatever
        the value is, where its computed standard deviation is only exactly
        zero when the value happens to be representable in binary: sixty
        copies of 14.0 give a standard deviation of 0.0, sixty copies of a real
        VIX print of 18.21 give 3.5e-15. A test written against 14.0 passes
        while the live path silently reports nothing wrong.
        """
        ranges = matrix.max(axis=0) - matrix.min(axis=0)
        flat = [name for name, spread in zip(FEATURE_NAMES, ranges, strict=True) if spread == 0.0]
        if flat:
            logger.warning(
                "Regime features that never moved across %d bars: %s. A constant column makes "
                "the covariance matrix singular and can stop the fit converging",
                len(matrix),
                ", ".join(flat),
            )

        logger.info("Refitting the regime HMM on %d bars x %d features", *matrix.shape)
        try:
            self._hmm.fit(matrix)
        except Exception:  # noqa: BLE001 - a dead classifier must be legible, not a traceback
            logger.exception(
                "Regime HMM fit FAILED on %d bars - no regime will be published until a later "
                "fit succeeds. Per-feature range: %s",
                len(matrix),
                ", ".join(
                    f"{name}={spread:.6g}"
                    for name, spread in zip(FEATURE_NAMES, ranges, strict=True)
                ),
            )
            return False
        return True

    def _log_classification(
        self,
        label: str,
        probs: dict[Regime, float],
        scalar: float,
        vix_level: float,
        yield_curve_slope: float,
    ) -> None:
        """Every classification, and transitions loudly.

        A regime is a gate, not a display: strategies whose suitable_regimes()
        excludes the current label are skipped entirely, so a transition can
        switch a promoted strategy off for a whole session. That happened on
        29 July and had to be reconstructed afterwards from a blank UI field.
        """
        ranked = ", ".join(
            f"{regime.value}={prob:.2f}"
            for regime, prob in sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        )
        if label != self._last_label:
            logger.info(
                "REGIME %s -> %s (exposure scalar %.2f). Strategies whose suitable regimes "
                "exclude %s are now skipped. Top probabilities: %s. VIX=%.2f, curve=%.2f",
                self._last_label or "none",
                label,
                scalar,
                label,
                ranked,
                vix_level,
                yield_curve_slope,
            )
        else:
            logger.debug(
                "Regime %s holds (scalar %.2f). Top probabilities: %s", label, scalar, ranked
            )

    def _current_sma(self) -> float:
        if len(self._benchmark_closes) < _SMA_WINDOW:
            return 0.0  # not enough history - bull-block rule is a no-op (sma_200 <= 0 check)
        return float(pd.Series(self._benchmark_closes[-_SMA_WINDOW:]).mean())
