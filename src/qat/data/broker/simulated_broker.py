"""A BrokerAdapter backed by historical bars and a simulated clock (W2).

The point of this class is that the production trading path can be replayed
over history WITHOUT a second copy of the rules. `MockBroker` invents prices
from a seeded RNG and fills instantly; this one serves real bars, fills on the
next bar's open, and executes protective orders against a bar's high and low.

The guard with no equivalent in any real adapter is `get_historical`: a
simulator holds the whole series in memory and must refuse to answer beyond the
simulated date. Nothing else prevents the strategy being handed bars that had
not happened yet, and the resulting backtest would look entirely plausible.

Bars arrive NORMALISED - lowercase open/high/low/close on a DatetimeIndex.
Accepting either capitalisation would be accepting the wrong one silently.

Slippage moves the fill price; commission does not appear here. Commission
reaches the record through the ledger and the cost model, exactly as it does
with a real broker, and charging it in both places would make every backtest
quietly worse than reality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import pandas as pd

from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerFill,
    Order,
    Position,
    RestingStopOrder,
)
from qat.domain.backtester.costs import CostModel
from qat.domain.corporate_actions.announcements import Announcement

_REQUIRED_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class OpeningPosition:
    """A holding that existed BEFORE the replayed window began (W2).

    G1 replays a window of the live record, and the record's dominant refusal
    is `already at the 10-position limit (10 held or pending)` - 2,511 of 2,886
    rows. That rail is a consequence of the book the window OPENED with, not of
    anything the window itself decided, so a replay starting flat cannot
    reproduce it.

    `stop_price` is optional and means what it says. A position restored
    without its stop counts its FULL value against the aggregate cap, so
    inventing protection that was not there would understate risk exactly where
    the live book was most exposed.
    """

    quantity: float
    avg_price: float
    stop_price: float | None = None


class SimulatedBroker:
    name = "simulated-broker"

    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        cost_model: CostModel,
        starting_cash: float = 100_000.0,
    ) -> None:
        for symbol, frame in bars.items():
            missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
            if missing:
                raise ValueError(
                    f"{symbol} bars are missing {missing}. SimulatedBroker requires normalised "
                    "lowercase open/high/low/close - normalising is the caller's job, because a "
                    "fake that accepts either shape accepts the wrong one silently."
                )
        self._bars = bars
        self.cost_model = cost_model
        self._cash = starting_cash

        every_date: set[pd.Timestamp] = set()
        for frame in bars.values():
            every_date.update(frame.index)
        self.session_dates: list[pd.Timestamp] = sorted(every_date)
        self._index = 0

        self._orders: dict[str, Order] = {}
        self._pending: list[Order] = []
        self._positions: dict[str, Position] = {}
        self._resting_stops: dict[str, float | None] = {}
        self._resting_targets: dict[str, float | None] = {}
        self._broker_fills: list[BrokerFill] = []
        self._announcements: list[Announcement] = []

    def adopt_opening_book(self, positions: dict[str, OpeningPosition]) -> None:
        """Install holdings that predate the window, as the broker would report
        them to `adopt_broker_positions` on a live restart.

        Placed directly rather than filled, because these were not bought
        during the replay: giving them fills would put trades into the record
        that never happened in the window being reproduced.
        """
        for symbol, opening in positions.items():
            self._positions[symbol] = Position(
                symbol=symbol, quantity=opening.quantity, avg_price=opening.avg_price
            )
            if opening.stop_price is not None:
                self._resting_stops[symbol] = opening.stop_price

    # --- the clock ----------------------------------------------------------

    @property
    def current_date(self) -> pd.Timestamp:
        return self.session_dates[self._index]

    def advance(self) -> bool:
        """Move to the next trading day. False when the series is exhausted.

        The ONLY thing that causes a fill. A test that expects an order to have
        filled without advancing is expecting a broker that trades on a bar
        that has not happened.
        """
        if self._index + 1 >= len(self.session_dates):
            return False
        self._index += 1
        # Entries first: an order filling at today's open exists for the rest of
        # today, so its protective legs are live on this bar.
        self._fill_pending_entries()
        self._fill_protective_orders()
        return True

    def _bar(self, symbol: str) -> pd.Series | None:
        frame = self._bars.get(symbol)
        if frame is None:
            return None
        row = frame[frame.index <= self.current_date]
        if row.empty:
            return None
        return row.iloc[-1]

    def _now(self) -> datetime:
        return self.current_date.to_pydatetime().replace(tzinfo=UTC)

    # --- reads --------------------------------------------------------------

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        bar = self._bar(symbol)
        if bar is None:
            return {}
        price = float(bar["close"])
        return {"bid": price, "ask": price, "last": price}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        """Bars up to AND INCLUDING the simulated date, never beyond it."""
        frame = self._bars.get(symbol)
        if frame is None:
            return []
        visible = frame[frame.index <= self.current_date]
        if visible.empty:
            return []
        window = visible.iloc[-bars:] if bars > 0 else visible
        return [
            {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for _, row in window.iterrows()
        ]

    async def positions(self) -> list[Position]:
        return list(self._positions.values())

    async def account(self) -> AccountSummary:
        market_value = 0.0
        for position in self._positions.values():
            bar = self._bar(position.symbol)
            if bar is not None:
                market_value += position.quantity * float(bar["close"])
        net_liq = self._cash + market_value
        return AccountSummary(net_liquidation=net_liq, cash=self._cash, buying_power=self._cash)

    async def balances(self) -> AccountBalances:
        summary = await self.account()
        return AccountBalances(
            equity=summary.net_liquidation,
            cash=summary.cash,
            buying_power=summary.buying_power,
            long_market_value=summary.net_liquidation - summary.cash,
            short_market_value=0.0,
            currency="USD",
            status="SIMULATED",
        )

    async def resting_stops(self) -> dict[str, float]:
        return {s: v for s, v in self._resting_stops.items() if v is not None}

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        orders: dict[str, RestingStopOrder] = {}
        for symbol, stop in self._resting_stops.items():
            if stop is None:
                continue
            position = self._positions.get(symbol)
            orders[symbol] = RestingStopOrder(
                symbol=symbol,
                order_id=f"resting-stop-{symbol}",
                stop_price=stop,
                quantity=abs(position.quantity) if position else 0.0,
            )
        return orders

    async def recent_fills(
        self, since: datetime, symbols: list[str] | None = None
    ) -> list[BrokerFill]:
        wanted = set(symbols) if symbols is not None else None
        return [
            f
            for f in self._broker_fills
            if f.filled_at > since and (wanted is None or f.symbol in wanted)
        ]

    async def announcements(self, symbol: str, since: date, until: date) -> list[Announcement]:
        return [
            a for a in self._announcements if a.symbol == symbol and since <= a.ex_date <= until
        ]

    def queue_announcement(self, announcement: Announcement) -> None:
        """Test seam, as MockBroker's is. A corporate action cannot be derived
        from a price series."""
        self._announcements.append(announcement)

    # --- writes -------------------------------------------------------------

    async def place_order(self, order: Order) -> Order:
        """Queued, never filled here. A market order placed against a closed
        bar reaches the market at the next open, and the app's own sizing was
        computed from that closed bar - so filling now would hand the strategy
        a price it could not have traded at.

        THE BROKER KEEPS ITS OWN COPY, and returns another. It used to store and
        return the caller's object, so a later `filled_price` set here mutated
        the OMS's order too - and no real adapter can do that, because Alpaca
        builds a fresh object out of its JSON response and the app learns about
        a fill by asking.

        That sharing silently defeated M70. `_correct_announced_price` asks
        whether what the broker charged differs from what was ANNOUNCED at
        sign-off, and the announced price it reads is `order.filled_price or
        order.reference_price`. With one shared object the fill price wrote
        itself into that field before the comparison ran, the difference was
        always zero, and every replayed entry kept the signal bar's close.
        """
        stored = replace(order)
        self._orders[order.order_id] = stored
        if stored.is_protective_stop:
            stored.status = "transmitted"
            self._resting_stops[stored.symbol] = stored.stop_price
            if stored.take_profit_price is not None:
                self._resting_targets[stored.symbol] = stored.take_profit_price
            return replace(stored)
        stored.status = "transmitted"
        self._pending.append(stored)
        # A snapshot of this instant, exactly as an adapter's response is.
        return replace(stored)

    def _fill_pending_entries(self) -> None:
        still_pending: list[Order] = []
        for order in self._pending:
            bar = self._bar(order.symbol)
            if bar is None or bar.name != self.current_date:
                # No bar for this symbol today - the order waits rather than
                # filling at a stale price from an earlier session.
                still_pending.append(order)
                continue
            fill_price = self._slipped(float(bar["open"]), order.side)
            order.status = "filled"
            order.filled_price = fill_price
            # Reported through `recent_fills` like any other execution, because
            # that is what the adapter this stands in for does. `AlpacaAdapter`
            # returns every filled order in the window, its own included - which
            # is why `absorb_broker_fills` has a branch for a fill that is OURS
            # and calls `_correct_announced_price` on it (M70).
            #
            # Recording only protective fills here left that branch dead in the
            # harness, so every replayed entry kept the price it was ANNOUNCED
            # at - the signal bar's close, published at sign-off before this
            # order had filled - rather than the next bar's open the simulator
            # actually charged. The fill model's central decision was invisible
            # in every recorded trade, and expectancy was computed against a
            # basis nobody paid.
            self._broker_fills.append(
                BrokerFill(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=fill_price,
                    filled_at=self._now(),
                )
            )
            self._apply_fill(order, fill_price)
            if order.is_bracket and order.side == "buy":
                self._resting_stops[order.symbol] = order.stop_price
                self._resting_targets[order.symbol] = order.take_profit_price
            elif order.side == "sell":
                self._resting_stops.pop(order.symbol, None)
                self._resting_targets.pop(order.symbol, None)
        self._pending = still_pending

    def _fill_protective_orders(self) -> None:
        """Resting legs against today's bar.

        The stop is evaluated FIRST and wins any bar that touches both levels.
        A daily bar cannot say which came first, and assuming the unfavourable
        one makes every expectancy figure a floor rather than an estimate.
        """
        for symbol in list(self._positions):
            position = self._positions.get(symbol)
            if position is None or position.quantity <= 0:
                continue
            bar = self._bar(symbol)
            if bar is None or bar.name != self.current_date:
                continue
            stop = self._resting_stops.get(symbol)
            target = self._resting_targets.get(symbol)
            low, high, open_ = float(bar["low"]), float(bar["high"]), float(bar["open"])

            if stop is not None and low <= stop:
                # A bar that OPENS through the stop fills at the open, which is
                # worse. Filling at the trigger would hide the loss shape a
                # split and a gap both produce.
                self._execute_protective(symbol, open_ if open_ <= stop else stop)
                continue
            if target is not None and high >= target:
                # The target, never the better gapped-up open - the same
                # never-flatter rule pointed the other way.
                self._execute_protective(symbol, target)

    def _execute_protective(self, symbol: str, price: float) -> None:
        position = self._positions.get(symbol)
        if position is None or position.quantity <= 0:
            return
        quantity = position.quantity
        self._broker_fills.append(
            BrokerFill(
                order_id=f"sim-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="sell",
                quantity=quantity,
                price=price,
                filled_at=self._now(),
            )
        )
        self._positions.pop(symbol, None)
        self._resting_stops.pop(symbol, None)
        self._resting_targets.pop(symbol, None)
        self._cash += quantity * price

    def _slipped(self, price: float, side: str) -> float:
        """Slippage always moves the fill AGAINST the order."""
        drift = price * (self.cost_model.slippage_bps / 10_000.0)
        return price + drift if side == "buy" else price - drift

    def _apply_fill(self, order: Order, fill_price: float) -> None:
        signed_qty = order.quantity if order.side == "buy" else -order.quantity
        self._cash -= signed_qty * fill_price
        existing = self._positions.get(order.symbol)
        if existing is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol, quantity=signed_qty, avg_price=fill_price
            )
            return
        new_qty = existing.quantity + signed_qty
        if abs(new_qty) < 1e-9:
            self._positions.pop(order.symbol, None)
            return
        self._positions[order.symbol] = Position(
            symbol=order.symbol, quantity=new_qty, avg_price=fill_price
        )

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        order = self._orders[order_id]
        for key, value in changes.items():
            setattr(order, key, value)
        if order.is_protective_stop and order.stop_price is not None:
            self._resting_stops[order.symbol] = order.stop_price
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        order.status = "cancelled"
        self._pending = [p for p in self._pending if p.order_id != order_id]
        if order.is_protective_stop:
            self._resting_stops.pop(order.symbol, None)
        return order


def new_simulated_order_id() -> str:
    return uuid.uuid4().hex
