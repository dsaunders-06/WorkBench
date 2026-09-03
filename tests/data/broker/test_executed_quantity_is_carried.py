"""An order's SIZE is not the amount that executed, and the app booked the size.

On 3 September TWS staged a 790-share BHP.AX order on a precautionary size limit
- it never reached the exchange - and the app booked all 790 because `oms.py:861`
read `order.quantity`. Reconciliation caught it four minutes later
(`tracked=790 broker=0`) and the kill switch halted flow.

`ib_async`'s `OrderStatus.filled` is the executed quantity and has always been
available; the handoff's claim that this needed a new broker-contract field
populated from scratch overstated the cost.
"""

from __future__ import annotations

from types import SimpleNamespace

from qat.data.broker.adapter import Order
from qat.data.broker.ib_translate import from_ib_trade


def _trade(status: str, filled: float, avg_price: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        order=SimpleNamespace(permId=0),
        orderStatus=SimpleNamespace(status=status, filled=filled, avgFillPrice=avg_price, permId=0),
    )


def _order() -> Order:
    return Order(symbol="BHP.AX", side="buy", quantity=790.0, order_id="app-1")


def test_an_accepted_but_unfilled_order_carries_zero_executed():
    """⚠️ THE 3 SEPTEMBER CASE. Accepted by the broker, nothing executed."""
    result = from_ib_trade(_trade("PreSubmitted", filled=0.0), _order())

    assert result.filled_quantity == 0.0
    assert result.quantity == 790.0, "the ORDER's size is unchanged - they differ"


def test_a_partial_fill_carries_what_executed():
    result = from_ib_trade(_trade("Submitted", filled=400.0, avg_price=64.0), _order())

    assert result.filled_quantity == 400.0


def test_a_full_fill_carries_the_whole_quantity():
    result = from_ib_trade(_trade("Filled", filled=790.0, avg_price=64.0), _order())

    assert result.filled_quantity == 790.0


def test_the_field_defaults_to_none_meaning_unreported():
    """`None` is "this adapter does not report it" - a different claim from zero."""
    assert Order(symbol="BHP.AX", side="buy", quantity=1.0, order_id="x").filled_quantity is None
