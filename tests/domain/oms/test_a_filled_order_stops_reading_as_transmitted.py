"""An order IBKR filled kept reading `transmitted` in this app, forever.

⚠️ MEASURED LIVE, 4 September 2026. TWE.AX and TAH.AX were both filled by IBKR -
the broker held 10,412 and 64,229 with their brackets resting - and 45 minutes
later the app still had them at `status=transmitted`, logging

    Autonomy blocked order 579188638 (buy TWE.AX): order is not pending
    sign-off (status=transmitted)

once a minute for each. The M139 guard refused them correctly every time, so
nothing was re-sent; but the app was asking a question it should have known the
answer to, and the resting-order rail quarantined both symbols on a book it
could not justify.

⚠️ THE FAKES HID IT. `MockBroker.place_order` and `SimulatedBroker` both fill
synchronously and set `status = "filled"` themselves. `IBAdapter` writes
"transmitted", "cancelled" and "rejected" and NEVER "filled" - `from_ib_trade`
can map it, but it is only ever called at placement, when the trade is still
PreSubmitted. So every test in this suite passed against a broker that closed
its own orders out, and the one real adapter never did.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _AsyncAckBroker(MockBroker):
    """Acknowledges without filling, the way IBKR does.

    ⚠️ The point of this fake. `MockBroker` fills synchronously and writes
    `status = "filled"` itself, which is precisely why no existing test could
    catch an adapter that never writes it.
    """

    def __init__(self) -> None:
        super().__init__(seed=1)
        self.queued_fills: list[BrokerFill] = []

    async def place_order(self, order: Order) -> Order:
        order.status = "transmitted"
        self._orders[order.order_id] = order
        return order

    async def recent_fills(self, since, symbols=None) -> list[BrokerFill]:
        return list(self.queued_fills)


def _returns(n: int = 30) -> pd.Series:
    return pd.Series([0.01, -0.01] * (n // 2), index=pd.date_range("2024-01-01", periods=n))


async def _transmitted_order(broker: _AsyncAckBroker) -> tuple[OMS, Order]:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    bus = EventBus()
    engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, engine, switch, bus=bus, settings=settings)
    order = await oms.submit_order(
        OrderCandidate(
            symbol="AAA",
            side="buy",
            price=100.0,
            atr=2.0,
            win_rate=0.55,
            win_loss_ratio=1.5,
            candidate_returns=_returns(),
            strategy="swing",
        ),
        100_000.0,
        {},
        {},
    )
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.status == "transmitted", "the fixture must reproduce the IBKR shape"
    return oms, signed


def _fill(order: Order, quantity: float) -> BrokerFill:
    return BrokerFill(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=quantity,
        price=100.0,
        filled_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_a_complete_fill_of_our_own_order_marks_it_filled() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR."""
    broker = _AsyncAckBroker()
    oms, order = await _transmitted_order(broker)
    broker.queued_fills = [_fill(order, order.quantity)]

    await oms.absorb_broker_fills()

    assert order.status == "filled"


@pytest.mark.asyncio
async def test_a_partial_fill_leaves_it_transmitted() -> None:
    """Still working is not done. Closing it out early would hide the
    remainder from every rail that asks what is in flight."""
    broker = _AsyncAckBroker()
    oms, order = await _transmitted_order(broker)
    broker.queued_fills = [_fill(order, order.quantity / 2.0)]

    await oms.absorb_broker_fills()

    assert order.status == "transmitted"


@pytest.mark.asyncio
async def test_a_cancelled_order_is_not_resurrected_as_filled() -> None:
    """⚠️ A late fill notice against an order this app cancelled must not
    rewrite its outcome - the same reasoning `_TERMINAL_ORDER_STATUSES` uses
    for a late 202 against a filled order."""
    broker = _AsyncAckBroker()
    oms, order = await _transmitted_order(broker)
    order.status = "cancelled"
    broker.queued_fills = [_fill(order, order.quantity)]

    await oms.absorb_broker_fills()

    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_a_foreign_fill_touches_no_order_of_ours() -> None:
    """A stop the broker fired is not one of our transmitted orders."""
    broker = _AsyncAckBroker()
    oms, order = await _transmitted_order(broker)
    foreign = _fill(order, order.quantity)
    broker.queued_fills = [
        BrokerFill(
            order_id="broker-someone-else",
            symbol=foreign.symbol,
            side=foreign.side,
            quantity=foreign.quantity,
            price=foreign.price,
            filled_at=foreign.filled_at,
        )
    ]

    await oms.absorb_broker_fills()

    assert order.status == "transmitted"
