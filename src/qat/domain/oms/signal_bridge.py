"""Bridges SignalEvent (from StrategyEngine, M3) to OMS.submit_order (M6) -
the connector that makes strategy signals actually become pending-signoff
orders. Not itself a spec-named module; a necessary piece the M9 wiring
needs, since nothing else in the system turns a strategy signal into an
order candidate.

This is where signal->order *policy* lives, deliberately kept out of OMS
(which stays a pure mechanism: "submit this order"). Two rules matter most,
both added in M11 after a deployed strategy produced ~75k blotter rows:

* Idempotence. Strategies re-emit a signal on every tick for as long as the
  condition holds, so an unguarded bridge queues a duplicate order per tick.
  A symbol with an order already awaiting sign-off, or already holding the
  position the signal is asking for, produces nothing further.
* Long-only by default. A "sell" closes an existing holding (sized to what is
  actually held, via OMS.submit_exit_order) and is otherwise dropped, rather
  than opening a short in a symbol the account never owned. Set
  allow_short_selling to opt into the old behaviour.

Win-rate/win-loss-ratio inputs to sizing are fixed defaults here, not
estimated from real historical trade outcomes - a rolling per-strategy
performance tracker is a natural future addition, not built anywhere in
this codebase yet. The defaults are clearly documented placeholders, not
real edge estimates, and existing_returns is left empty (a documented
simplification - see PortfolioRiskChecker, M6) since this bridge doesn't
maintain historical return series for already-held positions.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.features import compute_atr
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate

_MIN_HISTORY_FOR_SIZING = 2


class SignalToOrderBridge:
    name = "signal-to-order-bridge"

    def __init__(
        self,
        bus: EventBus,
        oms: OMS,
        default_win_rate: float = 0.55,
        default_win_loss_ratio: float = 1.5,
        max_history: int = 250,
        settings: Settings | None = None,
    ) -> None:
        self.bus = bus
        self.oms = oms
        self.settings = settings or Settings()
        self.default_win_rate = default_win_rate
        self.default_win_loss_ratio = default_win_loss_ratio
        self.max_history = max_history
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(SignalEvent, self._on_signal)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(SignalEvent, self._on_signal)

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

    async def _on_signal(self, event: SignalEvent) -> None:
        # A strategy re-emits its signal on EVERY tick for as long as its
        # condition holds - a signal is a state, not a one-off instruction. So
        # this must be idempotent: the same signal arriving repeatedly has to
        # produce at most one order, or the blotter fills with duplicates.
        #
        # The pending check is local and free, so it goes first: once a symbol
        # has something awaiting sign-off, subsequent ticks cost nothing and
        # never hit the broker.
        if event.symbol in self.oms.pending_signoff_symbols():
            return

        history = self._history.get(event.symbol)
        if not history or len(history) < _MIN_HISTORY_FOR_SIZING:
            return  # not enough history to size a stop yet

        bars = pd.DataFrame(history)
        price = float(bars["close"].iloc[-1])

        positions = await self.oms.broker.positions()
        held = next(
            (pos.quantity for pos in positions if pos.symbol == event.symbol),
            0.0,
        )

        if event.side == "sell":
            await self._handle_sell(event.symbol, held, price)
            return

        if held > 0:
            return  # already long - re-signalling must not pyramid the position

        await self._submit_entry(event, bars, price, positions)

    async def _handle_sell(self, symbol: str, held: float, price: float) -> None:
        if held > 0:
            # Close exactly what is held rather than letting the entry sizer
            # invent an unrelated quantity.
            await self.oms.submit_exit_order(symbol, quantity=held, price=price)
            return
        if not self.settings.allow_short_selling:
            return  # long-only: nothing to sell, and opening a short is not wanted
        # Shorting is explicitly enabled, so treat this as a new position.
        history = self._history.get(symbol)
        if history:
            positions = await self.oms.broker.positions()
            await self._submit_short(symbol, pd.DataFrame(history), price, positions)

    async def _submit_entry(
        self, event: SignalEvent, bars: pd.DataFrame, price: float, positions: list[Position]
    ) -> None:
        await self._submit_sized(event.symbol, event.side, bars, price, positions)

    async def _submit_short(
        self, symbol: str, bars: pd.DataFrame, price: float, positions: list[Position]
    ) -> None:
        await self._submit_sized(symbol, "sell", bars, price, positions)

    async def _submit_sized(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        bars: pd.DataFrame,
        price: float,
        positions: list[Position],
    ) -> None:
        atr_series = compute_atr(bars["high"], bars["low"], bars["close"])
        last_atr = atr_series.iloc[-1]
        atr = 0.0 if pd.isna(last_atr) else float(last_atr)
        if atr <= 0:
            return  # can't size a stop without a valid ATR yet

        candidate = OrderCandidate(
            symbol=symbol,
            side=side,
            price=price,
            atr=atr,
            win_rate=self.default_win_rate,
            win_loss_ratio=self.default_win_loss_ratio,
            candidate_returns=bars["close"].pct_change().dropna(),
        )

        account = await self.oms.broker.account()
        existing_weights = {pos.symbol: pos.quantity * pos.avg_price for pos in positions}
        existing_returns: dict[str, pd.Series] = {}

        await self.oms.submit_order(
            candidate, account.net_liquidation, existing_weights, existing_returns
        )
