"""A rejected protective stop must not give back a booking it never made.

Sign-off deliberately does NOT book a protective stop: `OMS._record_fill`
returns before the booking for `is_protective_stop`, because a resting stop does
not fill and does not change the position (M31d).

⚠️ SO A STOP HAS NOTHING TO REVERSE - AND ITS `quantity` IS THE SIZE OF THE
POSITION IT GUARDS. Publishing `OrderRejectedEvent` for one would compute
`9636 - 0` against A2M.AX and zero out a real 9,636-share holding in the ledger,
handing reconciliation a discrepancy that never happened and tripping the kill
switch on a book that is perfectly healthy.

Reachable, not theoretical: on 4 September IBKR refused four orders with
`Error 354 - you are trying to submit an order without having market data for
this instrument`, and a stop re-arm is an order like any other.

The `symbol not in _filled_quantities` guard in the OMS does not catch this,
because the symbol IS booked - that is the whole point of the position the stop
is protecting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.events import OrderRejectedEvent


class _Client:
    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> datetime:
        return datetime.now()


class _Bus:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish(self, event: object) -> Any:
        self.published.append(event)
        import asyncio

        return asyncio.sleep(0)


def _adapter() -> IBAdapter:
    return IBAdapter(  # type: ignore[arg-type]
        _Client(), _Bus(), settings=Settings(_env_file=None, market="ASX")
    )


def _register(adapter: IBAdapter, order: Order, req_id: int) -> None:
    """Put an order in the adapter's maps the way `place_order` would."""
    adapter._orders[order.order_id] = order
    adapter._ib_orders[order.order_id] = type("IB", (), {"orderId": req_id})()


def test_a_rejected_protective_stop_publishes_no_reversal() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR."""
    adapter = _adapter()
    stop = Order(
        symbol="A2M.AX",
        side="sell",
        quantity=9636.0,
        order_id="stop-1",
        stop_price=5.10,
        order_type="stop",
    )
    assert stop.is_protective_stop, "fixture must actually BE a protective stop"
    _register(adapter, stop, req_id=901)

    adapter._on_ib_error(901, 354, "no market data for this instrument", None)

    published = adapter.bus.published  # type: ignore[attr-defined]
    assert not any(isinstance(e, OrderRejectedEvent) for e in published), (
        "a rejected protective stop must not reverse a booking it never made - "
        "its quantity is the size of the position it guards"
    )


def test_a_rejected_entry_still_publishes_a_reversal() -> None:
    """The guard must be narrow: a real entry still gives its booking back."""
    adapter = _adapter()
    entry = Order(symbol="A2M.AX", side="buy", quantity=9636.0, order_id="entry-1")
    assert not entry.is_protective_stop
    _register(adapter, entry, req_id=902)

    adapter._on_ib_error(902, 354, "no market data for this instrument", None)

    published = adapter.bus.published  # type: ignore[attr-defined]
    assert any(
        isinstance(e, OrderRejectedEvent) for e in published
    ), "an ordinary rejected order must still reverse its optimistic booking"
