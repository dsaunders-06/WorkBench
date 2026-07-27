"""Deterministic in-memory broker for tests and M1 smoke runs.

Seeded so a given seed always produces the same synthetic fills - required
for reproducible tests and, later, reproducible backtests/paper sessions.
"""

from __future__ import annotations

import random
import uuid

from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    Order,
    Position,
)

_STARTING_CASH = 100_000.0
_SYNTHETIC_BASE_PRICE = 100.0


class MockBroker:
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic fills, not crypto
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._resting_stops: dict[str, float | None] = {}
        self._resting_targets: dict[str, float | None] = {}
        self._cash = _STARTING_CASH

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        price = self._synthetic_price(symbol)
        return {"bid": price - 0.01, "ask": price + 0.01, "last": price}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        price = self._synthetic_price(symbol)
        return [{"close": price} for _ in range(bars)]

    async def place_order(self, order: Order) -> Order:
        fill_price = self._synthetic_price(order.symbol)
        order.status = "filled"
        order.filled_price = fill_price
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
