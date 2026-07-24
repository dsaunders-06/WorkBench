"""Order Management System (spec §I): order lifecycle enforcement and the
mandatory human sign-off gate. Order/OrderStatus/BrokerAdapter/MockBroker
all exist since M1 - this builds the state machine that actually enforces
new -> pending_signoff -> transmitted -> filled/cancelled/rejected.

The safety-critical invariant: submit_order() runs the risk pipeline and,
if approved, creates an Order with status="pending_signoff" - it NEVER
calls broker.place_order(). Only sign_off(order_id, operator) (an explicit
call representing the human action) transitions to "transmitted" and calls
the broker. See tests/safety/test_no_order_without_signoff.py.
"""

from __future__ import annotations

import logging

import pandas as pd

from qat.data.broker.adapter import BrokerAdapter, Order
from qat.data.broker.mock_broker import new_order_id
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


class OMS:
    def __init__(
        self,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        max_order_notional: float = 50_000.0,
        symbol_allow_list: set[str] | None = None,
    ) -> None:
        self.broker = broker
        self.risk_engine = risk_engine
        self.kill_switch = kill_switch
        self.max_order_notional = max_order_notional
        self.symbol_allow_list = symbol_allow_list
        self._orders: dict[str, Order] = {}
        self._filled_quantities: dict[str, float] = {}

    async def submit_order(
        self,
        candidate: OrderCandidate,
        equity: float,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        sector_by_symbol: dict[str, str] | None = None,
    ) -> Order:
        if self.symbol_allow_list is not None and candidate.symbol not in self.symbol_allow_list:
            return self._new_rejected_order(candidate, 0.0)

        if self.kill_switch.tripped:
            return self._new_rejected_order(candidate, 0.0)

        decision = self.risk_engine.evaluate_order(
            candidate, equity, existing_weights, existing_returns, sector_by_symbol
        )
        if not decision.approved or decision.final_shares <= 0:
            return self._new_rejected_order(candidate, 0.0)

        notional = decision.final_shares * candidate.price
        if notional > self.max_order_notional:
            return self._new_rejected_order(candidate, decision.final_shares)

        order = Order(
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=decision.final_shares,
            order_id=new_order_id(),
            status="pending_signoff",
        )
        self._orders[order.order_id] = order
        return order

    async def sign_off(self, order_id: str, operator: str) -> Order:
        """The only path that can move an order past pending sign-off - an
        explicit, operator-attributed human action (spec §I)."""
        order = self._orders[order_id]
        if order.status != "pending_signoff":
            raise ValueError(f"Order {order_id} is not pending sign-off (status={order.status})")

        if self.kill_switch.tripped:
            order.status = "rejected"
            logger.info("Sign-off blocked by kill-switch: order=%s operator=%s", order_id, operator)
            return order

        order.status = "transmitted"
        filled = await self.broker.place_order(order)
        self._orders[order_id] = filled
        signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity
        self._filled_quantities[filled.symbol] = (
            self._filled_quantities.get(filled.symbol, 0.0) + signed_qty
        )
        logger.info(
            "Order signed off and transmitted: order=%s operator=%s symbol=%s qty=%s",
            order_id,
            operator,
            filled.symbol,
            filled.quantity,
        )
        return filled

    async def reject_order(self, order_id: str, operator: str, reason: str) -> Order:
        order = self._orders[order_id]
        if order.status not in ("new", "pending_signoff"):
            raise ValueError(f"Order {order_id} cannot be rejected from status={order.status}")
        order.status = "rejected"
        logger.info("Order rejected: order=%s operator=%s reason=%s", order_id, operator, reason)
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status == "transmitted":
            cancelled = await self.broker.cancel_order(order_id)
            self._orders[order_id] = cancelled
            return cancelled
        if order.status in ("filled", "cancelled", "rejected"):
            return order
        order.status = "cancelled"
        return order

    def get_order(self, order_id: str) -> Order:
        return self._orders[order_id]

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    async def check_reconciliation(self) -> bool:
        """Compares OMS-tracked filled quantities against broker-reported
        positions; a mismatch trips the kill-switch (spec §I). Returns True
        if a mismatch was found."""
        broker_positions = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        symbols = set(self._filled_quantities) | set(broker_positions)
        mismatch = any(
            abs(self._filled_quantities.get(symbol, 0.0) - broker_positions.get(symbol, 0.0)) > 1e-6
            for symbol in symbols
        )
        if mismatch:
            self.kill_switch.check_reconciliation()
        return mismatch

    def _new_rejected_order(self, candidate: OrderCandidate, quantity: float) -> Order:
        order = Order(
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=quantity,
            order_id=new_order_id(),
            status="rejected",
        )
        self._orders[order.order_id] = order
        return order
