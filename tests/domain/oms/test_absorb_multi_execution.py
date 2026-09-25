"""One broker exit is one closed trade, however many executions it took.

LOV.AX filled 3,217 shares in 183 executions on 26 August 2026. Two things must
both hold: every share is absorbed, and the ledger gains ONE row rather than
183. The promotion gate counts closed trades toward 20 and 30, so an exit that
books itself 183 times clears the gate on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.ib_translate import from_ib_fill
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _ib_execution(shares: float, cum_qty: float, price: float, avg_price: float, when: datetime):
    """The raw ib_async shape, run through the real `from_ib_fill` translation
    - not a hand-built `BrokerFill` - so a regression of the `avgPrice`/`price`
    sibling defect breaks this test too, not just the translation-layer one in
    `tests/data/broker/test_ib_fill_cumulative.py`."""
    raw = SimpleNamespace(
        contract=SimpleNamespace(symbol="LOV"),
        execution=SimpleNamespace(
            execId="x",
            permId=1216552509,
            side="SLD",
            shares=shares,
            cumQty=cum_qty,
            price=price,
            avgPrice=avg_price,
            time=when,
        ),
    )
    fill = from_ib_fill(raw, "ASX")
    assert fill is not None
    return fill


def _lov_executions() -> list[BrokerFill]:
    """The real shape: many executions, one order, rising cumulative.

    Deliberately includes a LATER execution SMALLER than an earlier one - that
    is the exact condition the old code discarded, and a fixture of uniformly
    rising execution sizes would pass against the defect.
    """
    sizes = [10.0, 25.0, 4.0, 12.0, 51.0, 8.0, 374.0, 3.0, 2730.0]
    start = datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC)
    running = 0.0
    fills = []
    for i, size in enumerate(sizes):
        running += size
        fills.append(
            BrokerFill(
                order_id="1216552509",
                symbol="LOV.AX",
                side="sell",
                quantity=running,  # CUMULATIVE, per the BrokerFill contract
                price=28.45,
                filled_at=start + timedelta(seconds=i),
            )
        )
    return fills


@pytest.fixture
async def oms_with_lov_position(tmp_path):
    """An OMS adopted into a 3,217-share LOV.AX position this app never
    transmitted, with a broker stub whose `recent_fills` answers with the raw
    183-execution shape (compressed here to 9 executions - `_lov_executions`).

    Modelled on `tests/domain/oms/test_resting_order_reconciliation.py`'s
    `oms_factory` (a real, test-isolated `data_dir` passed through to `OMS`
    rather than left to construct one itself) and on the adopted-position
    tests in `tests/safety/test_broker_side_fills.py` (a position placed
    directly on the broker stub and picked up by `adopt_broker_positions`,
    which is what makes the fills read as foreign rather than the app's own).

    `data_dir=str(tmp_path)` is not optional: `conftest` sets `QAT_DATA_DIR`
    session-wide and `PositionAnomalyStore` persists there, so a test that
    lets a declared anomaly land in that shared directory would quarantine
    LOV.AX for every test that runs after it in the same session.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["LOV.AX"] = Position(symbol="LOV.AX", quantity=3217.0, avg_price=28.45)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    await oms.adopt_broker_positions()

    executions = _lov_executions()
    broker._broker_fills = executions
    # The floor has to sit before the EARLIEST execution. Elsewhere in this
    # suite the pattern is `_last_fill_scan -= timedelta(seconds=1)` against
    # fills stamped `datetime.now(UTC)`; these fills carry fixed historical
    # timestamps instead, so the watermark is set directly against them
    # rather than against whatever the wall clock happens to read when the
    # test runs.
    oms._last_fill_scan = executions[0].filled_at - timedelta(seconds=1)
    return oms


@pytest.mark.asyncio
async def test_every_share_of_a_multi_execution_exit_is_absorbed(oms_with_lov_position):
    """3,217 filled, 3,217 absorbed.

    ⚠️ This assertion passes with the CUMULATIVE-quantity fix alone and does not
    need the per-order collapse - the delta arithmetic already sums correctly
    across many entries. It is here as a regression guard, not as the thing that
    demonstrates this task. The row-count test below is what the collapse fixes.

    The live 374 shortfall was the SHARES half of the defect
    (`from_ib_fill` supplying per-execution rather than cumulative), which is
    fixed one task earlier.
    """
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    total = sum(f.quantity for f in absorbed)
    assert total == pytest.approx(
        3217.0
    ), f"absorbed {total} of 3,217 - the shortfall is silently discarded fills"


@pytest.mark.asyncio
async def test_one_exit_produces_one_absorbed_fill(oms_with_lov_position):
    """Not 183. The gate counts rows."""
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    assert len(absorbed) == 1, (
        f"{len(absorbed)} fills for one order - the ledger will carry one row "
        "each and the promotion gate counts them"
    )


@pytest.mark.asyncio
async def test_a_later_piece_at_a_different_price_is_recovered_correctly(tmp_path):
    """`_lov_executions` fills at ONE price throughout, which cannot tell
    apart "recovered the increment's own price from two running averages"
    from "assumed the cumulative average is the increment's price" - both
    give the same answer when nothing ever moved. The real LOV order did move.

    Two POLLS, not one - the delta arithmetic in `_unabsorbed_part` only runs
    on the second sighting of an order id, and a single `broker._broker_fills`
    list (as `_lov_executions` uses) never produces one: the per-order collapse
    keeps only the highest-quantity row, which `_unabsorbed_part` then sees
    with `prior is None` and returns unchanged.

    Poll 1: an execution moving 2,000 shares, its own price and the order's
    average both 28.00 (one execution so far, so the two coincide - this poll
    alone is uninformative about whether `price` is per-execution or
    cumulative).

    Poll 2: an execution moving the remaining 1,217 shares at its OWN price of
    30.00, taking the order's cumulative average to 92510/3217 = 28.75288...
    Both raw executions go through the real `from_ib_fill` translation, so
    this is an end-to-end check: if `avgPrice` regressed back to `price`
    (the sibling defect), poll 2's `BrokerFill.price` would read 30.00
    instead of 28.75288..., `_unabsorbed_part` would blend it against the
    PRIOR average as though both were cumulative, and the absorbed increment
    below would NOT read 30.00.
    """
    start = datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC)
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["LOV.AX"] = Position(symbol="LOV.AX", quantity=3217.0, avg_price=28.00)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        # Keep the historical execution inside the 30-day cumulative-receipt
        # retention window. A wall clock made this test expire on 25 September.
        clock=lambda: start + timedelta(seconds=2),
    )
    await oms.adopt_broker_positions()

    oms._last_fill_scan = start - timedelta(seconds=1)

    first_piece = _ib_execution(
        shares=2000.0, cum_qty=2000.0, price=28.00, avg_price=28.00, when=start
    )
    broker._broker_fills = [first_piece]
    broker._positions["LOV.AX"] = Position(symbol="LOV.AX", quantity=1217.0, avg_price=28.00)
    first_absorbed = await oms.absorb_broker_fills()

    assert len(first_absorbed) == 1
    assert first_absorbed[0].price == pytest.approx(28.00)

    second_piece = _ib_execution(
        shares=1217.0,
        cum_qty=3217.0,
        price=30.00,  # this execution's OWN price
        avg_price=92510.0 / 3217.0,  # the order's TRUE cumulative average
        when=start + timedelta(seconds=1),
    )
    broker._broker_fills = [second_piece]
    broker._positions.pop("LOV.AX")  # the rest fills and the position goes flat
    second_absorbed = await oms.absorb_broker_fills()

    assert len(second_absorbed) == 1
    assert second_absorbed[0].quantity == pytest.approx(1217.0)
    assert second_absorbed[0].price == pytest.approx(30.00), (
        f"got {second_absorbed[0].price} - the last 1,217 shares filled at "
        "$30.00; a blended or stale price here means the increment's own "
        "price was not recovered from the two running averages"
    )


