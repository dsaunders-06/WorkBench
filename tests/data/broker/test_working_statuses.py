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


def test_the_two_sets_no_longer_diverge():
    """⚠️ CLOSED 28 August (item 31), and this test was rewritten deliberately -
    its previous version existed precisely so that closing the gap could not
    happen by accident.

    It used to assert `_IB_WORKING_STATUSES < WORKING_STATUSES`, missing
    `ApiPending` and `ApiUpdate`, so a stop in either read as NO protection and
    a protected position logged POSITION UNPROTECTED.

    ⚠️ Widening LOOSENS a rail: a position whose stop was ignored counted its
    FULL value against the aggregate cap and now counts only to the stop, so the
    aggregate falls. It was measured against the live book first - 20 open
    orders, 10 Submitted and 10 PreSubmitted, ZERO in either added state - so
    the change was a no-op on that book and could not move the number.

    They are now ONE definition rather than two that agree, which is what stops
    them drifting apart again.
    """
    assert _IB_WORKING_STATUSES == WORKING_STATUSES
