"""A protective order is sized when PROPOSED and transmitted when SIGNED OFF,
and the position can change in between.

⚠️ MEASURED LIVE, 9 September 2026, and it was a near-miss rather than a loss.
A signal exit on SEK.AX filled in TEN partial executions over 28 seconds. The
app read the position at TWELVE seconds, when 2,030 of 2,978 had filled:

    SEK.AX partially exited - keeping its entry record for the shares that remain
    Protective OCO proposed for unprotected position SEK.AX x948 at 12.78

Twenty-eight seconds later SEK was FLAT at the broker - confirmed by
`IB.positions()`, which returned nine positions with no SEK in them. The
protective sell of 948 shares was retried every sixty seconds against a position
that did not exist. **Signed off, it is a SHORT created by the rail whose entire
purpose is preventing one.**

What blocked it was the kill switch, tripped seconds earlier on an unrelated
error. That is luck, not design. Closing the app disposed of the order - a
`pending_signoff` order lives in memory, so a restart clears it - but relying on
that is an operator working around a defect.

⚠️ THE PATTERN ALREADY EXISTS IN THIS CODEBASE, in the resting-order cancel
loop's TOCTOU guard: *"Re-read immediately before committing to the loop, and
refuse on either of two INDEPENDENT signals - the broker's fresh answer, and
this app's own tracked fill count - because the whole feature exists on the
premise that one source alone was not enough to trust."* Protective sign-off had
no equivalent.

⚠️ REFUSE, DO NOT RESIZE, and the buy branch of `_sign_off_locked` already says
why: *"Reject rather than resize - silently changing a quantity a human just
approved would defeat the point of the approval."* A refusal is cheap here
because `rearm_protective_stops` runs on the protection sweep and will propose a
correctly-sized replacement; a silent resize would transmit a quantity nobody
approved.
"""

from __future__ import annotations

import logging

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountBalances, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _ShiftingBroker(MockBroker):
    """A broker whose holding can change between proposal and sign-off, which
    is exactly what a multi-execution fill does in the real world."""

    def __init__(self, held: float) -> None:
        super().__init__(seed=1)
        self.held = held
        self.fail_positions = False

    async def account(self) -> AccountBalances:
        return AccountBalances(equity=1_000_000.0, cash=1_000_000.0)

    async def positions(self) -> list[Position]:
        if self.fail_positions:
            raise ConnectionError("broker unreachable")
        if abs(self.held) <= 0:
            return []
        return [Position(symbol="SEK.AX", quantity=self.held, avg_price=14.88)]


def _oms(broker: MockBroker, tmp_path) -> OMS:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch()
    bus = EventBus()
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(broker, engine, switch, bus=bus, settings=settings)


async def _propose(oms: OMS, quantity: float):
    """A protective OCO, exactly as `rearm_protective_stops` proposes one."""
    return await oms.submit_protective_stop("SEK.AX", quantity, 12.78, 18.85)


@pytest.mark.asyncio
async def test_a_protective_order_signs_off_when_the_position_is_still_held(tmp_path):
    """⚠️ THE PRESENCE GUARD, first on purpose.

    Every test below asserts a REFUSAL. If this fixture could not produce a
    successful sign-off they would all pass against any code at all - the
    vacuous shape that has now bitten this project four times in one day. This
    proves the happy path works before anything asserts it does not.
    """
    broker = _ShiftingBroker(held=948.0)
    oms = _oms(broker, tmp_path)
    order = await _propose(oms, 948.0)

    signed = await oms.sign_off(order.order_id, "test")

    assert signed.status != "rejected", "a protective order over a real position must transmit"


@pytest.mark.asyncio
async def test_a_protective_order_is_REFUSED_when_the_position_went_flat(tmp_path, caplog):
    """The SEK.AX case. Proposed against 948 shares, signed off against nothing."""
    broker = _ShiftingBroker(held=948.0)
    oms = _oms(broker, tmp_path)
    order = await _propose(oms, 948.0)

    broker.held = 0.0  # the remaining executions land
    with caplog.at_level(logging.WARNING, logger="qat.domain.oms.oms"):
        signed = await oms.sign_off(order.order_id, "test")

    assert signed.status == "rejected"

    # ⚠️ THE REASON IS ASSERTED, and sabotage is why. Disabling the flat branch
    # leaves this test green, because the SHORTFALL branch below it also
    # rejects - 0 is less than 948. The two overlap, so flat earns its place on
    # the MESSAGE rather than the behaviour: an operator reading "is FLAT at the
    # broker ... would open a SHORT" learns what happened, where "shrank to 0"
    # buries it. A message worth having is a message worth pinning.
    said = caplog.text.lower()
    assert "flat at the broker" in said, caplog.text
    assert "short" in said, caplog.text


@pytest.mark.asyncio
async def test_a_protective_order_is_REFUSED_when_the_position_shrank(tmp_path):
    """Half-filled is the same defect at a smaller size: a protective sell for
    more than is held is short by the difference the moment it fills."""
    broker = _ShiftingBroker(held=948.0)
    oms = _oms(broker, tmp_path)
    order = await _propose(oms, 948.0)

    broker.held = 400.0
    signed = await oms.sign_off(order.order_id, "test")

    assert signed.status == "rejected"


@pytest.mark.asyncio
async def test_a_protective_order_is_REFUSED_when_the_broker_cannot_be_read(tmp_path):
    """Fail closed. A protective sell cannot be sized against a position you
    cannot see, and `None` and zero are different answers that must not
    collapse - the distinction `_broker_quantity` exists to preserve."""
    broker = _ShiftingBroker(held=948.0)
    oms = _oms(broker, tmp_path)
    order = await _propose(oms, 948.0)

    broker.fail_positions = True
    signed = await oms.sign_off(order.order_id, "test")

    assert signed.status == "rejected"


@pytest.mark.asyncio
async def test_a_position_that_GREW_still_signs_off(tmp_path):
    """Only a SHORTFALL matters. A protective order smaller than the holding
    under-protects, which is a different and much less urgent problem than
    selling shares that are not there - and refusing it would leave the
    position with nothing at all."""
    broker = _ShiftingBroker(held=948.0)
    oms = _oms(broker, tmp_path)
    order = await _propose(oms, 948.0)

    broker.held = 2000.0
    signed = await oms.sign_off(order.order_id, "test")

    assert signed.status != "rejected"
