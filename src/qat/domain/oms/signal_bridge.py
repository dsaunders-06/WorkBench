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

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd

from qat.config import Settings
from qat.data.bars import MultiSymbolAggregator
from qat.data.broker.adapter import Position
from qat.data.features import compute_atr
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, OrderFilledEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Entry:
    opened_at: datetime
    price: float
    stop_price: float | None


def _trading_days_between(start: datetime, end: datetime) -> int:
    """Weekdays elapsed. An approximation of trading days that ignores market
    holidays - which shortens a ten-day hold by at most a day or two a quarter,
    and is not worth a calendar dependency in a churn rail."""
    if end <= start:
        return 0
    days = 0
    cursor = start.date()
    last = end.date()
    while cursor < last:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


_MIN_HISTORY_FOR_SIZING = 2


def _meta_price(meta: dict[str, object], key: str) -> float | None:
    """Reads a price out of SignalEvent.meta, which is an untyped dict any
    strategy can put anything into - so a missing or non-numeric value is
    treated as absent rather than allowed to raise inside the order path."""
    value = meta.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


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
        bar_interval_seconds: float = 60.0,
    ) -> None:
        self.bus = bus
        self.oms = oms
        self.settings = settings or Settings()
        self.default_win_rate = default_win_rate
        self.default_win_loss_ratio = default_win_loss_ratio
        self.max_history = max_history
        # Real OHLC bars, not one-point-per-tick (M14). This is the most
        # load-bearing of the three aggregators in the app: the ATR computed
        # from these bars sets the stop distance, and the stop distance sets
        # the position size.
        self.bars = MultiSymbolAggregator(
            interval_seconds=bar_interval_seconds, max_bars=max_history
        )
        # Churn control state (M31).
        self._entries: dict[str, _Entry] = {}
        self._entry_times: list[datetime] = []
        self._time_stopped: set[str] = set()
        self._hold_blocked: set[str] = set()

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(SignalEvent, self._on_signal)
        self.bus.subscribe(OrderFilledEvent, self._on_fill)

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(SignalEvent, self._on_signal)
        self.bus.unsubscribe(OrderFilledEvent, self._on_fill)

    async def _on_fill(self, event: OrderFilledEvent) -> None:
        """Remembers when each position was opened, for the churn rails (M31).

        Tracked here rather than read from the broker because a Position
        carries no entry time, and the risk that matters - how long this has
        been held, and how far it has moved against the stop it was sized on -
        cannot be answered without one.
        """
        if event.side == "buy":
            self._entries.setdefault(
                event.symbol,
                _Entry(opened_at=event.ts, price=event.price, stop_price=event.stop_price),
            )
            self._entry_times.append(event.ts)
        else:
            self._entries.pop(event.symbol, None)
            self._time_stopped.discard(event.symbol)

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        self.bars.add_tick(event.symbol, event.ts, event.price, event.volume)
        await self._check_time_stop(event.symbol, event.price, event.ts)

    async def _check_time_stop(self, symbol: str, price: float, now: datetime) -> None:
        """Forces an exit on a thesis that never resolved (M31).

        Checked on the tick rather than from a timer: the bridge already sees
        every tick, and the broker is only asked for positions on the rare
        occasion the stop actually fires.
        """
        if not self.settings.enforce_time_stop:
            return
        entry = self._entries.get(symbol)
        if entry is None or symbol in self._time_stopped:
            return
        if _trading_days_between(entry.opened_at, now) < self.settings.time_stop_trading_days:
            return

        positions = await self.oms.broker.positions()
        held = next((p.quantity for p in positions if p.symbol == symbol), 0.0)
        if held <= 0:
            self._entries.pop(symbol, None)
            return
        self._time_stopped.add(symbol)
        logger.info(
            "TIME STOP on %s after %d trading days - exiting a thesis that never resolved",
            symbol,
            self.settings.time_stop_trading_days,
        )
        await self.oms.submit_exit_order(symbol, quantity=held, price=price)

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

        bars = self.bars.frame(event.symbol)
        if len(bars) < _MIN_HISTORY_FOR_SIZING:
            return  # not enough history to size a stop yet

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

    def _blocked_by_minimum_hold(self, symbol: str, price: float) -> bool:
        """Whether a SIGNAL-driven exit is too early to act on (M31).

        Only signal-driven exits reach here. The resting broker stop, the
        delever sweep and the kill-switch take other paths, so no protective
        exit can be delayed by this.

        The loss escape is what makes the rail defensible: a minimum hold on
        its own would sit through a broken thesis to save $12 of commission,
        and once the position is down min_holding_loss_escape_r the commission
        is small against the risk still on the table.
        """
        if not self.settings.enforce_min_holding_period:
            return False
        entry = self._entries.get(symbol)
        if entry is None:
            return False  # unknown entry: never trap a position we cannot date

        held_days = _trading_days_between(entry.opened_at, datetime.now(UTC))
        if held_days >= self.settings.min_holding_trading_days:
            return False

        if entry.stop_price is not None and entry.stop_price < entry.price:
            risk = entry.price - entry.stop_price
            loss_r = (entry.price - price) / risk
            if loss_r >= self.settings.min_holding_loss_escape_r:
                logger.info(
                    "%s is %.2fR down after %d trading days - the minimum hold does not "
                    "apply to a thesis this far wrong",
                    symbol,
                    loss_r,
                    held_days,
                )
                return False

        if symbol not in self._hold_blocked:
            self._hold_blocked.add(symbol)
            logger.info(
                "Signal exit on %s held back: %d of %d trading days, and not far enough "
                "down to escape the minimum hold",
                symbol,
                held_days,
                self.settings.min_holding_trading_days,
            )
        return True

    async def _handle_sell(self, symbol: str, held: float, price: float) -> None:
        if held > 0 and self._blocked_by_minimum_hold(symbol, price):
            return
        if held > 0:
            # Close exactly what is held rather than letting the entry sizer
            # invent an unrelated quantity.
            await self.oms.submit_exit_order(symbol, quantity=held, price=price)
            return
        if not self.settings.allow_short_selling:
            return  # long-only: nothing to sell, and opening a short is not wanted
        # Shorting is explicitly enabled, so treat this as a new position.
        bars = self.bars.frame(symbol)
        if not bars.empty:
            positions = await self.oms.broker.positions()
            await self._submit_short(symbol, bars, price, positions)

    def _entries_this_week(self, now: datetime) -> int:
        cutoff = now - timedelta(days=7)
        self._entry_times = [ts for ts in self._entry_times if ts >= cutoff]
        return len(self._entry_times)

    async def _submit_entry(
        self, event: SignalEvent, bars: pd.DataFrame, price: float, positions: list[Position]
    ) -> None:
        # Turnover budget (M31). Ten concurrent positions turned over weekly
        # costs 6.2% of a $100k account in commission before a single losing
        # trade; this bounds the rate at which that can happen. Entries only -
        # a budget that blocked exits would be a rail against de-risking.
        taken = self._entries_this_week(datetime.now(UTC))
        if taken >= self.settings.max_entries_per_week:
            logger.info(
                "Turnover budget reached: %d entries in the last seven days, limit %d - "
                "%s not opened",
                taken,
                self.settings.max_entries_per_week,
                event.symbol,
            )
            return
        # A strategy that has done the work of proposing a stop and target
        # (Swing, Breakout) gets those honoured, both for sizing and for the
        # bracket attached at the broker. A strategy that has not falls back to
        # the risk engine's own ATR stop.
        await self._submit_sized(
            event.symbol,
            event.side,
            bars,
            price,
            positions,
            strategy=event.strategy,
            stop_price=_meta_price(event.meta, "stop_price"),
            take_profit_price=_meta_price(event.meta, "target_price"),
        )

    async def _submit_short(
        self,
        symbol: str,
        bars: pd.DataFrame,
        price: float,
        positions: list[Position],
        strategy: str | None = None,
    ) -> None:
        await self._submit_sized(symbol, "sell", bars, price, positions, strategy=strategy)

    async def _submit_sized(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        bars: pd.DataFrame,
        price: float,
        positions: list[Position],
        strategy: str | None = None,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
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
            strategy=strategy,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

        account = await self.oms.broker.account()
        existing_weights = {pos.symbol: pos.quantity * pos.avg_price for pos in positions}
        existing_returns: dict[str, pd.Series] = {}

        await self.oms.submit_order(
            candidate, account.net_liquidation, existing_weights, existing_returns
        )
