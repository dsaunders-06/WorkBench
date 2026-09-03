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
"""

from __future__ import annotations

import pytest

from qat.data.broker.ib_errors import BENIGN_ORDER_ERROR_CODES, ErrorAction, classify


def test_a_known_benign_order_rejection_rejects_without_halting():
    assert classify(383, is_order_scoped=True) is ErrorAction.REJECT


@pytest.mark.parametrize(
    "code",
    [
        202,  # order cancelled - sent for EVERY cancellation, including one
        # IBKR issues itself when a bracket's OCA sibling is cancelled.
        105,  # order being modified does not match the original order
        110,  # price does not conform to the minimum price variation
        321,  # server error validating an API client request (still live on a MODIFY)
        329,  # order modify failed: cannot change to the new order type
        399,  # order message error
        404,  # shares not immediately available for short sale - order is HELD, not dead
        434,  # the order size cannot be zero
    ],
)
def test_the_ib_async_lifecycle_codes_reject_without_halting(code):
    """Task 5 CRITICAL fix (b). These are ib_async's own `warningCodes` (plus
    202, which its `wrapper.py` explicitly calls "an order-delete error" but
    an expected one) - routine broker lifecycle traffic, not a risk event."""
    assert classify(code, is_order_scoped=True) is ErrorAction.REJECT


def test_an_unknown_order_scoped_code_halts():
    """⚠️ FAIL CLOSED. 9999 is in nobody's list, which is the point."""
    assert classify(9999, is_order_scoped=True) is ErrorAction.HALT


def test_an_informational_code_with_no_order_is_ignored():
    """⚠️ 2104 is "market data farm connection is OK" and arrives as an ERROR.
    Fail-closed on unmatched errors would halt the system on a health notice."""
    assert classify(2104, is_order_scoped=False) is ErrorAction.IGNORE


def test_even_an_unknown_code_is_ignored_when_it_matches_no_order():
    assert classify(9999, is_order_scoped=False) is ErrorAction.IGNORE


def test_the_benign_set_is_the_enumerated_one():
    """A guard against someone 'simplifying' this into a serious-code list."""
    assert 383 in BENIGN_ORDER_ERROR_CODES
    assert 9999 not in BENIGN_ORDER_ERROR_CODES


def test_the_benign_set_excludes_codes_without_a_documented_order_meaning():
    """165, 492 and 10167 sit alongside the ones added in `warningCodes`, but
    165 is a historical-data query notice (not an order at all) and
    ib_async's own comment marks 492/10167 "not listed" - no documented
    meaning to call benign. Fail-closed means an undocumented code HALTS,
    not "probably fine because a neighbour was."""
    assert 165 not in BENIGN_ORDER_ERROR_CODES
    assert 492 not in BENIGN_ORDER_ERROR_CODES
    assert 10167 not in BENIGN_ORDER_ERROR_CODES


def test_a_benign_code_is_still_ignored_when_it_matches_no_order():
    """⚠️ Rule 2 outranks rule 1, and this is the only test that says so.

    Checking code-membership before `is_order_scoped` passes every other test in
    this file while returning REJECT here - marking an order rejected on the
    strength of a message that was never about an order.
    """
    assert classify(383, is_order_scoped=False) is ErrorAction.IGNORE
