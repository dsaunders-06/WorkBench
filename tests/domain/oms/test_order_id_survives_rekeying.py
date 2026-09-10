"""An order in `pending_orders()` must be fetchable by its own id.

⚠️ MEASURED LIVE, 31 August 2026, on the first app-transmitted entry since
item 56 shipped. Every 60 seconds:

    executor.py:127 retry_pending -> :147 _consider -> oms.py:964 get_order
    KeyError: '1031062661'

`IBAdapter.place_order` returns an Order RE-IDENTIFIED with the broker's permId
(`ib_adapter.py:342-344`). `OMS.sign_off` stores that object back under its
ORIGINAL key and puts the permId only into `_broker_order_ids`, a set. So
`_orders["<uuid>"] = Order(order_id="<permId>")` - **the dict key and the
object's own id disagree.**

`pending_orders()` iterates `.values()` and hands back the object; `_consider`
then calls `get_order(order.order_id)`, a KEY lookup, which raises.

⚠️ **The `try` in `retry_pending` wraps the WHOLE `for` loop**, so the sweep
dies on the first such order and every remaining pending order is skipped.
Autonomous execution stalls.

⚠️ **WHY NO TEST CAUGHT IT:** `MockBroker.place_order` returns the same object
with the same `order_id` and never re-ids. The fixture is friendlier than
production, which is item 22's lesson exactly. The broker below re-ids the way
the real adapter does.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_PERM_ID = "1031062661"


class _ReIdingBroker(MockBroker):
    """A broker that re-identifies the order it returns, as IBKR does.

    `ib_adapter.py:342-344`:

        result = from_ib_trade(parent_trade, order)
        if result.order_id != app_order_id:
            self._register(result, parent, group)
        return result

    The returned Order carries the broker's permId. MockBroker does not model
    that, and the live defect lives entirely in what the OMS does with it.
    """

    async def place_order(self, order: Order) -> Order:
        placed = await super().place_order(order)
        # ⚠️ `transmitted`, NOT `filled`, and that is load-bearing. The live JHX
        # order was still WORKING when `_consider` retried - a market order that
        # took 45 seconds across 17 executions. `pending_orders()` deliberately
        # excludes `filled`, so a broker that fills instantly leaves the list
        # EMPTY and the invariant test below iterates nothing and passes. An
        # empty loop proves nothing; this reproduces the state that broke.
        return replace(placed, order_id=_PERM_ID, status="transmitted")


def _oms() -> OMS:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(_ReIdingBroker(seed=1), engine, switch, max_order_pct_of_cash=1.0, bus=bus)


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate() -> OrderCandidate:
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


@pytest.mark.asyncio
async def test_every_pending_order_can_be_fetched_by_its_own_id() -> None:
    """⚠️ THE INVARIANT, and it is what `_consider` actually does.

    Anchored on the shape rather than on one id: whatever `pending_orders()`
    hands out must be retrievable by the id it carries. A dict whose key and
    whose value's own id can diverge will always break some caller.
    """
    oms = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    pending = oms.pending_orders()
    # ⚠️ Guard the loop. `pending_orders()` excludes `filled`, so a broker that
    # fills instantly leaves this EMPTY and the loop below passes having
    # examined nothing.
    assert pending, "nothing pending - the loop below would prove nothing"

    for order_in_flight in pending:
        oms.get_order(order_in_flight.order_id)  # must not raise


@pytest.mark.asyncio
async def test_the_order_is_reachable_under_the_brokers_id() -> None:
    """The permId is the id every later execution, modify and cancel arrives
    under, so it has to resolve."""
    oms = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    assert oms.get_order(_PERM_ID).symbol == "AAA"


@pytest.mark.asyncio
async def test_the_order_is_still_reachable_under_the_original_id() -> None:
    """⚠️ THE CONTROL, and it is why the fix ALIASES rather than moves the key.

    The journal, the blotter and the decision record all hold the id the order
    was created with. Re-keying alone would break every one of them - trading
    one KeyError for another.
    """
    oms = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    original = order.order_id
    await oms.sign_off(original, operator="alice")

    assert oms.get_order(original).symbol == "AAA"


@pytest.mark.asyncio
async def test_an_aliased_order_is_ENUMERATED_only_once() -> None:
    """⚠️ SEEN LIVE on the Order Blotter, 10 September 2026: one COH.AX entry,
    two identical rows, "2 of 2 orders".

    The alias above is correct and must stay - it is what makes an order
    reachable under both ids, and the three tests above are its warrant. But
    `orders()` is `list(self._orders.values())`, so two keys pointing at ONE
    object enumerate that object TWICE.

    LOOKUP wants the alias; ENUMERATION must not see it. The blotter renders a
    row per returned object and prints `order.order_id` - which is the permId on
    both - so the duplicate is invisible as a duplicate: every column matches.

    ⚠️ `position_closer.preview_protective_orders` reads the same list, filtered
    to transmitted stops, and its own docstring states the invariant this breaks:
    "this normally returns zero or one order, not two". The aliasing happens in
    `_sign_off_locked`, and sign_off is the sole path to the broker, so a
    protective stop is aliased exactly like an entry - putting a double-counted
    stop in front of the close-position confirmation dialog.
    """
    oms = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    # ⚠️ PROVE THE ALIAS EXISTS FIRST. Without this the assertions below pass
    # trivially on any OMS that never aliased at all, and would keep passing if
    # someone "fixed" this by deleting the alias - which the three tests above
    # exist to forbid.
    assert oms.get_order(order.order_id) is oms.get_order(_PERM_ID), "no alias - test is vacuous"

    listed = oms.orders()
    ids = [listed_order.order_id for listed_order in listed]

    assert len(ids) == len(set(ids)), f"the same order enumerated twice: {ids}"
    assert sum(1 for listed_order in listed if listed_order.symbol == "AAA") == 1, ids
