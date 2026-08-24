"""The orphan scan's status set, checked against ib_async's own (M141).

M139's cause was a hand-maintained status map that did not know IBKR's working
states. This asserts the domain module's literals against the library rather
than trusting them, so an ib_async upgrade that adds a state fails the suite
instead of narrowing the scan in silence.

Lives at the broker boundary because the domain module must not import
ib_async.
"""

from __future__ import annotations

from ib_async import OrderStatus

from qat.data.broker.ib_translate import _IB_WORKING_STATUSES
from qat.domain.oms.resting_orders import WORKING_STATUSES

# ib_async counts this active; an order that failed validation cannot fill.
_NOT_REALLY_WORKING = {"ValidationError"}


def test_the_scan_knows_every_state_ib_async_calls_active():
    assert WORKING_STATUSES == frozenset(OrderStatus.ActiveStates) - _NOT_REALLY_WORKING


def test_the_two_sets_diverge_deliberately():
    """`_IB_WORKING_STATUSES` is NARROWER, by operator decision on 24 August.

    Widening it moves `_position_stops`, which is the denominator of every
    risk-at-stop figure the governor gates entries on, so it ships separately
    with its effect measured. This test exists so the gap reads as a decision
    rather than as an oversight - and so that closing it is a deliberate act
    that updates this test.
    """
    assert _IB_WORKING_STATUSES < WORKING_STATUSES
    assert WORKING_STATUSES - _IB_WORKING_STATUSES == {"ApiPending", "ApiUpdate"}
