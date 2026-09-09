"""Every order this app sends states its time-in-force. None leaves it implicit.

⚠️ MEASURED LIVE, 9 September 2026, and it halted the account twice. Both
app-driven market exits of the day - IAG.AX and SEK.AX - were rejected with:

    Error 10349: Order TIF was set to GTC based on order preset.

The IBKR order preset cannot stand aside. Checked in the Gateway UI: Time in
Force is a dropdown of DAY / GTC / OPG / IOC / AUC / GTD / DTC across all three
"Show" views, with no option to disable the override. So the preset ALWAYS
imposes a TIF, and an order that does not state its own gets one imposed and is
then rejected for the mismatch.

⚠️ AND THIS MODULE ALREADY KNEW. `to_ib_parent` carries the lesson in its own
comment, learned on 4 September: *"GTC explicitly ... and because leaving it
unset does not mean 'IBKR's default'. Measured live: IBKR answered warning
10349, 'Order TIF was set to DAY based on order preset', so a Gateway-side
preset chose the TIF instead of this application (M96)."*

It was fixed in the bracket and stop paths and NOT in the plain market/limit
branch of `to_ib_order`, which is what every app-driven market exit goes
through. The same defect, one branch over, five days later.

⚠️ WHY GTC AND NOT DAY, settled by measurement rather than preference. The
preset must be GTC because the protective legs must be: DAY killed every stop
this system ever placed, on 31 July, when six take-profit legs expired at the
close, the paired stops went with them as OCO does, and about $36,000 sat
through a three-day weekend unprotected. And the broker confirms the preset is
GTC today - all 18 resting legs read `tif='GTC'`, including BHP's, placed
9 September at 14:05.

So every order is GTC at the broker whatever the app sends. Sending DAY never
achieved DAY; it achieved a rejection.

**This test is structural on purpose.** It asserts the property over every
translation entry point rather than over the branch that failed, because the
branch that failed was the one nobody thought to check.
"""

from __future__ import annotations

import pytest

from qat.data.broker.adapter import Order
from qat.data.broker.ib_translate import (
    to_ib_oca_pair,
    to_ib_order,
    to_ib_parent,
    to_ib_protective_legs,
)


def _order(**kw) -> Order:
    base = dict(
        symbol="SEK.AX",
        side="sell",
        quantity=2978.0,
        order_id="t1",
        status="pending_signoff",
    )
    base.update(kw)
    return Order(**base)  # type: ignore[arg-type]


def _every_ib_order():
    """One of every shape this app can hand IBKR, with the name it goes by."""
    yield "market exit", to_ib_order(_order())
    yield "limit exit", to_ib_order(_order(limit_price=12.90))
    yield "protective stop", to_ib_order(_order(order_type="stop", stop_price=12.78))
    # BOTH branches of to_ib_parent. Sabotage found that only the limit one was
    # covered, so removing the TIF from its MARKET branch went undetected - the
    # sweep was incomplete in exactly the way it exists to prevent.
    yield "bracket parent limit", to_ib_parent(_order(side="buy", limit_price=14.88))
    yield "bracket parent market", to_ib_parent(_order(side="buy"))
    for leg in to_ib_protective_legs(
        _order(side="buy", stop_price=12.78, take_profit_price=18.85), parent_id=1
    ):
        yield "bracket leg", leg
    for leg in to_ib_oca_pair(
        _order(order_type="stop", stop_price=12.78, take_profit_price=18.85),
        oca_group="qat-1",
    ):
        yield "oca leg", leg


@pytest.mark.parametrize(("name", "ib_order"), list(_every_ib_order()))
def test_every_order_shape_states_GTC_explicitly(name, ib_order):
    """⚠️ THE TEST THAT WOULD HAVE CAUGHT 9 SEPTEMBER ON 4 SEPTEMBER.

    A per-branch test passes for every branch somebody remembered. This one
    fails for any shape that forgets, including one added later.
    """
    assert ib_order.tif == "GTC", f"{name} left its TIF as {ib_order.tif!r}"


def test_the_market_exit_is_the_one_that_was_wrong():
    """Named separately so the regression is findable by its own story rather
    than only as one row of a parametrised sweep."""
    assert to_ib_order(_order()).tif == "GTC"


def test_the_sweep_actually_covers_every_shape():
    """⚠️ THE PRESENCE GUARD for a structural test.

    A parametrised sweep that silently generated nothing would pass. This pins
    the count, so deleting a shape from `_every_ib_order` fails here rather
    than quietly shrinking the property being asserted.
    """
    shapes = list(_every_ib_order())
    # NINE. Eight, not seven, because `to_ib_protective_legs` and
    # `to_ib_oca_pair` each yield a PAIR - miscounted first time and this guard
    # said so. Then nine, because sabotage found `to_ib_parent`'s MARKET branch
    # was never exercised.
    assert len(shapes) == 9, [name for name, _ in shapes]
    assert {name for name, _ in shapes} == {
        "market exit",
        "limit exit",
        "protective stop",
        "bracket parent limit",
        "bracket parent market",
        "bracket leg",
        "oca leg",
    }
