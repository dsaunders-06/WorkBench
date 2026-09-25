"""The OMS half of the partial-fill contract (M42).

M42 is a two-layer defect and these tests cover the second layer, not the
first. The bug lived in `AlpacaAdapter.place_order`, which wrote back the order
id, the status and the fill price and left `quantity` at the size requested -
that half is pinned in `tests/data/broker/test_alpaca_adapter.py`.

**These tests passed before the fix as well as after**, and that is worth
saying rather than hiding: they were written first, against a mock that already
wrote the filled quantity back, so they demonstrated the mock behaving well
while the real adapter did not. Testing the layer being reasoned about instead
of the layer holding the defect is the same mistake M56a was found by, and it
very nearly shipped a green suite over a live kill-switch hazard.

Kept because the property is real and unpinned otherwise: the OMS must count
what the adapter reports rather than the size it asked for. Together the two
files say the adapter tells the truth and the OMS believes it.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _PartiallyFillingBroker:
    """Fills a fraction of whatever is asked for, the way a thin book does.

    A fraction rather than a fixed size, because the OMS sizes the order
    itself - the test must not care what it decided, only that the two numbers
    end up agreeing.
    """

    def __init__(self, fraction: float) -> None:
        self.fraction = fraction
        self.requested: float | None = None
        self.filled: float | None = None

    async def place_order(self, order: Order) -> Order:
        self.requested = order.quantity
        # Exactly what AlpacaAdapter does: the SAME order object comes back
        # with the broker's answer written onto it.
        self.filled = order.quantity * self.fraction
        order.filled_quantity = self.filled
        order.filled_price = 100.0
        order.status = "filled"
        return order

    async def positions(self) -> list[Position]:
        return [Position(symbol="AAA", quantity=self.filled or 0.0, avg_price=100.0)]

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=100_000.0, buying_power=100_000.0)

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {"price": 100.0}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError


def _candidate() -> OrderCandidate:
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        candidate_returns=[],
        win_rate=0.9,
        win_loss_ratio=3.0,
        stop_price=95.0,
    )


def _oms(broker: _PartiallyFillingBroker, bus: EventBus | None = None) -> OMS:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    engine = RiskEngine(bus or EventBus(), switch, settings=settings)
    return OMS(broker, engine, switch, bus=bus, max_order_pct_of_cash=1.0)


async def _place(oms: OMS) -> None:
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "test")


@pytest.mark.asyncio
async def test_a_partial_fill_is_tracked_at_what_actually_filled():
    """The defect itself. Tracking the requested size against a broker holding
    less is a discrepancy, and reconciliation answers it with the kill-switch."""
    broker = _PartiallyFillingBroker(fraction=0.6)
    oms = _oms(broker)

    await _place(oms)

    assert broker.requested is not None and broker.requested > 0
    assert broker.filled == pytest.approx(broker.requested * 0.6)
    assert oms._filled_quantities["AAA"] == pytest.approx(
        broker.filled
    ), "tracked must equal what the broker actually holds, not what was requested"


@pytest.mark.asyncio
async def test_the_announced_fill_carries_the_filled_quantity():
    """The ledger builds its entry lot from this event. A lot opened at the
    requested size makes every R-multiple on that trade wrong, and leaves a
    remainder no exit can ever match."""
    bus = EventBus()
    seen: list[OrderFilledEvent] = []

    async def collect(event: OrderFilledEvent) -> None:
        seen.append(event)

    bus.subscribe(OrderFilledEvent, collect)
    broker = _PartiallyFillingBroker(fraction=0.6)
    oms = _oms(broker, bus=bus)

    await _place(oms)

    assert seen, "a fill must be announced"
    assert seen[-1].quantity == pytest.approx(broker.filled)


@pytest.mark.asyncio
async def test_a_complete_fill_is_unchanged():
    """The ordinary case must not move."""
    broker = _PartiallyFillingBroker(fraction=1.0)
    oms = _oms(broker)

    await _place(oms)

    assert oms._filled_quantities["AAA"] == pytest.approx(broker.requested)
