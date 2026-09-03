"""An app-transmitted SELL must learn what it actually filled at (M71).

M70 fixed the buy side: `OMS._correct_announced_price` compares the broker's
real fill against what `_announce_fill` published at transmit (the price the
order was SIZED against, because there is no fill price yet) and corrects it.
That method opened with `raw.side != "buy"` and `order.side != "buy"` guards -
deliberately skipping sells, because a sell closes the position rather than
leaving an open lot to rebase, and by the time the true fill arrives the
`ClosedTrade` is already written to `closed_trades.csv`.

This is the other half. `_correct_announced_price` now handles both sides:
a sell mismatch publishes `ExitPriceCorrectedEvent`, and `TradeLedger` amends
the row already on disk - write-then-heal, matched exactly on the order id
`ClosedTrade` now carries.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_ENTRY = 100.0
_STOP = 90.0
# The exit's reference price - what the sell was SIZED against at transmit.
_SIZED_AT = 110.0
# What the broker actually paid.
_PAID = 115.0


# Far enough back that any real `datetime.now(UTC)` fill is strictly after it.
_WATERMARK_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class _ExitAcknowledgingBroker(MockBroker):
    """Alpaca on an exit that does not fill in the same second - the sell
    twin of `_AcknowledgingBroker` in test_live_entry_price_correction.py.

    It assigns its own order id, ACKNOWLEDGES rather than filling, and
    reports the execution later through `recent_fills` at a price of its own
    choosing. `MockBroker` fills a sell synchronously, which is precisely the
    case where the defect does not appear.
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
        """The acknowledged sell executes, at a price the app did not choose."""
        order = next(o for o in self._orders.values() if o.symbol == symbol and o.side == "sell")
        filled = order.quantity if quantity is None else quantity
        # Flattens the broker's own position record, the way a real full exit
        # would - so reconciliation compares a closed position against a
        # closed position rather than tripping on this fixture's own state.
        self._positions[symbol] = Position(symbol=symbol, quantity=0.0, avg_price=0.0)
        existing = next((f for f in self._broker_fills if f.order_id == order.order_id), None)
        self._broker_fills = [f for f in self._broker_fills if f.order_id != order.order_id]
        self._broker_fills.append(
            BrokerFill(
                order_id=order.order_id,
                symbol=symbol,
                side="sell",
                quantity=filled,
                price=price,
                filled_at=existing.filled_at if existing else datetime.now(UTC),
            )
        )


