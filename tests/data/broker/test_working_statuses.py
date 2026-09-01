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

from qat.data.broker.ib_translate import _IB_STATUS_MAP, _IB_WORKING_STATUSES
from qat.domain.oms.resting_orders import TERMINAL_STATUSES, WORKING_STATUSES

# ib_async counts this active; an order that failed validation cannot fill.
_NOT_REALLY_WORKING = {"ValidationError"}


def test_the_scan_knows_every_state_ib_async_calls_active():
    assert WORKING_STATUSES == frozenset(OrderStatus.ActiveStates) - _NOT_REALLY_WORKING


def test_the_terminal_set_is_every_state_ib_async_calls_done():
    """`TERMINAL_STATUSES` answers "is this order definitely finished", which
    is what `PositionCloser` verifies its cancels with. Pinned to the library
    for the same reason `WORKING_STATUSES` is: an ib_async upgrade that adds a
    done state must fail the suite, not silently widen what counts as gone."""
    assert TERMINAL_STATUSES == frozenset(OrderStatus.DoneStates)


def test_working_and_terminal_do_not_overlap():
    assert not (WORKING_STATUSES & TERMINAL_STATUSES)


def test_pending_cancel_is_in_NEITHER_set_and_that_is_the_whole_point():
    """⚠️ THE GAP IS REAL AND IT IS WHERE THE RISK LIVES.

    `PendingCancel` is not a working state and not a done state. Asking "is it
    gone?" as `status not in WORKING_STATUSES` therefore answered YES for a leg
    that IBKR was still showing and that could still fill - `PositionCloser`
    dropped it from its post-cancel read, found no survivors, and sent a market
    SELL over both OCA legs still resting. A short position, reported as a
    clean close.

    And it is the ORDINARY transient of an honoured cancel as much as it is
    19 August's rejected one (error 10147), so that fired on the happy path.

    This is asserted rather than left as a comment so that an upgrade which
    moves `PendingCancel` into either set is noticed HERE, where the choice of
    predicate can be re-made, instead of silently changing what the closer
    treats as gone.
    """
    assert "PendingCancel" not in WORKING_STATUSES
    assert "PendingCancel" not in TERMINAL_STATUSES
    # And it is a status IBKR really reports, not a hypothetical: it is what
    # `_IB_STATUS_MAP` maps to "transmitted".
    assert "PendingCancel" in _IB_STATUS_MAP


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
