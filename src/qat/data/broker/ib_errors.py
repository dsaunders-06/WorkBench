"""What to do about an error IBKR reports, decided by failing closed.

⚠️ WHY THIS IS ITS OWN FILE. The rule is one sentence and it is the whole safety
of consuming `errorEvent`: enumerate the BENIGN codes, and let everything else
halt. Kept beside the adapter's connection and order plumbing it would be read as
plumbing.

On 3 September IBKR reported Error 383 - an order whose size exceeded a TWS
precautionary limit - and nothing in the application consumed it. The order was
never transmitted to the exchange, the app believed it was live, and only broker
reconciliation four minutes later disagreed.

⚠️ THE ENUMERATION DIRECTION IS THE POINT. Listing the SERIOUS codes would mean
every rejection nobody anticipated is waved through as routine. That is the shape
the manual-close branch was rejected for three times, each time with 3,000+ tests
passing. Here an unrecognised order-scoped code HALTS.
"""

from __future__ import annotations

from enum import Enum


class ErrorAction(Enum):
    """What the adapter should do about one error from IBKR."""

    IGNORE = "ignore"
    REJECT = "reject"
    HALT = "halt"


# Order-scoped codes known to mean "this order will not be accepted, and that is
# a configuration disagreement rather than a risk event" - or, for the lifecycle
# codes below, "this order's life ended (or continues) in a way ib_async itself
# does not treat as exceptional".
#
# ⚠️ ADD TO THIS SET ONLY WITH EVIDENCE FROM A REAL REJECTION. Every code added
# here is one that will no longer halt, and the cost of being wrong is a genuine
# problem treated as routine.
#
# 383 - order size exceeds the TWS Precautionary Settings size limit. Observed
#       3 September 2026 on a 790-share order against a limit of 500.
#
# The rest are not from a live rejection - the evidence is ib_async's OWN
# source (.venv/Lib/site-packages/ib_async/wrapper.py, `Wrapper.error`, this
# install's version), read for Task 5 after 202/404/2109 were found halting
# routine broker lifecycle traffic:
#
# 202 - "Order Canceled - Reason:". wrapper.py sends this for EVERY
#       cancellation and deliberately carves it OUT of its own warningCodes
#       ("literally 'Order Canceled' error status, so now it is an
#       order-delete error"). No app-initiated cancel is required to see it:
#       when a bracket's stop fills, IBKR cancels the OCA sibling itself and
#       reports 202 against THAT leg's orderId. The order is dead, but
#       expectedly so - it must not halt the rest of the session.
#
# The remaining seven are wrapper.py's own `warningCodes` set - codes it
# records on the trade WITHOUT cancelling it ("DO NOT delete the trade
# object because the order is STILL LIVE at the broker") - narrowed to the
# ones actually ABOUT an order. Left out of that same set: 165 (a
# historical-data query notice, not an order) and 492/10167, which
# wrapper.py's own comment marks "not listed" - no documented meaning to
# call benign.
#
# 105 - order being modified does not match the original order.
# 110 - price does not conform to the contract's minimum price variation.
#       (When this hits a brand-new order still PendingSubmit, ib_async
#       cancels it instead of leaving it live - still not a halt: a bad
#       price is the same "configuration disagreement" 383 already is.)
# 321 - server error validating an API client request; wrapper.py notes that
#       when it results from a MODIFY, the order is still live.
# 329 - order modify failed: cannot change to the new order type. The
#       original order is untouched.
# 399 - order message error.
# 404 - shares for this order are not immediately available for short sale;
#       the order is held while IBKR attempts to locate them.
# 434 - the order size cannot be zero.
BENIGN_ORDER_ERROR_CODES: frozenset[int] = frozenset({383, 202, 105, 110, 321, 329, 399, 404, 434})


def classify(code: int, *, is_order_scoped: bool) -> ErrorAction:
    """Decide what one IBKR error means for this application.

    ⚠️ `is_order_scoped` FIRST, and it is not a formality. `errorEvent` carries
    connection and market-data notices as well as order errors - code 2104 is
    "market data farm connection is OK" and arrives at ERROR level. Classifying
    those would halt the system on a health message, so an error that matches no
    order this app placed is ignored no matter what its code is.
    """
    if not is_order_scoped:
        return ErrorAction.IGNORE
    if code in BENIGN_ORDER_ERROR_CODES:
        return ErrorAction.REJECT
    return ErrorAction.HALT
