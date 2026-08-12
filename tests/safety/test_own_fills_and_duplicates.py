"""Two defects that halted the 4 August session (M46).

The app transmitted four entries and, within three seconds, reconciliation
reported every symbol at exactly double the broker's quantity and tripped the
kill-switch:

    AMAT tracked=14 broker=7   AMD tracked=14 broker=7
    GS   tracked=14 broker=7   MS  tracked=164 broker=82

Both causes are here.

* `_orders` is keyed by the app's own order id, but the adapter overwrites
  `order.order_id` with the broker's on transmit. So the "did this app send
  it" test in absorb_broker_fills compared a broker id against a dictionary of
  local ids, never matched, and absorbed every entry fill a second time as
  though a resting protective order had fired.
* The anti-pyramiding guard asked for POSITIONS. A transmitted order that has
  not filled is not a position, so a signal arriving two seconds after MS was
  transmitted opened the same trade again - 82 shares against an intended 41.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _RenamingBroker(MockBroker):
    """Behaves as Alpaca does on the two points that mattered.

    It assigns its OWN order id on transmit, discarding the app's - which is
    what made the "did this app send it" test compare a broker id against a
    dictionary of local ids. And it ACKNOWLEDGES rather than filling, because
    Alpaca acks asynchronously: on 4 August MS was transmitted at 14:01:24 and
    filled at 14:01:27, and the duplicate signal arrived at 14:01:26 - inside
    that window, where the order exists and the position does not.
    """

    def __init__(self, *, fills_immediately: bool = False) -> None:
        super().__init__(seed=1)
        self.assigned: list[str] = []
        self._fills_immediately = fills_immediately

    async def place_order(self, order: Order) -> Order:
        placed = await super().place_order(order)
        placed.order_id = f"broker-{len(self.assigned)}"
        self.assigned.append(placed.order_id)
        if not self._fills_immediately and not placed.is_protective_stop:
            placed.status = "transmitted"
        elif placed.status == "filled":
            # Alpaca's closed-order query returns EVERY filled order, including
            # the ones this app sent. That is the mechanism: absorb sees its
            # own entry come back and, unable to recognise the id, counts it a
            # second time. A fake that reported only protective executions
            # could not reproduce the failure at all.
            self._broker_fills.append(
                BrokerFill(
                    order_id=placed.order_id,
                    symbol=placed.symbol,
                    side=placed.side,
                    quantity=placed.quantity,
                    price=placed.filled_price or 0.0,
                    filled_at=datetime.now(UTC),
                )
            )
        return placed


def _candidate(symbol: str = "MS") -> OrderCandidate:
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


def _oms(broker: MockBroker) -> OMS:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    return OMS(broker, RiskEngine(EventBus(), switch, settings=settings), switch, bus=EventBus())


# --- The app's own fills must never be absorbed as foreign --------------------


@pytest.mark.asyncio
async def test_an_own_fill_is_not_counted_twice_when_the_broker_renames_it():
    """The exact 4 August failure. sign_off counts the fill; absorb must then
    recognise the broker's id as one this app produced."""
    broker = _RenamingBroker(fills_immediately=True)
    oms = _oms(broker)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "operator")
    tracked_after_signoff = oms._filled_quantities.get("MS", 0.0)

    await oms.absorb_broker_fills()

    assert oms._filled_quantities.get("MS", 0.0) == tracked_after_signoff


@pytest.mark.asyncio
async def test_reconciliation_stays_clean_after_transmitting_an_entry():
    """The consequence that actually stopped the session."""
    broker = _RenamingBroker(fills_immediately=True)
    oms = _oms(broker)
    await oms.adopt_broker_positions()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "operator")

    assert await oms.check_reconciliation() is False
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_a_genuinely_foreign_fill_is_still_absorbed():
    """The fix must not close the door M34 opened - a protective order firing
    at the broker still has to be recorded."""
    broker = _RenamingBroker(fills_immediately=True)
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "operator")

    # The watermark is stamped `now()` when the OMS is built with no state file,
    # and `recent_fills` filters STRICTLY greater. Everything above can finish
    # inside one clock tick - measured here at ~1ms, with 20,000 now() calls
    # yielding 10 distinct values - and then `filled_at == since` and the fill
    # this test exists to see is dropped. That is the CI failure of 12 August
    # (run 31561345567), which passed on every other run and never locally.
    # Moving the watermark is right where loosening the filter to `>=` would be
    # wrong: a simulator that answers more fully than the broker hides bugs
    # rather than reproducing them, which is this file's whole premise.
    oms._last_fill_scan -= timedelta(milliseconds=1)

    broker.fill_resting_stop("MS", price=196.93)
    absorbed = await oms.absorb_broker_fills()

    assert [f.symbol for f in absorbed] == ["MS"]
    assert absorbed[0].side == "sell"


# --- A committed order blocks a second entry ---------------------------------


@pytest.mark.asyncio
async def test_a_transmitted_order_blocks_a_second_buy_before_it_fills():
    """Two seconds separated MS being transmitted and the next signal. The
    broker had no position yet, so the guard saw nothing."""
    broker = _RenamingBroker()  # acknowledges, does not fill - as Alpaca does
    oms = _oms(broker)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    signed = await oms.sign_off(order.order_id, "operator")

    assert signed.status == "transmitted", "the window this guard exists for"
    assert oms.has_live_buy("MS") is True


@pytest.mark.asyncio
async def test_an_order_awaiting_sign_off_also_blocks_a_second_buy():
    """The same reasoning the governor already applies to exposure: committed
    is committed, whether or not it has been transmitted."""
    oms = _oms(MockBroker(seed=1))

    await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.has_live_buy("MS") is True


@pytest.mark.asyncio
async def test_a_different_symbol_is_not_blocked():
    oms = _oms(MockBroker(seed=1))

    await oms.submit_order(_candidate("MS"), 100_000.0, {}, {})

    assert oms.has_live_buy("GS") is False


@pytest.mark.asyncio
async def test_a_rejected_order_does_not_block_the_symbol_forever():
    """Only live orders count. A refusal must not lock a symbol out."""
    oms = _oms(MockBroker(seed=1))
    rejected = oms._new_rejected_order_for("MS", "buy", 0.0, "refused")

    assert rejected.status == "rejected"
    assert oms.has_live_buy("MS") is False


@pytest.mark.asyncio
async def test_a_sell_does_not_block_a_buy_or_the_reverse():
    """The account must always be able to de-risk."""
    broker = MockBroker(seed=1)
    broker._positions["MS"] = Position(symbol="MS", quantity=41.0, avg_price=213.70)
    oms = _oms(broker)

    await oms.submit_exit_order("MS", quantity=41.0, price=213.70)

    assert oms.has_live_buy("MS") is False
