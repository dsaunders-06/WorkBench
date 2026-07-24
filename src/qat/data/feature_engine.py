"""Wires FeatureBuilder to the EventBus: turns MarketDataEvent ticks into
FeatureEvent publications per symbol (spec §D distribution stage).

Ticks are treated as single-point bars (open=high=low=close=price) - a
deliberate simplification for M2. A dedicated OHLC bar aggregator over ticks
is a natural addition once a strategy needs real intrabar structure.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from qat.data.features import FeatureBuilder
from qat.domain.bus import EventBus
from qat.domain.events import FeatureEvent, MarketDataEvent


class FeatureEngine:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "feature-engine"

    def __init__(
        self, bus: EventBus, builder: FeatureBuilder | None = None, max_history: int = 500
    ) -> None:
        self.bus = bus
        self.builder = builder or FeatureBuilder()
        self.max_history = max_history
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)

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

        bars = pd.DataFrame(history)
        features = self.builder.build(bars)
        await self.bus.publish(FeatureEvent(symbol=event.symbol, features=features, as_of=event.ts))
