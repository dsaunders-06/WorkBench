"""A protective order firing must not look like a discrepancy (M34).

Every closed trade this system will ever produce comes from a stop, a target,
or the time stop, and two of those three execute entirely at the broker. No
order leaves this process, so nothing publishes OrderFilledEvent.

Two things followed from that, and both bite on the first day a stop fires:

* `check_reconciliation` compares tracked quantity against the broker's and
  trips the kill-switch on any divergence - so a stop doing exactly its job
  halts the session.
* The trade ledger subscribes to OrderFilledEvent, so the closed trade is
  never recorded. The Performance tab stays empty and the promotion gate
  accumulates nothing from the only exits this system has.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _candidate(symbol: str = "AAA", price: float = 100.0) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=price,
        atr=2.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.01, -0.01] * 30),
        strategy="swing",
    )


async def _opened_position(
    bus: EventBus, ledger: TradeLedger | None = None
) -> tuple[MockBroker, OMS]:
    """A position opened THROUGH the app, so the ledger holds an open lot.

    The ledger has to be listening before the buy or there is nothing for the
    later sell to close against - FIFO matching needs the entry.
    """
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    if ledger is not None:
        await ledger.start()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "operator")
    await oms.adopt_broker_positions()
    return broker, oms


@pytest.mark.asyncio
async def test_a_stop_firing_does_not_trip_the_kill_switch():
    """The rail was correct and the conclusion was wrong: a position that
    closed because its stop worked is not a broker discrepancy."""
    bus = EventBus()
    broker, oms = await _opened_position(bus)

    broker.fill_resting_stop("AAA", price=95.0)
    mismatch = await oms.check_reconciliation()

    assert mismatch is False
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_a_broker_side_fill_becomes_a_closed_trade():
    """The half that matters more. Without this the ledger stays empty, so the
    promotion gate never accumulates evidence from the only exits there are."""
    bus = EventBus()
    ledger = TradeLedger(bus, tempfile.mkdtemp())
    broker, oms = await _opened_position(bus, ledger)

    broker.fill_resting_stop("AAA", price=95.0)
    await oms.check_reconciliation()

    closed = ledger.closed_trades()
    assert len(closed) == 1
    assert closed[0].symbol == "AAA"
    assert closed[0].exit_price == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_the_recorded_exit_price_is_the_real_fill_not_the_stop_level():
    """A stop fills at or below its trigger and a target at or above its
    limit, so using the level as a proxy would put a wrong number into every
    realised P&L the promotion gate reads."""
    bus = EventBus()
    ledger = TradeLedger(bus, tempfile.mkdtemp())
    broker, oms = await _opened_position(bus, ledger)

    broker.fill_resting_stop("AAA", price=92.15)  # gapped through the stop
    await oms.check_reconciliation()

    assert ledger.closed_trades()[0].exit_price == pytest.approx(92.15)


@pytest.mark.asyncio
async def test_the_fill_query_asks_about_what_the_APP_tracks_not_what_the_broker_holds():
    """M48. A stop firing is precisely the event that removes the position from
    the broker's list, so bounding the question by the broker's holdings would
    exclude the one symbol we need to hear about - the same shape of mistake as
    bounding the protection query by `status=open`."""
    bus = EventBus()
    broker, oms = await _opened_position(bus)
    asked: list[list[str] | None] = []
    inner = broker.recent_fills

    async def _record(since, symbols=None):
        asked.append(symbols)
        return await inner(since, symbols)

    broker.recent_fills = _record  # type: ignore[assignment]
    oms._last_fill_scan -= timedelta(seconds=1)  # see the note on clock granularity below

    broker.fill_resting_stop("AAA", price=95.0)
    assert await broker.positions() == [], "the broker no longer holds it"

    await oms.check_reconciliation()

    assert asked and asked[0] is not None
    assert "AAA" in asked[0], "the symbol whose position just vanished must still be asked about"
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_an_adopted_position_stopping_out_is_absorbed():
    """The case the old window could never return. An adopted position's
    protection was placed in an earlier session, so its `submitted_at` is days
    old - and the query bounded on submitted_at asked only about the last five
    minutes."""
    bus = EventBus()
    ledger = TradeLedger(bus, tempfile.mkdtemp())
    await ledger.start()
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    # Held before this process existed, protected by an order it never sent.
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    broker._resting_stops["OLD"] = 45.0
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    await oms.adopt_broker_positions()
    # Windows' clock granularity is coarse enough that construction and the
    # fill below can land on the same microsecond, and the watermark is
    # deliberately exclusive. Rewinding it puts the fill unambiguously inside
    # the window, which is what five minutes of a real session does.
    oms._last_fill_scan -= timedelta(seconds=1)

    broker.fill_resting_stop("OLD", price=44.80)
    mismatch = await oms.check_reconciliation()

    assert mismatch is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_fill_this_app_sent_is_not_counted_twice():
    """sign_off already counted it. Counting it again would create exactly the
    discrepancy this exists to prevent."""
    bus = EventBus()
    _, oms = await _opened_position(bus)
    tracked_before = dict(oms._filled_quantities)

    await oms.absorb_broker_fills()

    assert oms._filled_quantities == tracked_before


@pytest.mark.asyncio
async def test_the_same_fill_is_absorbed_only_once():
    """check_reconciliation runs every poll, forever."""
    bus = EventBus()
    broker, oms = await _opened_position(bus)
    seen: list[OrderFilledEvent] = []
    bus.subscribe(OrderFilledEvent, lambda e: seen.append(e) or None)

    broker.fill_resting_stop("AAA", price=95.0)
    for _ in range(4):
        await oms.check_reconciliation()

    assert len([e for e in seen if e.side == "sell"]) == 1
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_a_genuine_discrepancy_still_trips():
    """The rail has to keep working. A position that appears at the broker
    with no fill to explain it is exactly what reconciliation is for."""
    bus = EventBus()
    broker, oms = await _opened_position(bus)

    # Someone else buys into the account - no fill record, no explanation.
    broker._positions["ZZZ"] = broker._positions["AAA"].__class__(
        symbol="ZZZ", quantity=10.0, avg_price=50.0
    )
    mismatch = await oms.check_reconciliation()

    assert mismatch is True
    assert oms.kill_switch.tripped is True


@pytest.mark.asyncio
async def test_a_broker_that_cannot_report_fills_behaves_exactly_as_before():
    class _NoFills(MockBroker):
        recent_fills = None  # type: ignore[assignment]

    settings = Settings(_env_file=None)
    switch = KillSwitch()
    bus = EventBus()
    broker = _NoFills(seed=1)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)

    assert await oms.absorb_broker_fills() == []
