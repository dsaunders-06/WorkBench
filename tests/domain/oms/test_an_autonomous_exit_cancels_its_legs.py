"""An autonomous exit left both protective legs resting on a flat position.

⚠️ MEASURED, 4 September 2026. The escaped-hold rule exited A2M.AX through
`signal_bridge`, the sell filled, the position went flat - and both OCA legs
stayed at FULL SIZE:

    RESTING ORDER ORPHAN: A2M.AX SELL resting=9636 justified=0 excess=9636 FLAT
      1216552518 sell LMT 9636@8.08   1216552519 sell STP 9636@6.24 (oca)

A naked short waiting to happen: that stop sat about 4% under the last of 6.47,
well inside a day's range. The resting-order rail found it and NAMED the order
ids, and then the operator cancelled them by hand in TWS - because that rail
says, in its own words, "The ORDERS ARE NOT CANCELLED by this."

⚠️ THE CAREFUL WORK WENT INTO THE PATH A HUMAN DRIVES. `PositionCloser`
(M163) cancels legs, re-reads to prove they are gone, and recovers if the sell
then fails. The autonomous paths - `signal_bridge`'s time stop and signal exits -
called `submit_exit_order` directly and walked away. Those are the exits that
run unattended, which is precisely when nobody is watching the scan.

⚠️ WHY CANCEL FIRST RATHER THAN SELL FIRST, decided on evidence rather than
taste. The two failure modes are not symmetric:

  * cancel first, sell fails -> the position is UNPROTECTED, and
    `verify_position_stops` detects it while `signal_bridge` RE-ARMS it
    automatically ("Proposed protective stops for N unprotected position(s)").
    Self-healing, and the position is one you meant to hold.
  * sell first, cancel fails -> the legs are ORPHANED, detected by a rail with
    no remedy, and if one fills you own an unintended SHORT with no bound.

And if the legs cannot be cancelled at all, this REFUSES TO SELL. The position
then stays fully protected and the exit retries - strictly safer than selling
into resting legs, which is the double-fill this exists to prevent.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountBalances, Order, Position, RestingOrder
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _BrokerWithLegs(MockBroker):
    """A broker holding a position with two resting protective legs."""

    def __init__(self, *, cancel_succeeds: bool = True) -> None:
        super().__init__(seed=1)
        self._legs = [
            RestingOrder(
                order_id="leg-stop",
                symbol="AAA",
                side="sell",
                order_type="STP",
                quantity=100.0,
                limit_price=None,
                stop_price=90.0,
                status="PreSubmitted",
            ),
            RestingOrder(
                order_id="leg-target",
                symbol="AAA",
                side="sell",
                order_type="LMT",
                quantity=100.0,
                limit_price=120.0,
                stop_price=None,
                status="Submitted",
            ),
        ]
        self._cancel_succeeds = cancel_succeeds
        self.cancelled: list[str] = []

    async def account(self) -> AccountBalances:
        return AccountBalances(equity=1_000_000.0, cash=1_000_000.0)

    async def positions(self) -> list[Position]:
        # ⚠️ The broker must really HOLD it, or `_broker_quantity` cannot tell a
        # partial exit from a full one - which is what made the first version of
        # the partial test pass for the wrong reason.
        return [Position(symbol="AAA", quantity=100.0, avg_price=100.0)]

    async def open_orders(self) -> list[RestingOrder]:
        return list(self._legs)

    async def resting_stops(self) -> dict[str, float]:
        """⚠️ DERIVED FROM `_legs`, not a fixed dict, and that is the point.

        `naked_positions` reads THIS, not `open_orders`. A fixture that did not
        model it reported AAA unprotected whether or not the legs were still
        there, so the test asserting the remainder becomes visible passed
        against the unfixed code - vacuous, and in the exact shape this project
        keeps rediscovering: a test asserting ABSENCE must first prove the
        fixture can produce PRESENCE.
        """
        return {
            leg.symbol: leg.stop_price
            for leg in self._legs
            if leg.order_type == "STP" and leg.stop_price is not None
        }

    async def cancel_order(self, order_id: str) -> Order:
        self.cancelled.append(order_id)
        if self._cancel_succeeds:
            self._legs = [leg for leg in self._legs if leg.order_id != order_id]
        return Order(
            order_id=order_id,
            symbol="AAA",
            side="sell",
            quantity=100.0,
            status="cancelled",
        )


def _oms(broker: MockBroker) -> OMS:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    bus = EventBus()
    engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, engine, switch, bus=bus, settings=settings)
    oms._filled_quantities["AAA"] = 100.0
    return oms


@pytest.mark.asyncio
async def test_a_full_exit_cancels_the_protective_legs_first() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR - the A2M orphan."""
    broker = _BrokerWithLegs()
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity=100.0, price=100.0, reason="signal")
    assert broker.cancelled == []
    await oms.sign_off(order.order_id, "test")

    assert sorted(broker.cancelled) == ["leg-stop", "leg-target"]
    assert await broker.open_orders() == []