async def _opened_position(tmp_path, broker: _ExitAcknowledgingBroker, quantity: float = 10.0):
    """A lot open and ready to close, with OMS and TradeLedger sharing one bus
    - as `runtime.py` wires it, so a ledger on its own bus would pass this
    suite while failing in the app.

    Every OMS here gets its own `data_dir` (a distinct `tmp_path` per test),
    because `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store
    persists there - one declared quarantine would otherwise leak into every
    later test, which the quarantine test below would trip over.
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
        # A FIXED clock in the past, so the fill watermark cannot race the
        # fills. `absorb_broker_fills` stamps `scan_started = self._now()`
        # BEFORE querying, and MockBroker filters `filled_at > since` -
        # STRICTLY greater. The fake stamps its fill with the real
        # `datetime.now(UTC)`, so when the whole test body lands inside one
        # clock tick - Windows resolution is coarse and CI runners are fast -
        # the fill's stamp EQUALS the watermark and is excluded. The correction
        # then never runs and the exit price stays at what it was sized at.
        #
        # That failed in CI on 20 August while passing five times locally.
        # Production is not exposed the same way: a real `filled_at` comes from
        # the broker with microsecond precision and the watermark from the local
        # clock, so exact equality is vanishingly unlikely. This is the test
        # being non-deterministic, not M71 being wrong - so the fix belongs
        # here, and NOT in relaxing the `>` boundary, which would risk
        # re-absorbing a fill already counted.
        clock=lambda: _WATERMARK_EPOCH,
    )
    await ledger.start()
    await bus.publish(
        OrderFilledEvent(
            order_id="entry-1",
            symbol="AAA",
            side="buy",
            quantity=quantity,
            price=_ENTRY,
            stop_price=_STOP,
            strategy="swing",
            # Stamped from the SAME clock the OMS is pinned to (line above:
            # `clock=lambda: _WATERMARK_EPOCH`). This fixture ran two clocks -
            # the OMS at the epoch and the ledger at the wall clock - so its
            # entry was stamped eight months AFTER the exit that closes it.
            # Harmless until `_close_against_lots` began refusing an exit that
            # precedes its lot (24 August 2026), which is a real guard that this
            # fixture was accidentally violating. The scenario under test - a
            # late exit price being corrected on disk - is unchanged.
            ts=_WATERMARK_EPOCH,
        )
    )
    assert ledger.open_lots("AAA"), "the lot must exist before the sell can close it"
    # OMS's own bookkeeping never saw that buy - it was opened directly on the
    # ledger's bus, as a real position from an earlier session would be. Adopt
    # it the same way `runtime.py` does at startup, so reconciliation compares
    # a real baseline instead of tripping on this fixture's own gap.
    broker._positions["AAA"] = Position(symbol="AAA", quantity=quantity, avg_price=_ENTRY)
    await oms.adopt_broker_positions()
    return oms, ledger


async def _sold(oms: OMS, quantity: float = 10.0) -> Order:
    order = await oms.submit_exit_order("AAA", quantity, _SIZED_AT, reason="signal")
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.status == "transmitted", "the window this whole defect lives in"
    return signed


def _rows(tmp_path) -> list[dict[str, str]]:
    with (tmp_path / "closed_trades.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --- the defect, end to end -----------------------------------------------


@pytest.mark.asyncio
async def test_the_recorded_exit_price_is_corrected_on_disk(tmp_path):
    """Announced at what it was sized against; the broker then says what it
    actually paid. The row already on disk must end up corrected, not just
    the in-memory object."""
    broker = _ExitAcknowledgingBroker()
    oms, ledger = await _opened_position(tmp_path, broker)
    await _sold(oms)

    written_wrong = ledger.closed_trades()
    assert len(written_wrong) == 1
    assert written_wrong[0].exit_price == pytest.approx(_SIZED_AT), "the defect, before the fix"
    wrong_r_multiple = written_wrong[0].r_multiple

    broker.complete("AAA", price=_PAID)
    corrected = await oms.absorb_broker_fills()
    assert corrected == [], "an own fill is corrected in place, never re-absorbed as foreign"

    memory = ledger.closed_trades()[0]
    assert memory.exit_price == pytest.approx(_PAID)

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert float(rows[0]["exit_price"]) == pytest.approx(_PAID)
    # abs=0.01: as_row() rounds to 2dp for the CSV, so the disk figure is not
    # bit-identical to the unrounded in-memory one - just equal to it within
    # that rounding.
    assert float(rows[0]["exit_cost"]) == pytest.approx(memory.exit_cost, abs=0.01)
    assert float(rows[0]["r_multiple"]) == pytest.approx(memory.r_multiple, abs=1e-4)
    assert float(rows[0]["r_multiple"]) != pytest.approx(
        wrong_r_multiple
    ), "must actually be recomputed, not merely copied forward"
    assert rows[0]["order_id"] == "broker-1"


# --- what must NOT happen --------------------------------------------------


@pytest.mark.asyncio
async def test_a_price_within_tolerance_amends_nothing(tmp_path):
    """The quiet path stays quiet. An order that filled at what it was sized
    against needs no correction, and a rewrite per poll would be noise - and
    risk."""
    broker = _ExitAcknowledgingBroker()
    oms, ledger = await _opened_position(tmp_path, broker)
    await _sold(oms)

    broker.complete("AAA", price=_SIZED_AT * (1 + 1e-6))
    corrected = await oms.absorb_broker_fills()

    assert corrected == []
    assert ledger.closed_trades()[0].exit_price == pytest.approx(_SIZED_AT)
    assert list(tmp_path.glob("closed_trades.csv.bak-*")) == [], "no backup without an amendment"


@pytest.mark.asyncio
async def test_a_quarantined_symbol_amends_nothing(tmp_path):
    """The same rule the buy path already applies. A corporate action changes
    what the broker reports legitimately, and M60 exists to stop anything
    writing to a position in that state - including a healing amendment."""
    broker = _ExitAcknowledgingBroker()
    oms, ledger = await _opened_position(tmp_path, broker)
    await _sold(oms)
    oms.anomalies.declare(
        symbol="AAA",
        reason="2-for-1 split",
        declared_by="operator",
        tracked_quantity=0.0,
        broker_quantity=0.0,
    )

    broker.complete("AAA", price=_PAID)
    await oms.absorb_broker_fills()

    assert ledger.closed_trades()[0].exit_price == pytest.approx(_SIZED_AT)
    assert list(tmp_path.glob("closed_trades.csv.bak-*")) == []


@pytest.mark.asyncio
async def test_reconciliation_stays_clean(tmp_path):
    """A correction that trips the kill-switch would be worse than the
    defect - the same assertion the buy suite makes."""
    broker = _ExitAcknowledgingBroker()
    oms, _ = await _opened_position(tmp_path, broker)
    await _sold(oms)
    broker.complete("AAA", price=_PAID)

    await oms.absorb_broker_fills()

    assert await oms.check_reconciliation() is False
    assert oms.kill_switch.tripped is False
