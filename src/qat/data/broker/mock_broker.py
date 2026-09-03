"""Deterministic in-memory broker for tests and M1 smoke runs.

Seeded so a given seed always produces the same synthetic fills - required
for reproducible tests and, later, reproducible backtests/paper sessions.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime

from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerFill,
    Order,
    Position,
    RestingOrder,
    RestingStopOrder,
)
from qat.domain.corporate_actions.announcements import Announcement

_STARTING_CASH = 100_000.0
_SYNTHETIC_BASE_PRICE = 100.0


class MockBroker:
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic fills, not crypto
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._resting_stops: dict[str, float | None] = {}
        self._resting_targets: dict[str, float | None] = {}
        self._broker_fills: list[BrokerFill] = []
        # Empty by default and only ever filled by `queue_announcement` (M39). A
        # mock that invented corporate actions from its price series would make
        # every other test in the suite non-deterministic.
        self._announcements: list[Announcement] = []
        self._cash = _STARTING_CASH

    def queue_announcement(self, announcement: Announcement) -> None:
        """Test seam. A corporate action cannot be derived from a price series,
        so it is placed here explicitly."""
        self._announcements.append(announcement)

    async def announcements(self, symbol: str, since: date, until: date) -> list[Announcement]:
        """Bounded on `ex_date`, which is the date the detector keys on. Bounding
        on `payable_date` would be wrong for the same reason keying on it is:
        CRWD's precedes its ex-date."""
        return [
            a for a in self._announcements if a.symbol == symbol and since <= a.ex_date <= until
        ]

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        price = self._synthetic_price(symbol)
        return {"bid": price - 0.01, "ask": price + 0.01, "last": price}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        price = self._synthetic_price(symbol)
        return [{"close": price} for _ in range(bars)]

    async def place_order(self, order: Order) -> Order:
        # A protective stop rests; it does not fill and it does not change the
        # position (M31d). Simulating it as a sell would have the simulator
        # liquidate every position the app tried to protect.
        if order.is_protective_stop:
            order.status = "transmitted"
            self._orders[order.order_id] = order
            self._resting_stops[order.symbol] = order.stop_price
            if order.take_profit_price is not None:
                self._resting_targets[order.symbol] = order.take_profit_price
            return order

        fill_price = self._synthetic_price(order.symbol)
        order.status = "filled"
        order.filled_price = fill_price
        # These fakes fill synchronously and completely, so what executed IS the
        # order's size. Stated rather than left None, so OMS tests exercise the
        # populated path the real adapter takes.
        order.filled_quantity = order.quantity
        self._orders[order.order_id] = order
        self._apply_fill(order, fill_price)

        # A bracket entry leaves resting protective legs at the broker. The
        # simulator records them so "did my stop actually get placed?" is
        # answerable here and not only against a live account - the whole
        # reason for the bracket is that these outlive the app process.
        if order.is_bracket and order.side == "buy":
            self._resting_stops[order.symbol] = order.stop_price
            self._resting_targets[order.symbol] = order.take_profit_price
        elif order.side == "sell":
            # Closing the position cancels its protective legs, exactly as a
            # real broker does - otherwise a stale stop would linger against a
            # position that no longer exists.
            self._resting_stops.pop(order.symbol, None)
            self._resting_targets.pop(order.symbol, None)
        return order

    async def recent_fills(
        self, since: datetime, symbols: list[str] | None = None
    ) -> list[BrokerFill]:
        """Protective legs the simulator has executed (M34).

        Driven by fill_resting_stop/fill_resting_target rather than by price,
        so a test can say "the stop fired" without simulating a market.

        `symbols` narrows the answer the way the real adapter's query does
        (M48), so a caller that passes a set which omits a symbol gets the same
        blind spot here as it would in production. A simulator that quietly
        answered more fully than the broker would hide the bug rather than
        reproduce it.
        """
        wanted = set(symbols) if symbols is not None else None
        return [
            f
            for f in self._broker_fills
            if f.filled_at > since and (wanted is None or f.symbol in wanted)
        ]

    def fill_resting_stop(self, symbol: str, price: float | None = None) -> None:
        """Simulates a resting stop executing at the broker."""
        self._fill_protective(symbol, price or self._resting_stops.get(symbol) or 0.0)

    def fill_resting_target(self, symbol: str, price: float | None = None) -> None:
        self._fill_protective(symbol, price or self._resting_targets.get(symbol) or 0.0)

    def _fill_protective(self, symbol: str, price: float) -> None:
        position = self._positions.get(symbol)
        if position is None or position.quantity <= 0:
            return
        quantity = position.quantity
        self._broker_fills.append(
            BrokerFill(
                order_id=f"broker-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="sell",
                quantity=quantity,
                price=price,
                filled_at=datetime.now(UTC),
            )
        )
        # The position closes and its protective legs go with it, exactly as a
        # real broker does.
        self._positions.pop(symbol, None)
        self._resting_stops.pop(symbol, None)
        self._resting_targets.pop(symbol, None)
        self._cash += quantity * price

    async def resting_stops(self) -> dict[str, float]:
        return {s: v for s, v in self._resting_stops.items() if v is not None}

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        """The same stops, with the id and quantity needed to modify one (M39).

        The simulator has no separate protective-order record, so the id is
        synthesised per symbol and the quantity comes from the position it
        protects - which is what a real bracket leg carries.
        """
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

    async def open_orders(self) -> list[RestingOrder]:
        """Not implemented here (I3, final review, correcting M141/item 23).

        This mock has no order-level record of a resting leg -
        `_resting_stops`/`_resting_targets` are position-keyed prices, not
        orders with an id and status, and building that record would give the
        orphan scan a shape this mock invented rather than the real IBKR one
        it is actually measured against
        (`tests/data/broker/test_ib_open_orders.py`).

        `[]` here reads exactly the way `BrokerAdapter.open_orders`'s own
        docstring says empty means: `OMS.check_resting_orders` treats it
        identically to a real broker with nothing open, never as "unknown".
        So the orphan scan will see NOTHING resting through this mock, ever -
        which is why `open_orders` is named in `capabilities.py`'s OPTIONAL
        registry, so that consequence is written down somewhere rather than
        only discoverable by reading this method.
        """
        return []

    def resting_stop(self, symbol: str) -> float | None:
        """The protective stop currently resting at the broker, if any."""
        return self._resting_stops.get(symbol)

    def resting_target(self, symbol: str) -> float | None:
        return self._resting_targets.get(symbol)

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        order = self._orders[order_id]
        for key, value in changes.items():
            setattr(order, key, value)
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        order.status = "cancelled"
        return order

    async def positions(self) -> list[Position]:
        return list(self._positions.values())

    async def account(self) -> AccountSummary:
        market_value = sum(
            pos.quantity * self._synthetic_price(pos.symbol) for pos in self._positions.values()
        )
        net_liq = self._cash + market_value
        return AccountSummary(net_liquidation=net_liq, cash=self._cash, buying_power=self._cash)

    async def balances(self) -> AccountBalances:
        """The three figures the simulator actually knows, plus the long market
        value it can compute. Everything else stays None and renders as a dash -
        the simulator has no margin, no SMA and no day-trade count, and
        inventing them would make the panel look identical whether or not a
        real broker was connected."""
        summary = await self.account()
        long_value = sum(
            pos.quantity * self._synthetic_price(pos.symbol)
            for pos in self._positions.values()
            if pos.quantity > 0
        )
        return AccountBalances(
            equity=summary.net_liquidation,
            cash=summary.cash,
            buying_power=summary.buying_power,
            long_market_value=long_value,
            short_market_value=0.0,
            currency="USD",
            status="SIMULATED",
        )

    def _synthetic_price(self, symbol: str) -> float:
        offset = self._rng.uniform(-1.0, 1.0)
        return round(_SYNTHETIC_BASE_PRICE + offset, 2)

    def _apply_fill(self, order: Order, fill_price: float) -> None:
        signed_qty = order.quantity if order.side == "buy" else -order.quantity
        self._cash -= signed_qty * fill_price
        existing = self._positions.get(order.symbol)
        if existing is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol, quantity=signed_qty, avg_price=fill_price
            )
        else:
            new_qty = existing.quantity + signed_qty
            self._positions[order.symbol] = Position(
                symbol=order.symbol, quantity=new_qty, avg_price=fill_price
            )


def new_order_id() -> str:
    return uuid.uuid4().hex
