"""Bridges SignalEvent (from StrategyEngine, M3) to OMS.submit_order (M6) -
the connector that makes strategy signals actually become pending-signoff
orders. Not itself a spec-named module; a necessary piece the M9 wiring
needs, since nothing else in the system turns a strategy signal into an
order candidate.

Win-rate/win-loss-ratio inputs to sizing are fixed defaults here, not
estimated from real historical trade outcomes - a rolling per-strategy
performance tracker is a natural future addition, not built anywhere in
this codebase yet. The defaults are clearly documented placeholders, not
real edge estimates, and existing_returns is left empty (a documented
simplification - see PortfolioRiskChecker, M6) since this bridge doesn't
maintain historical return series for already-held positions.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

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
    ) -> None:
        self.bus = bus
        self.oms = oms
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
        history = self._history.get(event.symbol)
        if not history or len(history) < _MIN_HISTORY_FOR_SIZING:
            return  # not enough history to size a stop yet

        bars = pd.DataFrame(history)
        price = float(bars["close"].iloc[-1])
        atr_series = compute_atr(bars["high"], bars["low"], bars["close"])
        last_atr = atr_series.iloc[-1]
        atr = 0.0 if pd.isna(last_atr) else float(last_atr)
        if atr <= 0:
            return  # can't size a stop without a valid ATR yet

        returns = bars["close"].pct_change().dropna()
        candidate = OrderCandidate(
            symbol=event.symbol,
            side=event.side,
            price=price,
            atr=atr,
            win_rate=self.default_win_rate,
            win_loss_ratio=self.default_win_loss_ratio,
            candidate_returns=returns,
        )

        account = await self.oms.broker.account()
        positions = await self.oms.broker.positions()
        existing_weights = {pos.symbol: pos.quantity * pos.avg_price for pos in positions}
        existing_returns: dict[str, pd.Series] = {}

        await self.oms.submit_order(
            candidate, account.net_liquidation, existing_weights, existing_returns
        )
