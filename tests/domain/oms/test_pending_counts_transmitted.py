"""A transmitted order is committed exposure and must be counted (item 58).

On 26 August two entries went out 173 milliseconds apart and both were sized
against a book of NINE:

    WOW.AX  decided 05:15:24Z  signed 15:15:24.870  position_count 9.0
    SEK.AX  decided 05:15:25Z  signed 15:15:25.043  position_count 9.0

The book went to ELEVEN against a `max_concurrent_positions` of 10, and stayed
over the cap until an exit on 27 August brought it back to ten - where
`governor.py:304` refuses at `>=`, so it still could not enter. That cost the
27 August session 1,036 refusals and every entry it might have made.

**The rail is not missing and the governor is not wrong.** `ExposureSnapshot`
counts pending buys deliberately. What it is given is too narrow:
`OMS.pending_orders` matched only `status == "pending_signoff"`, and in auto
mode the executor signs off in milliseconds - so between sign-off and the
broker reporting the position, an order is in NEITHER `held` NOR `pending`.

Its own docstring already said the right thing - *"committed exposure that has
not filled"* - while the code did less. The same shape as items 56, 59, 61 and
63 in the same week.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


@pytest.fixture
def oms_for_pending() -> OMS:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    return OMS(MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch)


def _order(oms: OMS, symbol: str, status: str):
    order = oms._new_pending_order(symbol=symbol, side="buy", quantity=100.0, reference_price=10.0)
    oms._orders[order.order_id] = replace(order, status=status)
    return oms._orders[order.order_id]


@pytest.mark.parametrize("status", ["pending_signoff", "transmitted"])
def test_committed_exposure_is_pending_whatever_it_is_called(oms_for_pending, status) -> None:
    """Both statuses mean the same thing to the position cap: the account is
    committed and the broker has not reported it yet."""
    _order(oms_for_pending, "WOW.AX", status)

    symbols = {order.symbol for order in oms_for_pending.pending_orders()}

    assert "WOW.AX" in symbols, (
        f"an order with status={status!r} is committed exposure the broker has not yet "
        f"reported, and a second candidate sized in the same cycle must see it (item 58)."
    )


@pytest.mark.parametrize("status", ["filled", "cancelled", "rejected", "new"])
def test_what_is_not_committed_stays_out(oms_for_pending, status) -> None:
    """⚠️ The other direction, and it matters more than it looks. `filled` is
    already in the broker's positions, so counting it here would double its
    contribution to `gross` and `risk_at_stop_dollars` - the snapshot guards the
    COUNT with `if order.symbol not in held` but adds exposure unconditionally.
    `cancelled` and `rejected` are not exposure at all."""
    _order(oms_for_pending, "SEK.AX", status)

    symbols = {order.symbol for order in oms_for_pending.pending_orders()}

    assert "SEK.AX" not in symbols, f"status={status!r} is not committed exposure"


def test_two_entries_in_one_cycle_see_each_other(oms_for_pending) -> None:
    """The 26 August sequence, reproduced. The first order is signed off and
    transmitted; the second is sized immediately after and must count it."""
    _order(oms_for_pending, "WOW.AX", "transmitted")

    pending = oms_for_pending.pending_orders()

    assert len(pending) == 1
    assert pending[0].symbol == "WOW.AX"
