"""A lot opened LIVE must learn what it actually paid (M70).

M65 fixed the half that could be healed at startup. This is the half that
cannot be.

`OMS._announce_fill` publishes when an order reaches "filled" OR "transmitted",
taking `order.filled_price or order.reference_price`. Alpaca returns "filled"
only on a same-second fill; anything queued, slow or partial acknowledges as
"transmitted", where there is no fill price - so the REFERENCE is published, and
two subscribers build on it:

* `SignalToOrderBridge._on_fill` stores it with `setdefault`, so the genuine
  price can never replace it.
* `TradeLedger._on_fill` opens the lot at it, and derives `entry_cost` and the
  excursion seeds from it.

`reconcile_entry_prices` heals both at the NEXT startup. A position opened and
closed inside one session never reaches that startup: its ClosedTrade is already
written, with a cost basis the account never paid. That is the case the M65 fix
structurally cannot reach, and it is the case that writes the record.

The true price is already in the building. `recent_fills` returns every filled
order for a tracked symbol carrying `filled_avg_price`, and
`_symbols_to_watch_for_fills` includes anything with an order in flight - so the
app's own entry comes back on the next poll and is discarded at
`_is_foreign_unrecorded`, because it is ours. The fix stops discarding it.

A second consequence, which nothing looks broken about: `entry_slippage` is
`entry_price - reference_price`, and for a live-opened lot both were set from
the same transmit-time announcement. It read zero by construction, on every
entry this app has ever opened - and it is the instrument M44 is scheduled to
measure the cost model with in September.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

# AMD, the live case: sized against 503.16, filled at 510.267 - 141 bps.
_SIZED_AT = 503.16
_PAID = 510.267


class _AcknowledgingBroker(MockBroker):
    """Alpaca on an entry that does not fill in the same second.

    It assigns its own order id, ACKNOWLEDGES rather than filling, and reports
    the execution later through `recent_fills` at a price of its own choosing.
    `MockBroker` fills synchronously, which is precisely the case where the
    defect does not appear - `order.filled_price` is set, so the announcement
    carries the real price and there is nothing to correct.
    """

    def __init__(self) -> None:
        super().__init__(seed=1)
        self._assigned = 0

    async def place_order(self, order: Order) -> Order:
        if order.is_protective_stop:
            return await super().place_order(order)
        self._assigned += 1
        order.order_id = f"broker-{self._assigned}"
        order.status = "transmitted"
        order.filled_price = None  # there is no fill price yet. That is the point.
        self._orders[order.order_id] = order
        return order

    def complete(self, symbol: str, price: float, quantity: float | None = None) -> None:
        """The acknowledged order executes, at a price the app did not choose.

        One row per order carrying the CUMULATIVE average, which is how Alpaca
        reports a partial that later completes - not two rows. And the row keeps
        the FIRST execution's `filled_at`, which is the behaviour
        `_fill_query_floor` exists for: the stamp is already behind the
        watermark by the time the remainder completes, so a window bounded on
        the watermark excludes the very row whose price is still moving.
        """
        order = next(o for o in self._orders.values() if o.symbol == symbol and o.side == "buy")
        filled = order.quantity if quantity is None else quantity
        self._positions[symbol] = Position(symbol=symbol, quantity=filled, avg_price=price)
        existing = next((f for f in self._broker_fills if f.order_id == order.order_id), None)
        self._broker_fills = [f for f in self._broker_fills if f.order_id != order.order_id]
        self._broker_fills.append(
            BrokerFill(
                order_id=order.order_id,
                symbol=symbol,
                side="buy",
                quantity=filled,
                price=price,
                filled_at=existing.filled_at if existing else datetime.now(UTC),
            )
        )


def _candidate(symbol: str = "AMD") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=_SIZED_AT,
        atr=14.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.01, -0.01] * 30),
        strategy="swing",
    )


async def _opened(tmp_path, broker: _AcknowledgingBroker):
    """An entry transmitted and acknowledged, with bridge and ledger listening.

    One bus for all three, as `runtime.py` wires it - a ledger on its own bus
    would never see the correction, and would pass this suite while failing in
    the app.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings, trade_ledger=ledger)
    # The ledger through its own start(), so its wiring is exercised rather
    # than assumed. The bridge's handlers are subscribed directly because
    # start() also rebuilds the ledger and launches the sweep, which this is
    # not testing - test_start_subscribes_the_correction covers that seam.
    await ledger.start()
    bus.subscribe(OrderFilledEvent, bridge._on_fill)
    bus.subscribe(EntryPriceCorrectedEvent, bridge._on_entry_price_corrected)
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.status == "transmitted", "the window this whole defect lives in"
    return oms, bridge, ledger


