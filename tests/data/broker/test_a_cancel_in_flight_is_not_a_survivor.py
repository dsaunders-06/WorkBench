"""A cancel that IBKR is already honouring is not a leg that survived.

⚠️ MEASURED LIVE, 9 September 2026, 11:21:46 and again at 12:20:56. A signal
exit on IAG.AX cancelled its two bracket legs, the group cancel WORKED, and the
still-resting re-check then declared both legs survivors and cancelled them a
second time:

    IBKR leg 423 survived the group cancel - cancelling it individually
    Error 10148, reqId 423: ... cannot be cancelled, state: PendingCancel.
    Error 10148, reqId 424: ... cannot be cancelled, state: Cancelled.
    KILL-SWITCH TRIPPED: ... unrecognised code 10148

10148 is not enumerated in `ib_errors`, so the halt is correct by construction -
an unfamiliar rejection must stop the account. But the rejection itself was
manufactured by this code asking IBKR to cancel something it was already
cancelling. The account then sat with IAG.AX 6,699 shares UNPROTECTED, because
the re-arm rail proposes a replacement stop and the kill switch blocks its
sign-off: the only thing that restores protection is order flow, and the switch
exists to stop order flow. Reset once, it reproduced within 49 seconds.

⚠️ WHY EVERY EXISTING TEST PASSED. `_RecordingIB` in
`test_ib_cancel_resolves.py` POPS a cancelled order out of `openTrades()`, and
says so in its own docstring - "so the group-cancel's own still-resting re-check
does not see a just-cancelled leg and cancel it a second time". That is a broker
that does not exist. The real one leaves the order VISIBLE, reporting
`PendingCancel`, which `adapter.py:151` and `ib_adapter.py:638` had both already
written down: **visible is not gone.** The fake here models the real behaviour
instead.

⚠️ THIS IS A THIRD QUESTION, not a loosening of the second. This module already
distinguishes CAPTURE ("what must I cancel" - `WORKING_STATUSES`) from
VERIFICATION ("is it definitely gone" - `not in TERMINAL_STATUSES`, fail-closed,
with `PendingCancel` deliberately in neither set). Whether to send a REDUNDANT
CANCEL is neither: a leg whose cancel is already in flight needs no second one.
The decision to SELL is unaffected - `_release_protective_legs` does its own
re-read and keeps its fail-closed rule.
"""

from __future__ import annotations

from typing import Any

import pytest
from ib_async.contract import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus


class _RealisticIB:
    """A client that behaves like IBKR rather than like a wish.

    `cancelOrder` leaves the trade VISIBLE in `openTrades()` and moves it to
    `status_after_cancel`, which is what the live broker does. `poll_statuses`
    lets a test walk the status forward on successive reads, so the bounded
    re-read can be exercised without a real clock.
    """

    def __init__(
        self,
        resting: list[Trade],
        *,
        status_after_cancel: str = "PendingCancel",
        poll_statuses: list[str] | None = None,
    ) -> None:
        self._resting: dict[int, Trade] = {t.order.orderId: t for t in resting}
        self._status_after_cancel = status_after_cancel
        self._poll_statuses = list(poll_statuses or [])
        self.cancel_calls: list[int] = []
        # ⚠️ COUNTED FROM THE FIRST CANCEL, not from construction, and the first
        # version of this fixture got it wrong. `_resolve_from_open_trades`
        # calls `openTrades()` while resolving the group, BEFORE any cancel goes
        # out, so that read consumed the first scripted status and the leg was
        # already `PendingCancel` by the time the survivor check looked. The
        # re-read test then passed with the re-read removed - caught by
        # sabotage, not by reading it.
        self.reads_after_cancel = 0
        self._cancel_seen = False

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        raise NotImplementedError("not exercised by these tests")

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancel_calls.append(int(order.orderId))
        self._cancel_seen = True
        trade = self._resting.get(order.orderId)
        if trade is not None:
            trade.orderStatus.status = self._status_after_cancel
        return trade

    def openTrades(self) -> list[Trade]:
        # The scripted statuses walk forward only on reads that happen AFTER a
        # cancel has gone out - the group-resolution read must not consume one.
        if self._cancel_seen:
            self.reads_after_cancel += 1
            if self._poll_statuses:
                nxt = self._poll_statuses.pop(0)
                for trade in self._resting.values():
                    trade.orderStatus.status = nxt
        return list(self._resting.values())

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _settings() -> Settings:
    return Settings(_env_file=None, trading_mode="paper")