@pytest.mark.asyncio
async def test_the_exit_is_REFUSED_when_a_leg_will_not_cancel() -> None:
    """⚠️ Fail closed. Selling into a resting leg is the double-fill that turns
    a protected long into a short; refusing leaves the position protected and
    the exit retries on the next tick."""
    broker = _BrokerWithLegs(cancel_succeeds=False)
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity=100.0, price=100.0, reason="signal")
    assert broker.cancelled == []
    order = await oms.sign_off(order.order_id, "test")

    assert order.status == "rejected"
    assert len(await broker.open_orders()) == 2, "the position must stay protected"


@pytest.mark.asyncio
async def test_a_PARTIAL_exit_releases_its_legs_too() -> None:
    """⚠️ REVERSED 9 September, and the reasoning matters more than the change.

    This test previously asserted the OPPOSITE - that a partial exit leaves its
    legs alone, because "the remainder still needs protecting". That is true of
    the INTENT and false of the RESULT: the legs keep the size of the position
    before the trim, so a 100-share bracket now guards a 60-share holding. If
    the stop then fires it sells 100 against 60 held and the account is SHORT 40
    - the same naked short this file exists to prevent, reached by a different
    route and at the worst possible moment, since a stop fires in a falling
    market.

    ⚠️ The de-lever sweep trims EVERY position at once ("trimming every position
    by {fraction:.1%}"), so one breach would leave the whole book over-covered,
    not one symbol.
    """
    broker = _BrokerWithLegs()
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity=40.0, price=100.0, reason="delever")
    assert broker.cancelled == []
    await oms.sign_off(order.order_id, "test")

    assert sorted(broker.cancelled) == ["leg-stop", "leg-target"]
    assert await broker.open_orders() == []


@pytest.mark.asyncio
async def test_the_remainder_of_a_PARTIAL_exit_is_VISIBLE_as_unprotected() -> None:
    """⚠️ THE WHOLE JUSTIFICATION FOR CANCELLING RATHER THAN RESIZING.

    `naked_positions` reports a held position with NO stop resting. It cannot
    see a stop that is merely the WRONG SIZE - that state is invisible to every
    rail in this application. So the two candidate designs fail differently:

      * resize in place, and a failure leaves a stop of the wrong size, which
        nothing detects and nothing heals;
      * cancel, and a failure leaves the position FULLY unprotected - which
        `naked_positions` sees, `verify_position_stops` shouts about, and
        `rearm_protective_stops` fixes on its own at `abs(quantity)`, the
        CURRENT holding, using the recorded entry stop.

    Cancelling fails into the state the system can see. That is the argument.
    """
    broker = _BrokerWithLegs()
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity=40.0, price=100.0, reason="delever")
    await oms.sign_off(order.order_id, "test")

    naked = await oms.naked_positions()

    assert [symbol for symbol, _ in naked] == [
        "AAA"
    ], "the remainder must be detectable as unprotected, or nothing re-arms it"