# --- the entry record ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_recorded_entry_price_is_corrected_when_the_fill_arrives(tmp_path):
    """The defect, end to end. Announced at what it was sized against; the
    broker then says what it charged."""
    broker = _AcknowledgingBroker()
    _, bridge, _ = await _opened(tmp_path, broker)
    assert bridge._entries["AMD"].price == pytest.approx(_SIZED_AT), "announced at the reference"

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    assert bridge._entries["AMD"].price == pytest.approx(_PAID)


@pytest.mark.asyncio
async def test_the_correction_is_persisted(tmp_path):
    """`_entries` is the file `restore_open_lots` rebuilds the ledger from. A
    correction held only in memory would be lost by the restart that is
    supposed to be the backstop."""
    broker = _AcknowledgingBroker()
    _, bridge, _ = await _opened(tmp_path, broker)

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    reloaded = SignalToOrderBridge(
        bus=EventBus(),
        oms=bridge.oms,
        settings=Settings(_env_file=None, data_dir=str(tmp_path)),
    )
    assert reloaded._entries["AMD"].price == pytest.approx(_PAID)


@pytest.mark.asyncio
async def test_the_stop_and_the_open_date_are_left_alone(tmp_path):
    """Only the price was ever wrong. The stop is the level the risk budget was
    spent on, and the open date drives the churn rails."""
    broker = _AcknowledgingBroker()
    _, bridge, _ = await _opened(tmp_path, broker)
    before = bridge._entries["AMD"]

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    after = bridge._entries["AMD"]
    assert after.stop_price == before.stop_price
    assert after.opened_at == before.opened_at
    assert after.strategy == before.strategy


# --- the open lot -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_open_lot_learns_the_price_it_was_opened_at(tmp_path):
    """The lot is what becomes a ClosedTrade. Correcting the entry record and
    leaving the lot alone would fix the file and still write the wrong trade."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)
    assert ledger.open_lots("AMD")[0].price == pytest.approx(_SIZED_AT)

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    assert ledger.open_lots("AMD")[0].price == pytest.approx(_PAID)


@pytest.mark.asyncio
async def test_the_entry_cost_is_recomputed_from_the_price_actually_paid(tmp_path):
    """`entry_cost` is derived from the price, so a corrected price with a
    stale cost is a trade whose commission belongs to a different fill."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)
    lot = ledger.open_lots("AMD")[0]

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    corrected = ledger.open_lots("AMD")[0]
    assert corrected.entry_cost == pytest.approx(ledger._fill_cost(lot.quantity, _PAID))


@pytest.mark.asyncio
async def test_the_excursion_seeds_do_not_keep_a_price_that_never_traded(tmp_path):
    """`worst_price` and `best_price` are seeded from the entry, so an
    uncorrected seed puts a price the market never printed into MAE and MFE."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    lot = ledger.open_lots("AMD")[0]
    assert lot.worst_price == pytest.approx(_PAID)
    assert lot.best_price == pytest.approx(_PAID)


@pytest.mark.asyncio
async def test_entry_slippage_stops_being_zero_by_construction(tmp_path):
    """The consequence M44 is scheduled to measure with. Before this, the
    lot's price and its reference were the same number, so the instrument read
    zero on every entry the app opened - a fabricated result, not a measured
    one."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    lot = ledger.open_lots("AMD")[0]
    assert lot.reference_price == pytest.approx(_SIZED_AT)
    assert lot.price - lot.reference_price == pytest.approx(_PAID - _SIZED_AT)


# --- what must NOT happen -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_quantity_is_not_counted_twice(tmp_path):
    """The M46 failure, which is what makes re-publishing OrderFilledEvent the
    wrong shape for this: sign_off already counted the fill."""
    broker = _AcknowledgingBroker()
    oms, bridge, _ = await _opened(tmp_path, broker)
    tracked = oms._filled_quantities.get("AMD", 0.0)

    broker.complete("AMD", price=_PAID)
    await oms.absorb_broker_fills()

    assert oms._filled_quantities.get("AMD", 0.0) == pytest.approx(tracked)


