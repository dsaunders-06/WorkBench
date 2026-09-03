"""The app booked 790 shares the exchange never took.

3 September: TWS STAGED a 790-share BHP.AX order on a precautionary size limit,
so it never reached the market. `oms.py:861` read `filled.quantity` - the ORDER's
size - and booked all 790. Reconciliation caught it (`tracked=790 broker=0`), the
kill switch halted flow, and the phantom then counted toward the position cap:
NST.AX was refused "already at the 10-position limit" against nine real holdings.

`_sign_off_locked` (oms.py:697) is the private method that books a fill; it is
reached only through the public `sign_off()`, which needs an order already
sitting `pending_signoff` (as `_new_pending_order` leaves it - the same
construction `test_pending_counts_transmitted.py` uses) and a broker to call.
`MockBroker.place_order` always fills the order's full size, which cannot
reproduce a staged-but-unfilled or partially-filled report, so these tests use
a broker double that overrides the returned quantity/status the way a live
adapter mapping a real broker report would - exactly what
`test_order_id_survives_rekeying.py`'s `_ReIdingBroker` does for IBKR's
re-identification.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, OrderStatus
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _ReportingBroker(MockBroker):
    """Reports a caller-chosen executed quantity and status instead of
    MockBroker's default of always filling the order's whole size - the same
    kind of override `_ReIdingBroker` uses, here standing in for whatever a
    live adapter mapped a TWS acknowledgement or execution report to."""

    def __init__(self, filled_quantity: float | None, status: OrderStatus) -> None:
        super().__init__(seed=1)
        self._reported_filled_quantity = filled_quantity
        self._reported_status = status

    async def place_order(self, order: Order) -> Order:
        placed = await super().place_order(order)
        return replace(
            placed,
            status=self._reported_status,
            filled_quantity=self._reported_filled_quantity,
        )


def _oms(filled_quantity: float | None, status: OrderStatus) -> OMS:
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(EventBus(), switch, settings=settings)
    broker = _ReportingBroker(filled_quantity=filled_quantity, status=status)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0)


async def _sign_off_a_buy(oms: OMS, symbol: str = "BHP.AX", quantity: float = 790.0) -> Order:
    """The 3 September order: BHP.AX, 790 shares, ordered and then signed off."""
    order = oms._new_pending_order(
        symbol=symbol, side="buy", quantity=quantity, reference_price=100.0
    )
    return await oms.sign_off(order.order_id, operator="alice")


@pytest.mark.asyncio
async def test_an_accepted_but_unfilled_order_books_nothing() -> None:
    """⚠️ THE TEST THIS TASK EXISTS FOR. TWS staged the order - accepted,
    `status="transmitted"` - but the exchange never took it: nothing executed.
    This is the 3 September BHP.AX incident, reproduced through the real
    `sign_off()` path rather than a hand-rolled call."""
    oms = _oms(filled_quantity=0.0, status="transmitted")

    await _sign_off_a_buy(oms)

    assert oms._filled_quantities.get("BHP.AX", 0.0) == 0.0


@pytest.mark.asyncio
async def test_a_partial_fill_books_only_what_executed() -> None:
    oms = _oms(filled_quantity=400.0, status="transmitted")

    await _sign_off_a_buy(oms)

    assert oms._filled_quantities["BHP.AX"] == 400.0


@pytest.mark.asyncio
async def test_an_unreported_quantity_books_nothing_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`None` is a programming error - all three live adapters populate it.
    Booking nothing is fail-closed: an under-booked real fill is visible to
    reconciliation within five minutes; an over-booked phantom is the defect
    this task exists to prevent."""
    oms = _oms(filled_quantity=None, status="transmitted")

    with caplog.at_level(logging.ERROR):
        await _sign_off_a_buy(oms)

    assert oms._filled_quantities.get("BHP.AX", 0.0) == 0.0
    assert "BHP.AX" in caplog.text
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_a_sell_books_negative_what_executed() -> None:
    """Ordered and executed are DELIBERATELY different sizes (1000 vs 790): a
    sell order for 1000 that only 790 executed against. Booking the ordered
    size here would leave `_filled_quantities` at -210 - a phantom short
    against a broker holding flat - which is the same class of bug as the
    790-share phantom long, just facing the other direction."""
    oms = _oms(filled_quantity=790.0, status="filled")
    oms._filled_quantities["BHP.AX"] = 790.0
    order = oms._new_pending_order(
        symbol="BHP.AX", side="sell", quantity=1000.0, reference_price=100.0
    )

    await oms.sign_off(order.order_id, operator="alice")

    assert oms._filled_quantities["BHP.AX"] == 0.0
