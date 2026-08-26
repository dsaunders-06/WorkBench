"""An order this app sent must never be absorbed as a foreign fill.

Measured 26 August 2026. Two entries transmitted at 15:15:24-25, each exactly
once and correctly bracketed. 107 seconds later the app absorbed both as "a
position was OPENED at the broker that this application did not send" and the
book doubled: WOW.AX tracked=2196 broker=1098, SEK.AX tracked=5956 broker=2978.

The cause is an identity mismatch, not a race. `IB.placeOrder` returns before
TWS acknowledges, so `permId` is 0 and `from_ib_trade` correctly leaves the
app's own UUID on the order. `_broker_order_ids` therefore holds a UUID while
the execution arrives keyed on the permId.

Tasks 2-3 fixed it: `IBAdapter.place_order` now waits, bounded, for the
permId (`_await_perm_id`, `ib_adapter.py`), and a permId that still arrives
late is bound through `_adopt_from_broker` publishing
`BrokerOrderIdResolvedEvent`, which `OMS._on_broker_order_id_resolved`
registers. `test_a_permid_learned_after_transmit_is_registered` below pins
that second, belt-and-braces path directly against the OMS's own bookkeeping.

**The end-to-end guard is the main event in this file, and it has to be
end-to-end.** This file used to hold two OTHER tests that pinned the same
claim - "a fill for an order this app sent is not foreign" - by building the
OMS over `MockBroker` and writing/reading its sets directly. Both were RED by
construction, and neither could ever have been made GREEN honestly:
`MockBroker.place_order` never varies `order.order_id` - it mutates
status/filled_price on the SAME object and hands it back - so no path through
it reaches either fix. Not `place_order`'s bounded wait, which exists only on
`IBAdapter` and has nothing IBKR-shaped to wait on over `MockBroker`. Not
`_adopt_from_broker`'s late binding, which resolves against
`reqAllOpenOrdersAsync`, a method `MockBroker` does not have. An OMS built
over `MockBroker` cannot fail the way the incident failed, so a test built
over one cannot prove the fix - it was asserting what the OMS ought to do, in
a shape production never actually produces. Every layer involved (the
adapter's wait, the OMS's identity check) was separately tested and separately
correct; what failed on 26 August was the CONNECTION between them, and only a
test that drives both together through the same real objects can pin that.

So `test_a_fill_under_the_permid_is_not_absorbed_as_foreign_end_to_end` drives
a real `IBAdapter` over a fake TWS whose permId is stamped from a task the
event loop runs strictly AFTER `placeOrder` returns - not synchronously, which
is the one timing detail that makes `_await_perm_id` necessary at all - through
the real `submit_order` -> `sign_off` path, exactly as production calls it.
The order this produces is a real bracket: the 26 August incident was TWO
BRACKETS, not a bare order, and the parent leg is the one whose permId this
whole defect turns on.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from ib_async import AccountValue, CommissionReport, Contract, Execution, Fill
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill
from qat.data.broker.ib_adapter import IBAdapter
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


# --- the end-to-end guard --------------------------------------------------


class _LateAckIBGateway:
    """A fake TWS shaped for exactly the two facts the incident turned on.

    `orderId` is assigned SYNCHRONOUSLY inside `placeOrder`, because real
    ib_async does that (`if not order.orderId: order.orderId =
    self.client.getReqId()`) and `IBAdapter._place_bracket` reads
    `parent.orderId` the instant `placeOrder` returns, to link the stop leg's
    `parentId` - see `tests/data/broker/test_ib_brackets.py::RecordingIB`,
    which established that requirement first.

    `permId`, by contrast, is asymmetric: `placeOrder` leaves it at 0 and a
    SEPARATE task, scheduled onto the running loop but not awaited, stamps
    the real value after `ack_delay`. That is the timing that actually
    produced the 26 August defect - `IB.placeOrder` returns before TWS
    acknowledges - and it is the reason this is a scheduled task and not a
    synchronous assignment: a fake that stamps permId before `placeOrder`
    returns would never exercise `_await_perm_id`'s wait at all, the same
    trap `tests/data/broker/test_ib_permid_wait.py::_LatePermIdClient`
    documents and whose technique this adapts.

    `reqExecutionsAsync` answers whatever the fixture puts in `executions`,
    populated AFTER transmit - exactly how a real execution report arrives
    well after the order that produced it, never synchronously with it.
    """

    def __init__(self, perm_id: int, ack_delay: float = 0.03) -> None:
        self._next_order_id = 100
        self.perm_id = perm_id
        self.ack_delay = ack_delay
        self.placed: list[IBOrder] = []
        self.executions: list[Fill] = []

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        if not order.orderId:
            order.orderId = self._next_order_id
            self._next_order_id += 1
        order.permId = 0
        status = OrderStatus(orderId=order.orderId, status="PreSubmitted", permId=0)
        trade = Trade(contract=contract, order=order, orderStatus=status)
        self.placed.append(order)
        # Scheduled, not awaited - `placeOrder` itself stays synchronous, as
        # real ib_async's is, so the acknowledgement genuinely lands on a
        # LATER loop iteration than this call.
        asyncio.ensure_future(self._acknowledge(order, status))
        return trade

    async def _acknowledge(self, order: IBOrder, status: OrderStatus) -> None:
        await asyncio.sleep(self.ack_delay)
        order.permId = self.perm_id
        status.permId = self.perm_id

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> None:
        return None

    def positions(self, account: str = "") -> list[object]:
        return []

    def accountSummary(self, account: str = "") -> list[AccountValue]:
        # Enough cash that the buy-side sign-off cost check never refuses -
        # this guard is about identity, not sizing, and mirrors what
        # MockBroker starts every other test in this file with.
        return [
            AccountValue(
                account="DU1",
                tag="TotalCashValue",
                value="100000",
                currency="AUD",
                modelCode="",
            )
        ]

    async def reqExecutionsAsync(self, execFilter: object = None) -> list[Fill]:
        return list(self.executions)


def _execution(
    symbol: str, side: str, shares: float, price: float, perm_id: int, when: datetime
) -> Fill:
    """One IBKR execution, shaped the way `from_ib_fill` expects it - the
    same construction `tests/data/broker/test_ib_recent_fills.py::_fill`
    uses, adapted here rather than imported so this file stays self-contained."""
    contract = Contract(symbol=symbol, secType="STK", exchange="ASX", currency="AUD")
    execution = Execution(
        execId="0001.abc",
        time=when,
        side=side,
        shares=shares,
        price=price,
        permId=perm_id,
        orderId=perm_id,
        cumQty=shares,
        avgPrice=price,
    )
    return Fill(
        contract=contract, execution=execution, commissionReport=CommissionReport(), time=when
    )


@pytest.fixture
async def oms_over_ib_adapter(tmp_path):
    """An OMS over a REAL `IBAdapter`, that has transmitted one bracket the
    IBKR permId-arrives-late way, through the real production call path.

    Three things this must get right or it proves nothing - the end-to-end
    counterparts of the three the old MockBroker fixture had to get right:

    * Its OWN `data_dir` (tmp_path). `conftest.isolate_data_dir` is session-
      scoped, so every test otherwise shares one QAT_DATA_DIR - and the
      anomaly stores and the absorbed-fills watermark are keyed to
      `settings.data_dir` and persist there.
    * A REAL `IBAdapter`, not `MockBroker` - this is the entire reason this
      fixture exists instead of reusing `oms_that_sent_an_order` below.
      `place_order`'s bounded permId wait and `_adopt_from_broker`'s late
      binding are both `IBAdapter` methods; a fixture that does not construct
      one cannot reach either.
    * The order goes through the real `submit_order` -> `sign_off` path, so
      `OMS._broker_order_ids` is populated at `oms.py:730` the way production
      populates it, not by writing to the set directly.
    """
    client = _LateAckIBGateway(perm_id=550634674)
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        market="ASX",
        ibkr_permid_wait_seconds=2.0,
    )
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    adapter = IBAdapter(client, bus, settings=settings)
    oms = OMS(adapter, engine, switch, bus=bus, settings=settings)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    assert (
        order.status == "pending_signoff"
    ), f"fixture premise: submit_order must not itself transmit, got status={order.status!r}"
    filled = await oms.sign_off(order.order_id, operator="operator")
    assert filled.status == "transmitted", (
        f"fixture premise: the fixture's own order must actually reach the broker, "
        f"got status={filled.status!r}"
    )
    assert filled.order_id == "550634674", (
        "fixture premise: place_order's bounded permId wait (Task 2) must have picked "
        f"up the permId before returning - got order_id={filled.order_id!r}. If this "
        "fails, the fix under test is unreachable and everything below tests nothing."
    )

    # The execution arrives afterwards, keyed on the SAME permId the wait
    # above resolved - exactly how TWS actually reports it, never
    # synchronously with placeOrder.
    client.executions.append(
        _execution(
            symbol="WOW",
            side="BOT",
            shares=filled.quantity,
            price=filled.filled_price or 213.70,
            perm_id=550634674,
            when=datetime.now(UTC),
        )
    )
    # Clock-granularity rewind, same reason and same amount as every other
    # fill test in this suite (see test_own_fills_and_duplicates.py and the
    # MockBroker fixture below): without it, the fixture's own construction
    # and the execution above can land in the same tick, and the strictly-
    # greater watermark filter in `_fill_query_floor` drops it before either
    # assertion below runs.
    oms._last_fill_scan -= timedelta(seconds=1)

    fill_for_our_order = BrokerFill(
        order_id="550634674",
        symbol=filled.symbol,
        side=filled.side,
        quantity=filled.quantity,
        price=filled.filled_price or 0.0,
        filled_at=datetime.now(UTC),
    )
    return oms, fill_for_our_order


@pytest.mark.asyncio
async def test_a_fill_under_the_permid_is_not_absorbed_as_foreign_end_to_end(
    oms_over_ib_adapter,
):
    """The whole defect, at the layer it actually lives.

    A real `IBAdapter`, transmitted through the real OMS call path, with a
    permId that arrived late off a scheduled task the way TWS actually
    delivers one. The resulting execution, keyed on that permId, must not be
    foreign - and absorbing it must not move a tracked quantity that
    `sign_off` already counted, which is the consequence an operator would
    actually see.
    """
    oms, fill_for_our_order = oms_over_ib_adapter

    assert not oms._is_foreign_unrecorded(fill_for_our_order), (
        "the app absorbed its own order as a foreign broker-side fill - this is "
        "the 26 August double-count, and it doubles the book"
    )

    before = dict(oms._filled_quantities)
    await oms.absorb_broker_fills()

    assert oms._filled_quantities == before, (
        f"tracked quantities moved on an absorb of our own fill: "
        f"{before} -> {dict(oms._filled_quantities)}"
    )


# --- the belt-and-braces path: a permId learned after the wait already gave up ---


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

    This fixture stays on `MockBroker` deliberately (it is what
    `test_a_permid_learned_after_transmit_is_registered` below needs): that
    test pins `register_broker_order_id` against the OMS's own bookkeeping
    directly, and does not touch `IBAdapter` at all. The end-to-end claim -
    that the SAME thing happens automatically, through a real adapter, when a
    permId genuinely arrives late - is `oms_over_ib_adapter` above.
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
async def test_a_permid_learned_after_transmit_is_registered(oms_that_sent_an_order):
    """The belt-and-braces path, for when the wait in place_order times out.

    The adapter learns the permId moments later either way - it needs it for
    modify and cancel to resolve. The OMS's own foreign-fill check must learn it
    at the same moment, or a slow acknowledgement still doubles the book.
    """
    oms, fill_for_our_order = oms_that_sent_an_order
    assert oms._is_foreign_unrecorded(fill_for_our_order), "fixture should start unregistered"

    oms.register_broker_order_id(fill_for_our_order.order_id)

    assert not oms._is_foreign_unrecorded(fill_for_our_order)
