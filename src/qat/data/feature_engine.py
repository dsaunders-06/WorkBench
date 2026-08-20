"""Wires FeatureBuilder to the EventBus: turns MarketDataEvent ticks into
FeatureEvent publications per symbol (spec §D distribution stage).

Ticks are aggregated into real OHLC bars by BarAggregator (M14). Before that
each tick was recorded as a single-point bar with open==high==low==close,
which left every range-based indicator - ATR above all - measuring a
tick-to-tick delta rather than anything traded.
"""

from __future__ import annotations

from datetime import tzinfo

from qat.data.bars import MultiSymbolAggregator
from qat.data.features import FeatureBuilder
from qat.domain.bus import EventBus
from qat.domain.events import FeatureEvent, MarketDataEvent


class FeatureEngine:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "feature-engine"

    def __init__(
        self,
        bus: EventBus,
        builder: FeatureBuilder | None = None,
        max_history: int = 500,
        bar_interval_seconds: float = 60.0,
        # The exchange whose local midnight ends a daily bar (M111). None keeps
        # the epoch anchor, which is what every intraday interval wants.
        bar_tz: tzinfo | None = None,
    ) -> None:
        self.bus = bus
        self.builder = builder or FeatureBuilder()
        self.max_history = max_history
        self.bars = MultiSymbolAggregator(
            interval_seconds=bar_interval_seconds, max_bars=max_history, tz=bar_tz
        )

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        self.bars.add_tick(event.symbol, event.ts, event.price, event.volume)
        bars = self.bars.frame(event.symbol)
        features = self.builder.build(bars)
        await self.bus.publish(FeatureEvent(symbol=event.symbol, features=features, as_of=event.ts))
