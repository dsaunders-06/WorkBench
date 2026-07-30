"""Wires strategies to the EventBus: MarketDataEvent (bars) + RegimeEvent
(gating) -> per-symbol FeatureSnapshot -> gated strategies -> SignalEvent.

Defaults to Regime.SIDEWAYS until M5's real regime engine publishes a
RegimeEvent - a conservative, clearly-documented placeholder (Multi-Factor
is unaffected either way since it's active in every regime).

Maintains its own bar aggregator per symbol rather than subscribing to
FeatureEvent, mirroring FeatureEngine's approach (M2) - each engine owns the
state it needs rather than depending on another engine's internals. Ticks
become real OHLC bars via BarAggregator (M14) rather than the single-point
bars used up to M13. The
whole universe's technical features are recomputed on every tick for
simplicity/correctness; this is not optimised for tick throughput or large
universes, which is fine for M3's scope.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Protocol

from qat.data.bars import MultiSymbolAggregator
from qat.data.broker.adapter import Position
from qat.data.features import FeatureBuilder
from qat.data.fundamentals import FundamentalSnapshot, FundamentalsSource
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, RegimeEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, Strategy, SymbolContext

logger = logging.getLogger(__name__)


class PositionSource(Protocol):
    """The slice of BrokerAdapter this engine needs - narrowed deliberately, so
    a strategy engine can never be handed something able to place an order."""

    async def positions(self) -> list[Position]: ...


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
        bar_interval_seconds: float = 60.0,
        position_source: PositionSource | None = None,
        position_cache_seconds: float = 5.0,
    ) -> None:
        self.position_source = position_source
        self.position_cache_seconds = position_cache_seconds
        self._positions_cache: dict[str, float] | None = None
        self._positions_fetched_at = 0.0
        self.bus = bus
        self.strategies = list(strategies)
        self.fundamentals_source = fundamentals_source
        self.feature_builder = feature_builder or FeatureBuilder()
        self.max_history = max_history
        self.bars = MultiSymbolAggregator(
            interval_seconds=bar_interval_seconds, max_bars=max_history
        )
        self._fundamentals_cache: dict[str, FundamentalSnapshot] = {}
        self._context_cache: dict[str, SymbolContext] = {}
        self._current_regime: Regime = default_regime
        self.default_regime = default_regime
        # Whether a real RegimeEvent has ever arrived. Until one has, every
        # gating decision below is made on the default rather than on a reading
        # of the market, and that has to be said out loud exactly once (M27a) -
        # on 29 July a strategy being gated off had to be reconstructed
        # afterwards from a blank field on screen.
        self._regime_is_real = False
        self._warned_about_default = False
        # Whether signals actually leave this engine (M19). SessionController
        # clears it outside market hours; ticks are still recorded so the
        # buffer is warm at the next open. True by default, so an engine built
        # without a controller behaves exactly as it always did.
        self.emitting = True

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(RegimeEvent, self._on_regime)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(RegimeEvent, self._on_regime)

    async def _current_positions(self) -> dict[str, float]:
        """Holdings for the exit path (M14).

        Cached for a short window because this runs per tick and a broker call
        per tick per symbol would dominate everything else. The staleness that
        buys is acceptable *here* specifically because nothing in this path
        places an order - a slightly stale holding can only produce a signal,
        and the bridge, risk engine and OMS all re-read real positions before
        anything reaches a broker.

        Returns empty on failure rather than raising: no positions reads as
        "nothing held", which suppresses exits. That is the safe direction for
        a signal-generation path, and the mechanical protection that must not
        depend on this is the resting broker stop, not a strategy signal.
        """
        if self.position_source is None:
            return {}

        now = time.monotonic()
        if (
            self._positions_cache is not None
            and now - self._positions_fetched_at < self.position_cache_seconds
        ):
            return self._positions_cache

        try:
            positions = await self.position_source.positions()
        except Exception:  # noqa: BLE001 - a broker blip must not stop signals
            logger.warning("Could not read positions for the exit path", exc_info=True)
            return self._positions_cache or {}

        self._positions_cache = {pos.symbol: float(pos.quantity) for pos in positions}
        self._positions_fetched_at = now
        return self._positions_cache

    async def _on_regime(self, event: RegimeEvent) -> None:
        try:
            self._current_regime = Regime(event.label)
        except ValueError:
            return  # unrecognised label: keep the previous regime rather than guess
        if not self._regime_is_real:
            logger.info(
                "Strategy gating now uses the classified regime (%s), not the %s default",
                self._current_regime.value,
                self.default_regime.value,
            )
        self._regime_is_real = True

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        # History is recorded even while suspended (M19): the first signal
        # after an open must be computed against a populated buffer, not an
        # empty one.
        self.bars.add_tick(event.symbol, event.ts, event.price, event.volume)

        if not self.emitting:
            return

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
        bars = self.bars.frame(event.symbol)
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
            positions=await self._current_positions(),
        )

        if not self._regime_is_real and not self._warned_about_default:
            self._warned_about_default = True
            logger.warning(
                "Gating %d strategies on the %s DEFAULT - the regime engine has published "
                "nothing. Strategies are being permitted or refused without any reading of "
                "the market: %s",
                len(self.strategies),
                self.default_regime.value,
                ", ".join(
                    f"{s.name}="
                    f"{'eligible' if self._current_regime in s.suitable_regimes() else 'skipped'}"
                    for s in self.strategies
                ),
            )

        for strategy in self.strategies:
            if self._current_regime not in strategy.suitable_regimes():
                continue
            for signal in strategy.on_features(snapshot):
                await self.bus.publish(signal)
