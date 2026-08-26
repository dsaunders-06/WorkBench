"""An order this app sent must never be absorbed as a foreign fill.

Measured 26 August 2026. Two entries transmitted at 15:15:24-25, each exactly
once and correctly bracketed. 107 seconds later the app absorbed both as "a
position was OPENED at the broker that this application did not send" and the
book doubled: WOW.AX tracked=2196 broker=1098, SEK.AX tracked=5956 broker=2978.

The cause is an identity mismatch, not a race. `IB.placeOrder` returns before
TWS acknowledges, so `permId` is 0 and `from_ib_trade` correctly leaves the
app's own UUID on the order. `_broker_order_ids` therefore holds a UUID while
the execution arrives keyed on the permId.

This task ships no fix - see `oms.py:730` and `ib_translate.py:from_ib_trade`
for where Tasks 2-3 have to change. Both tests below are expected to FAIL
until then; that failure is the specification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _candidate(symbol: str = "WOW.AX") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=213.70,
        atr=4.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.01, -0.01] * 30),
        strategy="swing",
    )


@pytest.fixture
async def oms_that_sent_an_order(tmp_path):
    """An OMS that has transmitted one order, the IBKR permId=0 way.

    Three things this must get right or it proves nothing:

    * Its OWN `data_dir` (tmp_path). `conftest.isolate_data_dir` is session-
      scoped, so every test otherwise shares one QAT_DATA_DIR - and the
      anomaly stores below are keyed to `settings.data_dir` and persist
      there. Absorbing the crafted fill in the second test declares a
      quarantine; without an isolated dir that quarantine would leak into
      every test that runs after this one.
    * `place_order` must return the order with `order_id` UNCHANGED - the
      app's own UUID. `MockBroker.place_order` (mock_broker.py) never
      touches `order.order_id` at all: it mutates status/filled_price in
      place and hands back the SAME object, which is exactly the shape
      `from_ib_trade` produces when `permId` is 0 (ib_translate.py, around
      line 310-325) - TWS has not acknowledged yet, so there is no broker id
      to assign. A stub that assigned its own id here - the way
      `tests/safety/test_own_fills_and_duplicates.py`'s `_RenamingBroker`
      does, for the unrelated Alpaca-shaped M46 defect - would make this
      test pass against the 26 August defect and prove nothing.
    * The order goes through the real `submit_order` / `sign_off` path, so
      `OMS._broker_order_ids` is populated at `oms.py:730` the way
      production populates it, not by writing to the set directly.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker(seed=1)
    oms = OMS(broker, engine, switch, bus=bus, settings=settings)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    filled = await oms.sign_off(order.order_id, operator="operator")
    assert filled.status == "filled", "the fixture's own order must actually fill"
    assert filled.order_id == order.order_id, (
        "the fixture's premise: the broker must leave order_id UNCHANGED, or this "
        "is not the permId=0 shape the 26 August incident actually had"
    )

    # 107 seconds later, the broker reports the resulting execution under a
    # DIFFERENT, permId-shaped numeric id - TWS assigns permId only once it
    # acknowledges, which `from_ib_trade` could not have done at placeOrder
    # time because the id did not exist yet.
    fill_for_our_order = BrokerFill(
        order_id="550634674",
        symbol=filled.symbol,
        side=filled.side,
        quantity=filled.quantity,
        price=filled.filled_price or 0.0,
        filled_at=datetime.now(UTC),
    )
    # So the second test's absorb_broker_fills() can actually see it -
    # MockBroker.recent_fills reads from here, the same seam
    # tests/safety/test_own_fills_and_duplicates.py uses throughout.
    broker._broker_fills.append(fill_for_our_order)
    # Clock-granularity rewind, same reason and same amount as every other
    # fill test in this suite (see test_own_fills_and_duplicates.py): without
    # it, construction and the fill above can land in the same tick and the
    # strictly-greater watermark filter drops it before either test runs.
    oms._last_fill_scan -= timedelta(seconds=1)

    return oms, fill_for_our_order


@pytest.mark.asyncio
async def test_a_fill_for_an_order_this_app_sent_is_not_foreign(oms_that_sent_an_order):
    """The whole defect, in one assertion.

    The OMS transmitted an order and the broker reported the resulting
    execution under its OWN identifier. That fill is not foreign, however the
    two ids are spelled.
    """
    oms, fill_for_our_order = oms_that_sent_an_order

    assert not oms._is_foreign_unrecorded(fill_for_our_order), (
        "the app absorbed its own order as a foreign broker-side fill - this is "
        "the 26 August double-count, and it doubles the book"
    )


@pytest.mark.asyncio
async def test_absorbing_after_our_own_entry_does_not_double_the_book(
    oms_that_sent_an_order,
):
    """The consequence, asserted where an operator would see it."""
    oms, _ = oms_that_sent_an_order
    before = dict(oms._filled_quantities)

    await oms.absorb_broker_fills()

    assert oms._filled_quantities == before, (
        f"tracked quantities moved on an absorb of our own fill: "
        f"{before} -> {dict(oms._filled_quantities)}"
    )
