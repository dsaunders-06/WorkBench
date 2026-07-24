"""Broker-agnostic interface. IBAdapter (M7) and MockBroker both implement this."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

OrderStatus = Literal["new", "pending_signoff", "transmitted", "filled", "cancelled", "rejected"]


@dataclass(slots=True)
class Order:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    order_id: str
    status: OrderStatus = "new"
    limit_price: float | None = None
    filled_price: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    avg_price: float


@dataclass(slots=True)
class AccountSummary:
    net_liquidation: float
    cash: float
    buying_power: float


class BrokerAdapter(Protocol):
    async def get_market_data(self, symbol: str) -> dict[str, float]: ...

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]: ...

    async def place_order(self, order: Order) -> Order: ...

    async def modify_order(self, order_id: str, **changes: object) -> Order: ...

    async def cancel_order(self, order_id: str) -> Order: ...

    async def positions(self) -> list[Position]: ...

    async def account(self) -> AccountSummary: ...
