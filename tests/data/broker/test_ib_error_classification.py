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

from qat.data.broker.ib_errors import BENIGN_ORDER_ERROR_CODES, ErrorAction, classify


def test_a_known_benign_order_rejection_rejects_without_halting():
    assert classify(383, is_order_scoped=True) is ErrorAction.REJECT


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


def test_a_benign_code_is_still_ignored_when_it_matches_no_order():
    """⚠️ Rule 2 outranks rule 1, and this is the only test that says so.

    Checking code-membership before `is_order_scoped` passes every other test in
    this file while returning REJECT here - marking an order rejected on the
    strength of a message that was never about an order.
    """
    assert classify(383, is_order_scoped=False) is ErrorAction.IGNORE
