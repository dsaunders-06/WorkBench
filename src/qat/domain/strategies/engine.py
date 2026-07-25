"""Wires strategies to the EventBus: MarketDataEvent (bars) + RegimeEvent
(gating) -> per-symbol FeatureSnapshot -> gated strategies -> SignalEvent.

Defaults to Regime.SIDEWAYS until M5's real regime engine publishes a
RegimeEvent - a conservative, clearly-documented placeholder (Multi-Factor
is unaffected either way since it's active in every regime).

Maintains its own tick-history buffer per symbol rather than subscribing to
FeatureEvent, mirroring FeatureEngine's approach (M2) - each engine owns the
state it needs rather than depending on another engine's internals. The
whole universe's technical features are recomputed on every tick for
simplicity/correctness; this is not optimised for tick throughput or large
universes, which is fine for M3's scope.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from qat.data.features import FeatureBuilder
from qat.data.fundamentals import FundamentalSnapshot, FundamentalsSource
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, RegimeEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, Strategy, SymbolContext


class StrategyEngine:
    name = "strategy-engine"

    def __init__(
        self,
        bus: EventBus,
        strategies: Sequence[Strategy],
        fundamentals_source: FundamentalsSource,
        feature_builder: FeatureBuilder | None = None,
        max_history: int = 500,
        default_regime: Regime = Regime.SIDEWAYS,
    ) -> None:
        self.bus = bus
        self.strategies = list(strategies)
        self.fundamentals_source = fundamentals_source
        self.feature_builder = feature_builder or FeatureBuilder()
        self.max_history = max_history
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._fundamentals_cache: dict[str, FundamentalSnapshot] = {}
        self._context_cache: dict[str, SymbolContext] = {}
        self._current_regime: Regime = default_regime

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(RegimeEvent, self._on_regime)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(RegimeEvent, self._on_regime)

    async def _on_regime(self, event: RegimeEvent) -> None:
        try:
            self._current_regime = Regime(event.label)
        except ValueError:
            pass  # unrecognised label: keep the previous regime rather than guess

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        history = self._history.setdefault(event.symbol, [])
        history.append(
            {
                "ts": event.ts,
                "open": event.price,
                "high": event.price,
                "low": event.price,
                "close": event.price,
                "volume": event.volume,
            }
        )
        if len(history) > self.max_history:
            del history[: len(history) - self.max_history]

        if not self.strategies:
            # Nothing is deployed, so no snapshot is needed - skip the whole
            # feature rebuild rather than doing it for every tick and throwing
            # it away. History above is still recorded, so deploying a
            # strategy later starts from a populated buffer.
            return

        if event.symbol not in self._fundamentals_cache:
            self._fundamentals_cache[event.symbol] = (
                await self.fundamentals_source.get_fundamentals(event.symbol)
            )

        # Only the ticked symbol's bars changed, so only its context needs
        # rebuilding; every peer's cached context is still current. Rebuilding
        # the whole universe per tick made this O(n^2) work per second.
        fundamentals = self._fundamentals_cache.get(event.symbol)
        if fundamentals is None:
            return
        bars = pd.DataFrame(self._history[event.symbol])
        self._context_cache[event.symbol] = SymbolContext(
            symbol=event.symbol,
            bars=bars,
            technical=self.feature_builder.build(bars),
            fundamentals=fundamentals,
        )

        universe = self._context_cache
        snapshot = FeatureSnapshot(
            symbol=event.symbol,
            as_of=event.ts,
            context=universe[event.symbol],
            universe=universe,
        )

        for strategy in self.strategies:
            if self._current_regime not in strategy.suitable_regimes():
                continue
            for signal in strategy.on_features(snapshot):
                await self.bus.publish(signal)