@pytest.mark.asyncio
async def test_a_symbol_with_no_legs_exits_normally() -> None:
    """The ordinary path must not need a broker that models resting orders."""
    broker = MockBroker(seed=1)
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity=100.0, price=100.0, reason="signal")

    assert order.status != "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [100.0, 40.0])
async def test_halted_exit_preserves_the_existing_bracket(quantity: float) -> None:
    broker = _BrokerWithLegs()
    oms = _oms(broker)
    before = await broker.open_orders()
    assert await broker.resting_stops() == {"AAA": 90.0}
    oms.kill_switch.trip("CE-017 reproduction")

    order = await oms.submit_exit_order("AAA", quantity, 100.0)

    assert order.status == "rejected"
    assert broker.cancelled == []
    assert await broker.open_orders() == before
    assert await broker.resting_stops() == {"AAA": 90.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [0.0, -1.0])
async def test_invalid_exit_quantity_does_not_cancel_protection(quantity: float) -> None:
    broker = _BrokerWithLegs()
    oms = _oms(broker)

    order = await oms.submit_exit_order("AAA", quantity, 100.0)

    assert order.status == "rejected"
    assert broker.cancelled == []
    assert await broker.resting_stops() == {"AAA": 90.0}


@pytest.mark.asyncio
async def test_failed_exit_risk_evaluation_preserves_protection(monkeypatch) -> None:
    broker = _BrokerWithLegs()
    oms = _oms(broker)

    def unavailable(*args):
        raise RuntimeError("risk audit unavailable")

    monkeypatch.setattr(oms.risk_engine, "evaluate_exit", unavailable)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)

    assert order.status == "rejected"
    assert broker.cancelled == []
    assert await broker.resting_stops() == {"AAA": 90.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "cancel", "halt"])
async def test_an_unsigned_exit_keeps_protection_until_authorised(decision: str) -> None:
    broker = _BrokerWithLegs()
    oms = _oms(broker)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    assert order.status == "pending_signoff"
    assert broker.cancelled == []
    assert await broker.resting_stops() == {"AAA": 90.0}

    if decision == "reject":
        await oms.reject_order(order.order_id, "operator", "keep holding")
    elif decision == "cancel":
        await oms.cancel_order(order.order_id)
    else:
        oms.kill_switch.trip("halt while awaiting approval")
        assert (await oms.sign_off(order.order_id, "operator")).status == "rejected"

    assert broker.cancelled == []
    assert await broker.resting_stops() == {"AAA": 90.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("halt_during", ["orders", "positions"])
async def test_halt_during_broker_read_prevents_first_cancel(halt_during, monkeypatch) -> None:
    broker = _BrokerWithLegs()
    oms = _oms(broker)
    original = broker.open_orders if halt_during == "orders" else broker.positions

    async def read_and_halt():
        result = await original()
        oms.kill_switch.trip("halt during exit preparation")
        return result

    monkeypatch.setattr(
        broker, "open_orders" if halt_during == "orders" else "positions", read_and_halt
    )
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    order = await oms.sign_off(order.order_id, "test")

    assert order.status == "rejected"
    assert broker.cancelled == []
    assert await broker.resting_stops() == {"AAA": 90.0}


@pytest.mark.asyncio
async def test_halt_during_an_empty_order_read_still_blocks_transmission(monkeypatch) -> None:
    broker = _BrokerWithLegs()
    broker._legs = []
    oms = _oms(broker)
    transmitted = []

    async def empty_read_and_halt():
        oms.kill_switch.trip("halt during empty broker read")
        return []

    async def record_transmission(order):
        transmitted.append(order)
        return order

    monkeypatch.setattr(broker, "open_orders", empty_read_and_halt)
    monkeypatch.setattr(broker, "place_order", record_transmission)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    signed = await oms.sign_off(order.order_id, "test")

    assert signed.status == "rejected"
    assert transmitted == []
