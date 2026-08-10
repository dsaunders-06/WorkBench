"""A position opened at the broker while the app was down (M81).

Monday night's startup produced two statements that cannot both be true.

`restore_open_lots` said:

    No entry record for MNST, so no lot could be restored - if these close, the
    exit is absorbed but produces no closed trade and no P&L

and moments later `replay_missed_exits` said:

    BROKER-SIDE FILL absorbed: buy 8 MNST at 91.18 - a resting protective order
    executed, and this is now a closed trade

The second is wrong twice over - a BUY is not a protective order executing, and
nothing was recorded as a closed trade. But the interesting part is that it is
wrong in a way that makes the FIRST statement wrong too: the replay publishes
`OrderFilledEvent(side="buy")`, `TradeLedger` is registered before
`signal_bridge` in the orchestrator's start order and is therefore already
subscribed, and its `_on_fill` opens a lot for any buy.

So MNST does have a lot. The warning that it does not is what an operator would
act on, and it is the opposite of the truth.

The lot it opens is thin, because the absorb path has nothing else to give it:
no `stop_price`, no `strategy`. That decides what tonight's liquidation records
- a closed trade with a correct entry price, no R-multiple, and no strategy to
attribute the outcome to.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _BoughtWhileDownBroker(MockBroker):
    """Holds a position this app never transmitted, with the fill still on the
    recent-fills feed - the state after a hand-placed buy at the broker."""

    def __init__(self) -> None:
        super().__init__(seed=1)
        self._positions["MNST"] = Position(symbol="MNST", quantity=8.0, avg_price=91.18375)
        self._broker_fills.append(
            BrokerFill(
                order_id="35010615-6f66-4e58-8fdb-c43cdb490b68",
                symbol="MNST",
                side="buy",
                quantity=8.0,
                price=91.18375,
                filled_at=datetime(2026, 8, 10, 13, 30, tzinfo=UTC),
            )
        )


async def _replayed(tmp_path) -> TradeLedger:
    """Startup as the orchestrator runs it: ledger subscribed first, then the
    replay publishes into it."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _BoughtWhileDownBroker(),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()  # registered BEFORE signal_bridge in runtime.py
    await oms.adopt_broker_positions()
    # The watermark defaults to NOW on a fresh data dir, which filters the fill
    # out before any of the logic under test runs. In production it was
    # Saturday's persisted value and the fill landed after it - the log records
    # the absorb happening. Wound back so the test exercises the real path
    # rather than the empty one.
    oms._last_fill_scan = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
    await oms.absorb_broker_fills(record_only=True)
    return ledger


@pytest.mark.asyncio
async def test_the_replayed_buy_does_open_a_lot(tmp_path):
    """The warning says no lot could be restored. A lot exists."""
    ledger = await _replayed(tmp_path)

    lots = ledger.open_lots("MNST")

    assert len(lots) == 1, "restore_open_lots skipped it, but the replay opened one anyway"
    assert lots[0].quantity == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_the_lot_carries_the_price_actually_paid(tmp_path):
    """The one thing it gets right, and it matters - this is the broker's own
    fill price, not a reference."""
    ledger = await _replayed(tmp_path)

    assert ledger.open_lots("MNST")[0].price == pytest.approx(91.18375)


@pytest.mark.asyncio
async def test_the_lot_has_no_stop_and_no_strategy(tmp_path):
    """What the absorb path cannot supply, and therefore what tonight's closed
    trade will be missing: no stop means no risk-per-share, so no R-multiple;
    no strategy means the outcome is attributed to nothing and counts towards
    no promotion gate."""
    lot = (await _replayed(tmp_path)).open_lots("MNST")[0]

    assert lot.stop_price is None
    assert lot.strategy is None


@pytest.mark.asyncio
async def test_the_resulting_closed_trade_has_no_r_multiple(tmp_path):
    """The consequence, end to end. The position is liquidated and the trade
    that lands in the record cannot say what it risked."""
    ledger = await _replayed(tmp_path)

    from qat.domain.events import OrderFilledEvent

    await ledger._on_fill(
        OrderFilledEvent(
            order_id="exit-1",
            symbol="MNST",
            side="sell",
            quantity=8.0,
            price=45.43,
            operator="broker (protective order)",
            exit_reason="stop",
        )
    )

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(91.18375)
    assert trades[0].r_multiple is None, "no stop was carried, so R cannot be computed"
    assert trades[0].strategy is None


@pytest.mark.asyncio
async def test_the_quantity_is_not_double_counted(tmp_path):
    """`record_only` exists for this: adoption already took the 8 from the
    broker, and applying the replayed fill again would trip the kill-switch on
    arithmetic (M50)."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _BoughtWhileDownBroker(),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    await oms.adopt_broker_positions()
    # Wound back for the same reason as `_replayed` - without this the fill is
    # filtered out and the test proves nothing by absorbing nothing.
    oms._last_fill_scan = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
    absorbed = await oms.absorb_broker_fills(record_only=True)

    assert [f.symbol for f in absorbed] == ["MNST"], "nothing absorbed - the test is vacuous"
    assert oms._filled_quantities["MNST"] == pytest.approx(8.0)
    assert await oms.check_reconciliation() is False
    assert oms.kill_switch.tripped is False


# --- what the operator is told (M81) ------------------------------------------


@pytest.mark.asyncio
async def test_an_absorbed_buy_is_not_called_a_protective_order(tmp_path, caplog):
    """The message was hard-coded for the sell case M34 was written for, so a
    position opened at the broker was announced as a stop firing."""
    with caplog.at_level("WARNING"):
        await _replayed(tmp_path)

    absorbed = [
        r.getMessage() for r in caplog.records if "BROKER-SIDE FILL absorbed" in r.getMessage()
    ]
    assert absorbed, "nothing absorbed - the test is vacuous"
    assert "protective order executed" not in absorbed[0]
    assert "now a closed trade" not in absorbed[0]
    assert "OPENED at the broker" in absorbed[0]


@pytest.mark.asyncio
async def test_the_absorbed_buy_states_what_the_lot_is_missing(tmp_path, caplog):
    """The operator's next question is what the trade will be worth as
    evidence, and the answer is "less than it looks"."""
    with caplog.at_level("WARNING"):
        await _replayed(tmp_path)

    absorbed = [
        r.getMessage() for r in caplog.records if "BROKER-SIDE FILL absorbed" in r.getMessage()
    ]
    assert "no R-multiple" in absorbed[0]
    assert "promotion evidence" in absorbed[0]


@pytest.mark.asyncio
async def test_a_sell_still_reads_as_a_protective_order_firing(tmp_path, caplog):
    """The fix must not cost M34 its own wording - a stop firing at the broker
    is still the case this path was built for."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _BoughtWhileDownBroker()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    await oms.adopt_broker_positions()
    broker._broker_fills.clear()
    broker.fill_resting_stop("MNST", price=72.68)
    oms._last_fill_scan = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)

    with caplog.at_level("WARNING"):
        await oms.absorb_broker_fills(record_only=True)

    absorbed = [
        r.getMessage() for r in caplog.records if "BROKER-SIDE FILL absorbed" in r.getMessage()
    ]
    assert absorbed, "nothing absorbed - the test is vacuous"
    assert "protective order executed" in absorbed[0]
    assert "now a closed trade" in absorbed[0]
