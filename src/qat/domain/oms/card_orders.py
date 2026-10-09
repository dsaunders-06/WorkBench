"""Durable Phase 3 card-key reservation, separate from transmitted identities.

Namespace 9b56cb30-d8b4-5ba1-8e7f-a034ad110a0e is frozen for card IDs.
The derived UUID is the OMS application order ID and becomes the broker order
reference through the existing identity path if paper transmission is ever
separately authorised. Unsigned proposals are never restored into the OMS.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid5

from qat.data.broker.adapter import Order

CARD_ORDER_NAMESPACE = UUID("9b56cb30-d8b4-5ba1-8e7f-a034ad110a0e")


def card_order_id(card_id: str) -> str:
    if not card_id:
        raise ValueError("card ID must not be empty")
    return str(uuid5(CARD_ORDER_NAMESPACE, card_id))


def _order_payload(order: Order) -> dict[str, object]:
    payload: dict[str, object] = asdict(order)
    payload["created_at"] = order.created_at.isoformat()
    payload["earnings_date"] = order.earnings_date.isoformat() if order.earnings_date else None
    payload["auction_open"] = order.auction_open.isoformat() if order.auction_open else None
    return payload


def _order_from_payload(payload: dict[str, object]) -> Order:
    fields = dict(payload)
    fields["created_at"] = datetime.fromisoformat(str(fields["created_at"]))
    if fields.get("earnings_date") is not None:
        fields["earnings_date"] = date.fromisoformat(str(fields["earnings_date"]))
    if fields.get("auction_open") is not None:
        fields["auction_open"] = datetime.fromisoformat(str(fields["auction_open"]))
    return Order(**fields)  # type: ignore[arg-type]


def _intent(order: Order) -> tuple[object, ...]:
    return (
        order.symbol,
        order.side,
        order.quantity,
        order.order_id,
        order.limit_price,
        order.stop_price,
        order.take_profit_price,
        order.reference_price,
        order.strategy,
        order.order_type,
        order.auction_open,
    )


class CardOrderStore:
    """One immutable order intent per card key, including across restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._orders: dict[str, Order] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema") != 1 or not isinstance(raw.get("orders"), dict):
                raise ValueError("invalid card order store")
            for card_id, payload in raw["orders"].items():
                if not isinstance(card_id, str) or not isinstance(payload, dict):
                    raise ValueError("invalid card order record")
                order = _order_from_payload(payload)
                self._validate(card_id, order)
                self._orders[card_id] = order

    @property
    def orders(self) -> dict[str, Order]:
        """Inspection returns copies so callers cannot alter reserved intents."""
        return {
            key: _order_from_payload(_order_payload(value)) for key, value in self._orders.items()
        }

    @staticmethod
    def _validate(card_id: str, order: Order) -> None:
        if order.order_id != card_order_id(card_id):
            raise ValueError("card order ID must be its fixed-namespace UUIDv5")
        if (
            order.order_type != "opening_auction_limit"
            or order.side != "buy"
            or order.quantity <= 0
            or int(order.quantity) != order.quantity
            or order.limit_price is None
            or order.limit_price <= 0
            or order.auction_open is None
            or order.auction_open.tzinfo is None
        ):
            raise ValueError("invalid opening auction limit intent")

    def reserve(self, card_id: str, order: Order) -> Order:
        self._validate(card_id, order)
        existing = self._orders.get(card_id)
        if existing is not None:
            if _intent(existing) != _intent(order):
                raise ValueError("card key already reserved for a different order")
            return _order_from_payload(_order_payload(existing))
        reserved = _order_from_payload(_order_payload(order))
        updated = {**self._orders, card_id: reserved}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {
                    "schema": 1,
                    "orders": {key: _order_payload(value) for key, value in updated.items()},
                },
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self._orders = updated
        return _order_from_payload(_order_payload(reserved))
