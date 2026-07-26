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
    # The price this order was sized against at submission. Kept so the
    # sign-off cash check has a known cost even when the broker cannot supply a
    # live quote - without it, an adapter that does not serve market data
    # leaves the check with no price at all.
    reference_price: float | None = None
    # Which strategy produced this order, when one did. Carried so the
    # autonomy gate can be granted per-strategy rather than all-or-nothing, and
    # so the decision journal can attribute an outcome to the strategy that
    # caused it. None for manual and exit orders, which belong to no strategy.
    strategy: str | None = None
    # Protective exits attached to the entry, submitted to the broker as one
    # bracket (M14). These live AT THE BROKER, which is the entire point: a
    # stop held only in this process disappears the moment the process does,
    # leaving the position naked. An unattended system that can die overnight
    # needs its protection to outlive it.
    stop_price: float | None = None
    take_profit_price: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_bracket(self) -> bool:
        return self.stop_price is not None or self.take_profit_price is not None


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
