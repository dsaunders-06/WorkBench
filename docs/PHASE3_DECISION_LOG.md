# Phase 3 decision log

## 23 October 2026 — ASX opening-auction entry

DS amended the step-4 entry ruling. An approved card's intended entry is a
pre-open `BUY LMT GTD` at the card's limit, with expiry shortly after that
stock's opening auction (default 10:15:00 Australia/Sydney), enforced by IBKR.
There is no fallback to a `DAY` or `GTC` limit. Production GTD support remains
deferred pending the one-off paper probe and DS review; the current build does
not transmit an opening-auction entry.

Evidence: the [10 October real-Gateway probe](PHASE3_REAL_GATEWAY_PROBE_2026-10-10.md)
records paper rejection of `LMT`/`OPG` for an ASX stock and contract details
without `OPG`. DS holds the private IBCS response of 19 October 2026 to the
ticket “ASX limit-on-open (LMT, TIF OPG) via API: live vs paper support.” Its
relevant reply says: “Paper trading session mirrors the behavior of live
session and you will most probably not be able to place an order in live
session that got rejected in paper session.” It adds: “If OPT is not listed
in contract details response or in TWS GUI -> ORDER ENTRY window - it is
not supported for this type of order,” and “This is purely exchange and
security type specific, API precautionary settings are not known to trigger
this error.” “OPT” is IBCS's typo for `OPG`. IBCS transferred the ticket to
another department; follow-up is pending and a case ID is not yet available.
IBKR's [order reference](https://ibkrcampus.com/docs/tws-api/ref/order)
specifies `goodTillDate` with `GTD` time-in-force.
