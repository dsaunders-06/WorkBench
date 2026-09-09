"""IBKR told us the order was rejected and the app was not listening.

3 September, `logger=ib_async.wrapper`:

    Error 383, reqId 476: The following order "ID:476" size exceeds the Size
    Limit of 500. Restriction is specified in Precautionary Settings of Global
    Configuration/Presets.

Nothing consumed it. The app went on believing the order was live at the
exchange for over two hours.

⚠️ THE ENUMERATION IS OF THE BENIGN CODES ONLY. An unfamiliar rejection falls to
HALT. Enumerating the SERIOUS set is what made the manual-close branch green over
the exact defect it was named for, three times.

⚠️ Task 5 review, round 2: the benign set itself split in two.
`test_the_ib_async_lifecycle_codes_reject_without_halting` used to assert
`ErrorAction.REJECT` for 202 AND for ib_async's `warningCodes` (105, 110, 321,
329, 399, 404, 434) alike - collapsing "the order is done" and "the order is
still live" into one action. `ib_errors.classify` now returns `ErrorAction.WARN`
for the still-live ones; the tests below are split to match, plus a guard that
the two benign sets stay disjoint.
"""

from __future__ import annotations

import pytest

from qat.data.broker.ib_errors import (
    BENIGN_ORDER_REJECT_CODES,
    BENIGN_ORDER_WARN_CODES,
    ErrorAction,
    classify,
)


def test_a_known_benign_order_rejection_rejects_without_halting():
    assert classify(383, is_order_scoped=True) is ErrorAction.REJECT


def test_code_202_rejects_without_halting():
    """202 is wrapper.py's own carve-out from its `warningCodes` - "literally
    'Order Canceled' error status, so now it is an order-delete error" - sent
    for EVERY cancellation, including one IBKR issues itself when a bracket's
    OCA sibling is cancelled. The order is DONE, so this belongs in REJECT,
    not the still-live WARN set below."""
    assert classify(202, is_order_scoped=True) is ErrorAction.REJECT


@pytest.mark.parametrize(
    "code",
    [
        105,  # order being modified does not match the original order
        110,  # price does not conform to the minimum price variation
        321,  # server error validating an API client request (still live on a MODIFY)
        329,  # order modify failed: cannot change to the new order type
        399,  # order message error
        404,  # shares not immediately available for short sale - order is HELD, not dead
        434,  # the order size cannot be zero
    ],
)
def test_the_still_live_codes_warn_without_changing_or_halting(code):
    """Task 5 review, round 2. These are ib_async's own `warningCodes` -
    "DO NOT delete the trade object because the order is STILL LIVE at the
    broker" (`wrapper.py`). Marking the order 'rejected' for one of these, as
    the previous round did, tells the rest of the app an order that can still
    fill never would - so `classify` must answer WARN, not REJECT, for every
    one of them."""
    assert classify(code, is_order_scoped=True) is ErrorAction.WARN


def test_an_unknown_order_scoped_code_halts():
    """⚠️ FAIL CLOSED. 9999 is in nobody's list, which is the point."""
    assert classify(9999, is_order_scoped=True) is ErrorAction.HALT


def test_an_informational_code_with_no_order_is_ignored():
    """⚠️ 2104 is "market data farm connection is OK" and arrives as an ERROR.
    Fail-closed on unmatched errors would halt the system on a health notice."""
    assert classify(2104, is_order_scoped=False) is ErrorAction.IGNORE


def test_even_an_unknown_code_is_ignored_when_it_matches_no_order():
    assert classify(9999, is_order_scoped=False) is ErrorAction.IGNORE


def test_the_benign_sets_are_the_enumerated_ones():
    """A guard against someone 'simplifying' this into a serious-code list."""
    assert 383 in BENIGN_ORDER_REJECT_CODES
    assert 202 in BENIGN_ORDER_REJECT_CODES
    assert 10148 in BENIGN_ORDER_REJECT_CODES
    assert 105 in BENIGN_ORDER_WARN_CODES
    assert 9999 not in BENIGN_ORDER_REJECT_CODES
    assert 9999 not in BENIGN_ORDER_WARN_CODES


