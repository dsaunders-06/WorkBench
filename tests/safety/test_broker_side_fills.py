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

import json
import logging
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
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
async def test_an_adopted_position_stopping_out_becomes_a_closed_trade(tmp_path):
    """M49, end to end and the whole point of the trial. Absorbing the fill was
    never enough: the ledger matches a sell against an ENTRY LOT, and lots were
    in memory only, so every position - all of which were opened in earlier
    sessions - closed into nothing. The counter could not move off zero."""
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "OLD": {
                    "opened_at": "2026-07-20T00:00:00+00:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "target_price": 60.0,
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    broker._resting_stops["OLD"] = 45.0
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    bridge = SignalToOrderBridge(bus, oms, settings=settings, trade_ledger=ledger)
    await oms.adopt_broker_positions()
    await bridge.restore_open_lots()
    oms._last_fill_scan -= timedelta(seconds=1)

    broker.fill_resting_stop("OLD", price=44.80)
    await oms.check_reconciliation()

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(50.0)
    assert trades[0].exit_price == pytest.approx(44.80)
    # Attributed, or the per-strategy promotion gate still counts nothing.
    assert trades[0].strategy == "swing"
    assert switch.tripped is False


def _entries_file(tmp_path, symbol: str = "OLD") -> None:
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                symbol: {
                    "opened_at": "2026-07-20T00:00:00+00:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "target_price": 60.0,
                    "strategy": "swing",
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_a_stop_that_fired_while_the_app_was_down_becomes_a_closed_trade(tmp_path):
    """M50, and the whole point of it. The watermark started at construction, so
    a fill from before this process existed was never asked for - and adoption
    re-baselines what is HELD while saying nothing about what closed. The trade
    was simply gone."""
    _entries_file(tmp_path)
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")

    # --- session one: the app runs, then stops -----------------------------
    bus_one = EventBus()
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    broker._resting_stops["OLD"] = 45.0
    oms_one = OMS(
        broker,
        RiskEngine(bus_one, KillSwitch(), settings=settings),
        KillSwitch(),
        bus=bus_one,
        settings=settings,
    )
    await oms_one.adopt_broker_positions()
    await oms_one.absorb_broker_fills()  # persists the watermark
    assert (tmp_path / "absorbed_fills.json").exists()
    # A second of session one elapsing before it stopped. Without this the
    # watermark and the fill below land in the same clock tick - Windows'
    # resolution is coarse enough that they do - and the fill reads as older
    # than the last scan, which no real five-minute cadence ever produces.
    oms_one._last_fill_scan -= timedelta(seconds=1)
    oms_one._save_fill_state()

    # --- the app is not running, and the stop fires ------------------------
    broker.fill_resting_stop("OLD", price=44.80)
    assert await broker.positions() == []

    # --- session two: a fresh process, same account ------------------------
    bus_two = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus_two, tmp_path, settings=settings)
    await ledger.start()
    oms_two = OMS(
        broker,
        RiskEngine(bus_two, switch, settings=settings),
        switch,
        bus=bus_two,
        settings=settings,
    )
    bridge = SignalToOrderBridge(bus_two, oms_two, settings=settings, trade_ledger=ledger)
    await oms_two.adopt_broker_positions()
    replayed = await bridge.replay_missed_exits()

    assert replayed == ["OLD"]
    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].exit_price == pytest.approx(44.80)
    assert trades[0].entry_price == pytest.approx(50.0)
    assert trades[0].strategy == "swing"
    # The exit is stamped when it FILLED, not when it was noticed.
    assert trades[0].closed_at > trades[0].opened_at

    # And the arithmetic is untouched: adoption already read the post-exit book.
    assert await oms_two.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_replayed_exit_is_not_recorded_twice_by_the_next_restart(tmp_path):
    """The watermark alone cannot say whether a fill on its boundary was already
    recorded. Recording a closed trade twice would inflate the very count the
    promotion gate reads, so the absorbed ids are remembered too."""
    _entries_file(tmp_path)
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    broker._resting_stops["OLD"] = 45.0

    bus_one = EventBus()
    oms_one = OMS(
        broker,
        RiskEngine(bus_one, KillSwitch(), settings=settings),
        KillSwitch(),
        bus=bus_one,
        settings=settings,
    )
    await oms_one.adopt_broker_positions()
    await oms_one.absorb_broker_fills()
    oms_one._last_fill_scan -= timedelta(seconds=1)  # see the note on clock granularity above
    oms_one._save_fill_state()
    broker.fill_resting_stop("OLD", price=44.80)

    async def _one_session() -> int:
        bus = EventBus()
        switch = KillSwitch()
        ledger = TradeLedger(bus, tmp_path, settings=settings)
        await ledger.start()
        oms = OMS(
            broker,
            RiskEngine(bus, switch, settings=settings),
            switch,
            bus=bus,
            settings=settings,
        )
        bridge = SignalToOrderBridge(bus, oms, settings=settings, trade_ledger=ledger)
        await oms.adopt_broker_positions()
        await bridge.replay_missed_exits()
        return len(ledger.closed_trades())

    assert await _one_session() == 1
    # A second restart must find nothing left to replay.
    assert await _one_session() == 1


