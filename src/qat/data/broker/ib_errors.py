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
# a configuration disagreement rather than a risk event".
#
# ⚠️ ADD TO THIS SET ONLY WITH EVIDENCE FROM A REAL REJECTION. Every code added
# here is one that will no longer halt, and the cost of being wrong is a genuine
# problem treated as routine.
#
# 383 - order size exceeds the TWS Precautionary Settings size limit. Observed
#       3 September 2026 on a 790-share order against a limit of 500.
BENIGN_ORDER_ERROR_CODES: frozenset[int] = frozenset({383})


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