def test_the_benign_sets_exclude_codes_without_a_documented_order_meaning():
    """165, 492 and 10167 sit alongside the ones added in `warningCodes`, but
    165 is a historical-data query notice (not an order at all) and
    ib_async's own comment marks 492/10167 "not listed" - no documented
    meaning to call benign. Fail-closed means an undocumented code HALTS,
    not "probably fine because a neighbour was." Checked against BOTH benign
    sets - the split must not have let one of them back in through the other
    door.
    """
    for code in (165, 492, 10167):
        assert code not in BENIGN_ORDER_WARN_CODES
        assert code not in BENIGN_ORDER_REJECT_CODES


def test_the_benign_sets_are_disjoint():
    """`classify` checks WARN before REJECT (see its own docstring) - if a
    code were ever added to both, WARN would silently win, and a code that
    actually means "the order is done" would be reported as still live.
    Nothing should have to rely on the check ORDER to stay correct."""
    assert not (BENIGN_ORDER_WARN_CODES & BENIGN_ORDER_REJECT_CODES)


def test_a_benign_reject_code_is_still_ignored_when_it_matches_no_order():
    """⚠️ Rule 2 outranks rule 1, and this is one of two tests that say so.

    Checking code-membership before `is_order_scoped` passes every other test in
    this file while returning REJECT here - marking an order rejected on the
    strength of a message that was never about an order.
    """
    assert classify(383, is_order_scoped=False) is ErrorAction.IGNORE


def test_a_benign_warn_code_is_still_ignored_when_it_matches_no_order():
    """⚠️ The same property, for the WARN branch the split just introduced -
    a code that would warn about a MATCHED order must not warn about one
    that was never ours."""
    assert classify(105, is_order_scoped=False) is ErrorAction.IGNORE


def test_code_10148_rejects_without_halting():
    """⚠️ MEASURED THREE TIMES ON 9 September 2026, and it halted the account
    on every one.

        Error 10148, reqId 615: OrderId 615 that needs to be cancelled
        cannot be cancelled, state: PendingCancel.
        Error 10148, reqId 616: ... state: Cancelled.

    It is 202's twin and arrives for the same reason. `cancel_order` cancels
    EVERY leg of a group rather than trusting IBKR's OCA cascade - "cascades is
    not a guarantee this project accepts on trust" - so when cancelling leg 615
    auto-cancels its sibling 616, our explicit cancel of 616 asks IBKR to cancel
    something already gone. 10148 is the answer.

    ⚠️ THE RAIL IS RIGHT AND THE CLASSIFICATION WAS WRONG. Not trusting the
    cascade is worth keeping - an orphaned stop against a position that no
    longer exists is what puts the account short. What must change is treating
    that rail's own expected reply as an unrecognised rejection.

    Safe by the meaning of the code itself: 10148 is only ever emitted when the
    cancel target is already `PendingCancel` or `Cancelled`, which is the state
    the cancel was asking for. It cannot report a live order.

    WHAT IT COST. Each halt blocked the sign-off that the re-arm rail needed to
    replace IAG.AX's protection, so a held 6,699-share position sat unprotected
    while the only mechanism that could protect it was the order flow the halt
    existed to stop. Aggregate risk-at-stop reached 8.12% against a 5.00% cap.
    """
    assert classify(10148, is_order_scoped=True) is ErrorAction.REJECT


def test_10148_is_ignored_when_it_matches_no_order():
    """Order-scope is established BEFORE classification, as for every other
    code here: `errorEvent` also carries health notices, and failing closed on
    those would halt daily."""
    assert classify(10148, is_order_scoped=False) is ErrorAction.IGNORE