@pytest.mark.asyncio
async def test_without_a_data_directory_the_previous_behaviour_is_unchanged(tmp_path):
    """No settings means no watermark file, which means no replay - exactly the
    pre-M50 behaviour. Degrading to merely incomplete is the right failure."""
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(broker, RiskEngine(bus, switch), switch, bus=bus)

    assert await oms.missed_fills() == []
    assert not (tmp_path / "absorbed_fills.json").exists()


@pytest.mark.asyncio
async def test_a_position_with_no_entry_record_is_named_not_invented(tmp_path):
    """The broker knows what it paid but not when it was bought. A fabricated
    open date would put invented holding periods into the evidence the trial
    exists to produce, so the position is skipped and said out loud."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    broker = MockBroker(seed=1)
    broker._positions["MYSTERY"] = Position(symbol="MYSTERY", quantity=5.0, avg_price=10.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    bridge = SignalToOrderBridge(bus, oms, settings=settings, trade_ledger=ledger)

    with caplog_at_warning() as records:
        restored = await bridge.restore_open_lots()

    assert restored == []
    assert ledger.open_lots() == []
    assert any("MYSTERY" in r.getMessage() for r in records)


@contextmanager
def caplog_at_warning():
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector(level=logging.WARNING)
    logger = logging.getLogger("qat.domain.oms.signal_bridge")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


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
async def test_an_order_that_fills_in_pieces_is_counted_in_full():
    """M53, and it halted a live session. A CVS stop gapped through at the open
    and filled 47 shares in pieces. The app read it mid-fill, absorbed 30,
    recorded the id as done, and never counted the remaining 17 - because the
    dedupe asked "have I seen this id" when the question is "has anything new
    executed". Tracked 17 against a broker holding 0 is a discrepancy, and
    reconciliation answered it with the kill-switch."""
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    broker = MockBroker(seed=1)
    broker._positions["AAA"] = Position(symbol="AAA", quantity=47.0, avg_price=105.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    await oms.adopt_broker_positions()
    oms._last_fill_scan -= timedelta(seconds=1)

    # The broker reports cumulative filled_qty and a cumulative average price.
    partial = BrokerFill(
        order_id="stop-1",
        symbol="AAA",
        side="sell",
        quantity=30.0,
        price=95.0,
        filled_at=datetime.now(UTC),
    )
    complete = replace(partial, quantity=47.0, price=96.0)

    broker._broker_fills = [partial]
    broker._positions["AAA"] = Position(symbol="AAA", quantity=17.0, avg_price=105.0)
    assert len(await oms.absorb_broker_fills()) == 1
    assert oms._filled_quantities["AAA"] == pytest.approx(17.0)

    broker._broker_fills = [complete]
    broker._positions.pop("AAA")  # the rest fills and the account goes flat
    rest = await oms.absorb_broker_fills()

    assert len(rest) == 1
    assert rest[0].quantity == pytest.approx(17.0), "only the NEW shares"
    # The increment's own price, recovered from the two running averages -
    # (96*47 - 95*30)/17 - not the blended average, which would misstate P&L.
    assert rest[0].price == pytest.approx((96.0 * 47 - 95.0 * 30) / 17)
    assert oms._filled_quantities["AAA"] == pytest.approx(0.0)
    assert await oms.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_pre_m53_fill_record_is_not_re_absorbed(tmp_path):
    """The migration hazard, and it is the dangerous direction.

    M50 stored a timestamp per order id and no quantity. Reading that as "zero
    absorbed" makes the WHOLE order eligible again - and the file written on
    5 August holds a 47-share CVS stop of which 30 were already recorded. Counted
    twice, tracked goes to -47, a duplicate closed trade is written, and the
    kill-switch trips. That is M46 arriving through the migration of the fix for
    M50."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    filled_at = datetime.now(UTC) - timedelta(minutes=5)
    # Byte-for-byte the shape the live file was in.
    (tmp_path / "absorbed_fills.json").write_text(
        json.dumps(
            {
                "watermark": (filled_at + timedelta(seconds=56)).isoformat(),
                "absorbed": {"stop-1": filled_at.isoformat()},
            }
        ),
        encoding="utf-8",
    )
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._broker_fills = [
        BrokerFill(
            order_id="stop-1",
            symbol="AAA",
            side="sell",
            quantity=47.0,
            price=95.36,
            filled_at=filled_at,
        )
    ]
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    oms.watch_symbols_for_fills(["AAA"])
    await oms.adopt_broker_positions()

    assert await oms.absorb_broker_fills() == []
    assert oms._filled_quantities.get("AAA", 0.0) == pytest.approx(0.0)
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_fully_absorbed_order_is_never_absorbed_again():
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    broker = MockBroker(seed=1)
    broker._positions["AAA"] = Position(symbol="AAA", quantity=10.0, avg_price=100.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    await oms.adopt_broker_positions()
    oms._last_fill_scan -= timedelta(seconds=1)
    broker._broker_fills = [
        BrokerFill(
            order_id="stop-1",
            symbol="AAA",
            side="sell",
            quantity=10.0,
            price=95.0,
            filled_at=datetime.now(UTC),
        )
    ]

    assert len(await oms.absorb_broker_fills()) == 1
    assert await oms.absorb_broker_fills() == []
    assert oms._filled_quantities["AAA"] == pytest.approx(0.0)


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