@pytest.mark.asyncio
async def test_an_empty_fill_list_absorbs_nothing(tmp_path):
    """The per-order collapse loops over `fills`; an empty list is correct by
    inspection (the loop simply never runs), but nothing had exercised it.
    `MockBroker.recent_fills` answers `[]` when nothing is queued - the
    default state of a fresh stub - so this is the ordinary "nothing has
    happened yet" poll, not a contrived edge case."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )

    absorbed = await oms.absorb_broker_fills()

    assert absorbed == []


@pytest.mark.asyncio
async def test_two_different_orders_in_one_pass_are_both_absorbed(tmp_path):
    """The collapse keys `highest` by `order_id`, so two DIFFERENT orders
    reported in the same poll must not collide in that dict - each keeps its
    own row, with its own quantity and its own price, rather than one
    overwriting the other or the two being merged."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["AAA"] = Position(symbol="AAA", quantity=10.0, avg_price=50.0)
    broker._positions["BBB"] = Position(symbol="BBB", quantity=20.0, avg_price=75.0)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    await oms.adopt_broker_positions()

    now = datetime.now(UTC)
    oms._last_fill_scan = now - timedelta(seconds=1)
    broker._positions.pop("AAA")  # both stops fired; both positions are flat
    broker._positions.pop("BBB")
    broker._broker_fills = [
        BrokerFill(
            order_id="stop-aaa", symbol="AAA", side="sell", quantity=10.0, price=51.0, filled_at=now
        ),
        BrokerFill(
            order_id="stop-bbb", symbol="BBB", side="sell", quantity=20.0, price=76.0, filled_at=now
        ),
    ]

    absorbed = await oms.absorb_broker_fills()

    assert len(absorbed) == 2, f"{len(absorbed)} fills for two distinct orders - one was dropped"
    by_symbol = {f.symbol: f for f in absorbed}
    assert by_symbol["AAA"].quantity == pytest.approx(10.0)
    assert by_symbol["AAA"].price == pytest.approx(51.0)
    assert by_symbol["BBB"].quantity == pytest.approx(20.0)
    assert by_symbol["BBB"].price == pytest.approx(76.0)