@pytest.mark.asyncio
async def test_a_second_lot_is_not_opened(tmp_path):
    """The other half of the same reason. The ledger opens a lot per buy event,
    so a correction shaped as a fill would double the position on the tab that
    reports it."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)

    broker.complete("AMD", price=_PAID)
    await bridge.oms.absorb_broker_fills()

    assert len(ledger.open_lots("AMD")) == 1


@pytest.mark.asyncio
async def test_reconciliation_stays_clean(tmp_path):
    """A correction that trips the kill-switch would be worse than the defect."""
    broker = _AcknowledgingBroker()
    oms, _, _ = await _opened(tmp_path, broker)
    broker.complete("AMD", price=_PAID)

    await oms.absorb_broker_fills()

    assert await oms.check_reconciliation() is False
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_a_price_that_matches_corrects_nothing(tmp_path):
    """The quiet path stays quiet. An order that filled at what it was sized
    against needs no correction, and a log line per poll would be noise."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)

    broker.complete("AMD", price=_SIZED_AT)
    corrected = await bridge.oms.absorb_broker_fills()

    assert corrected == []
    assert bridge._entries["AMD"].price == pytest.approx(_SIZED_AT)
    assert ledger.open_lots("AMD")[0].price == pytest.approx(_SIZED_AT)


@pytest.mark.asyncio
async def test_a_quarantined_position_is_never_corrected(tmp_path):
    """The same rule `reconcile_entry_prices` applies. A corporate action
    changes what the broker reports legitimately, and M60 exists to stop
    anything writing to a position in that state."""
    broker = _AcknowledgingBroker()
    oms, bridge, _ = await _opened(tmp_path, broker)
    oms.anomalies.declare(
        symbol="AMD",
        reason="2-for-1 split",
        declared_by="operator",
        tracked_quantity=7.0,
        broker_quantity=14.0,
    )

    broker.complete("AMD", price=_PAID)
    await oms.absorb_broker_fills()

    assert bridge._entries["AMD"].price == pytest.approx(_SIZED_AT)


@pytest.mark.asyncio
async def test_a_genuinely_foreign_fill_is_still_absorbed(tmp_path):
    """The door M34 opened must stay open. A resting stop firing at the broker
    is still a closed trade, and this change edits the branch that decides."""
    broker = _AcknowledgingBroker()
    oms, _, _ = await _opened(tmp_path, broker)
    broker.complete("AMD", price=_PAID)
    await oms.absorb_broker_fills()
    # Successive polls are minutes apart in the app and microseconds apart
    # here, and the broker's window is exclusive - so the watermark is stepped
    # back to stand for the gap rather than sleeping through it.
    oms._last_fill_scan -= timedelta(seconds=1)

    broker.fill_resting_stop("AMD", price=470.11)
    absorbed = await oms.absorb_broker_fills()

    assert [f.symbol for f in absorbed] == ["AMD"]
    assert absorbed[0].side == "sell"


@pytest.mark.asyncio
async def test_a_repeated_poll_corrects_once(tmp_path):
    """`_fill_query_floor` reaches back past remembered fills, so the same
    execution is seen again. Correcting on every sight of it would rewrite the
    record - and log - forever."""
    broker = _AcknowledgingBroker()
    _, bridge, _ = await _opened(tmp_path, broker)
    broker.complete("AMD", price=_PAID)

    first = await bridge.oms.absorb_broker_fills()
    second = await bridge.oms.absorb_broker_fills()

    assert first == [] and second == []
    assert bridge._entries["AMD"].price == pytest.approx(_PAID)


@pytest.mark.asyncio
async def test_start_subscribes_the_correction(tmp_path):
    """The seam the behaviour tests subscribe by hand. A handler nothing wires
    up is the M45 pattern - configuration that persists, displays and changes
    nothing - and it would pass every test above."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _AcknowledgingBroker()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings)
    ledger = TradeLedger(bus, tmp_path, settings=settings)

    await bridge.start()
    await ledger.start()
    try:
        wired = bus._handlers.get(EntryPriceCorrectedEvent, [])
        assert bridge._on_entry_price_corrected in wired
        assert ledger._on_entry_price_corrected in wired
    finally:
        await bridge.stop()
        await ledger.stop()

    assert bus._handlers.get(EntryPriceCorrectedEvent, []) == []


@pytest.mark.asyncio
async def test_a_partial_that_completes_ends_on_the_final_average(tmp_path):
    """Alpaca reports one row per order carrying the cumulative average, so a
    partial corrects to the average so far and the completion corrects again.
    Guarding on difference rather than on having-corrected-once is what makes
    that fall out."""
    broker = _AcknowledgingBroker()
    _, bridge, ledger = await _opened(tmp_path, broker)
    quantity = ledger.open_lots("AMD")[0].quantity

    broker.complete("AMD", price=508.00, quantity=quantity / 2)
    await bridge.oms.absorb_broker_fills()
    assert bridge._entries["AMD"].price == pytest.approx(508.00)

    broker.complete("AMD", price=_PAID, quantity=quantity)
    await bridge.oms.absorb_broker_fills()

    assert bridge._entries["AMD"].price == pytest.approx(_PAID)
    assert ledger.open_lots("AMD")[0].price == pytest.approx(_PAID)
