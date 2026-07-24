"""Deterministic in-memory broker for tests and M1 smoke runs.

Seeded so a given seed always produces the same synthetic fills - required
for reproducible tests and, later, reproducible backtests/paper sessions.
"""

from __future__ import annotations

import random
import uuid

from qat.data.broker.adapter import AccountSummary, Order, Position

_STARTING_CASH = 100_000.0
_SYNTHETIC_BASE_PRICE = 100.0


class MockBroker:
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic fills, not crypto
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
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
        return order

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