def _leg(order_id: int, perm_id: int) -> Trade:
    ib_order = IBOrder(orderId=order_id, permId=perm_id, action="SELL", totalQuantity=6699)
    return Trade(
        contract=Contract(symbol="IAG"),
        order=ib_order,
        orderStatus=OrderStatus(orderId=order_id, status="PreSubmitted", permId=perm_id),
    )


def _adapter(client: _RealisticIB, perm_id: int) -> IBAdapter:
    adapter = IBAdapter(client, EventBus(), settings=_settings())
    order = Order(
        symbol="IAG.AX", side="sell", quantity=6699, order_id=str(perm_id), stop_price=7.28
    )
    adapter._orders[order.order_id] = order
    return adapter


@pytest.mark.asyncio
async def test_a_leg_that_IGNORES_the_cancel_is_still_re_cancelled():
    """⚠️ THE PRESENCE GUARD, first on purpose.

    Every test below asserts that a second cancel is NOT sent. If this fixture
    could not produce a second cancel in the first place they would all pass
    against any code at all - the vacuous shape that let two M170 sabotages
    escape and that made this morning's `resting_stops` test meaningless. This
    proves the re-cancel is real before anything asserts its absence.
    """
    client = _RealisticIB([_leg(423, 1216558927)], status_after_cancel="Submitted")
    adapter = _adapter(client, 1216558927)

    await adapter.cancel_order("1216558927")

    assert client.cancel_calls.count(423) == 2, "a leg still working must be cancelled again"


@pytest.mark.asyncio
async def test_a_leg_in_PendingCancel_is_not_cancelled_again():
    """The IAG.AX case. `PendingCancel` is the ordinary transient of a cancel
    IBKR IS honouring, so a second cancel achieves nothing and earns a 10148
    that halts the account."""
    client = _RealisticIB([_leg(423, 1216558927)], status_after_cancel="PendingCancel")
    adapter = _adapter(client, 1216558927)

    await adapter.cancel_order("1216558927")

    assert client.cancel_calls.count(423) == 1


@pytest.mark.asyncio
async def test_a_leg_already_Cancelled_is_not_cancelled_again():
    """Leg 424's case in the same incident - it had reached `Cancelled` before
    the re-check ran, and was cancelled again anyway."""
    client = _RealisticIB([_leg(424, 1216558928)], status_after_cancel="Cancelled")
    adapter = _adapter(client, 1216558928)

    await adapter.cancel_order("1216558928")

    assert client.cancel_calls.count(424) == 1


@pytest.mark.asyncio
async def test_the_re_read_is_bounded_and_gives_a_slow_cancel_time_to_land():
    """⚠️ THE HANDOFF PRESCRIBED THIS SHAPE BEFORE THE INCIDENT: "a bounded
    re-read (~3 polls over 2s) before declaring survivors - NOT a looser
    predicate."

    A status filter alone is fragile - it reads once, immediately after issuing
    the cancels, so a leg whose status has not moved yet still looks like a
    survivor. Here the first read says `Submitted` and the second `PendingCancel`,
    and no second cancel must go out.
    """
    client = _RealisticIB(
        [_leg(423, 1216558927)],
        status_after_cancel="Submitted",
        poll_statuses=["Submitted", "PendingCancel"],
    )
    adapter = _adapter(client, 1216558927)

    await adapter.cancel_order("1216558927")

    assert client.cancel_calls.count(423) == 1
    assert client.reads_after_cancel >= 2, "it must actually re-read, not just filter one read"


@pytest.mark.asyncio
async def test_the_re_read_gives_up_rather_than_waiting_forever():
    """Bounded. A leg that never moves is a genuine survivor and must be
    cancelled again - the rail must not hang waiting for a status that is not
    coming."""
    client = _RealisticIB([_leg(423, 1216558927)], status_after_cancel="Submitted")
    adapter = _adapter(client, 1216558927)

    await adapter.cancel_order("1216558927")

    assert client.cancel_calls.count(423) == 2
