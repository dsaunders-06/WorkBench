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

⚠️ A SECOND SPLIT, INSIDE THE BENIGN SET ITSELF (Task 5 review, round 2).
`ib_async/wrapper.py`'s own `Wrapper.error` treats two shapes of "benign"
completely differently, and the first cut of this file collapsed them into one
`REJECT` action:

- Its `warningCodes` branch is explicit: "DO NOT delete the trade object
  because the order is STILL LIVE at the broker" - it records a validation
  warning on the trade and nothing else. The order can still fill.
- Its error/cancel branch (202, and anything genuinely unrecognised) marks the
  trade `Cancelled`. The order is done.

Writing `status = "rejected"` for both meant a benign warning like 404 (shares
still being located for a short sale) told the rest of the app - and, from a
later task, the OMS - that an order which could still fill never would.
`ErrorAction.WARN` below is the still-live half; `ErrorAction.REJECT` now
means only "done, but expectedly so".
"""

from __future__ import annotations

from enum import Enum


class ErrorAction(Enum):
    """What the adapter should do about one error from IBKR."""

    IGNORE = "ignore"
    WARN = "warn"
    REJECT = "reject"
    HALT = "halt"


# Order-scoped codes that mean the order is DONE - it will not fill, and
# "rejected" is what actually happened, just not from a risk event.
#
# ⚠️ ADD TO THIS SET ONLY WITH EVIDENCE FROM A REAL REJECTION OR FROM
# wrapper.py ITSELF. Every code added here is one that will no longer halt,
# and the cost of being wrong is a genuine problem treated as routine.
#
# 383 - order size exceeds the TWS Precautionary Settings size limit. Observed
#       3 September 2026 on a 790-share order against a limit of 500. The
#       order was never transmitted to the exchange.
# 202 - "Order Canceled - Reason:". wrapper.py sends this for EVERY
#       cancellation and deliberately carves it OUT of its own warningCodes
#       ("literally 'Order Canceled' error status, so now it is an
#       order-delete error"). No app-initiated cancel is required to see it:
#       when a bracket's stop fills, IBKR cancels the OCA sibling itself and
#       reports 202 against THAT leg's orderId. The order is dead, but
#       expectedly so - it must not halt the rest of the session.
BENIGN_ORDER_REJECT_CODES: frozenset[int] = frozenset({383, 202})

# Order-scoped codes wrapper.py's OWN `warningCodes` set records on the trade
# WITHOUT cancelling it ("DO NOT delete the trade object because the order is
# STILL LIVE at the broker") - narrowed to the ones actually ABOUT an order.
# Left out of that same set: 165 (a historical-data query notice, not an
# order) and 492/10167, which wrapper.py's own comment marks "not listed" -
# no documented meaning to call benign.
#
# ⚠️ ADD TO THIS SET ONLY WITH EVIDENCE FROM A REAL REJECTION OR FROM
# wrapper.py ITSELF. Every code added here is one whose order this app will
# now report as UNCHANGED - the cost of being wrong is telling the rest of
# the app, and eventually the OMS, that an order is still open when the
# broker actually let it go.
#
# 105 - order being modified does not match the original order. The
#       modification is refused; the original order is untouched and live.
# 110 - price does not conform to the contract's minimum price variation.
#       wrapper.py treats this as a warning UNLESS the order is a brand-new
#       one still PendingSubmit, in which case it cancels it instead
#       (`isWarning = False` for that one case only). This classifier sees
#       only the code, not the order's live status at the moment of the
#       error, so it cannot draw that distinction - it takes wrapper.py's
#       DEFAULT (warn, stay live), the same call the previous round of this
#       fix made when 110 was still merged into REJECT and flagged as that
#       round's one open concern.
# 321 - server error validating an API client request; wrapper.py notes that
#       when it results from a MODIFY, the order is still live.
# 329 - order modify failed: cannot change to the new order type. The
#       original order is untouched.
# 399 - order message error.
# 404 - shares for this order are not immediately available for short sale;
#       the order is held while IBKR attempts to locate them.
# 434 - the order size cannot be zero.
BENIGN_ORDER_WARN_CODES: frozenset[int] = frozenset({105, 110, 321, 329, 399, 404, 434})


def classify(code: int, *, is_order_scoped: bool) -> ErrorAction:
    """Decide what one IBKR error means for this application.

    ⚠️ `is_order_scoped` FIRST, and it is not a formality. `errorEvent` carries
    connection and market-data notices as well as order errors - code 2104 is
    "market data farm connection is OK" and arrives at ERROR level. Classifying
    those would halt the system on a health message, so an error that matches no
    order this app placed is ignored no matter what its code is - checked before
    either benign set, so a code that would WARN or REJECT about a matched order
    still IGNOREs when the error was never about one of ours.

    ⚠️ `BENIGN_ORDER_WARN_CODES` and `BENIGN_ORDER_REJECT_CODES` are disjoint by
    construction (pinned by a guard test) - the order these two are checked in
    must never matter, and isn't meant to signal a priority between them.
    """
    if not is_order_scoped:
        return ErrorAction.IGNORE
    if code in BENIGN_ORDER_WARN_CODES:
        return ErrorAction.WARN
    if code in BENIGN_ORDER_REJECT_CODES:
        return ErrorAction.REJECT
    return ErrorAction.HALT
