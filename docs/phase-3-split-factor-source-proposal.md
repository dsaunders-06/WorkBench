# Phase 3 source basis decision for operator review

This is a design finding, not authorization to connect to IBKR, ASX or another
data service. No real source or backfill was built in the steps 2–3 fix.

## What IBKR publishes

IBKR's [historical bar documentation](https://interactivebrokers.github.io/tws-api/historical_bars.html)
states that `TRADES` history is adjusted for splits but not dividends, while
`ADJUSTED_LAST` is adjusted for both. An
[IBKR Campus example](https://www.interactivebrokers.com/campus/contributors/retrieving-historical-data-from-ibkr/)
repeats that distinction. Consequently, an old `TRADES` bar retrieved after a
split cannot be labelled raw as-traded merely because its source is IBKR.
`ADJUSTED_LAST` cannot be the split-only analytical input because it also
adjusts for dividends.

IBKR's [bar type reference](https://interactivebrokers.github.io/tws-api/classIBApi_1_1Bar.html)
describes OHLC as double-precision values. Its published information does not
establish that inverting an adjusted historical OHLC bar always recreates each
original exchange tick exactly, nor does the split-adjustment statement specify
whether historical share volume can be recovered as raw traded volume. Those
properties require a separate evidence check for each affected symbol.

## Proposed authority and calculation

1. The operator supplies a dated, versioned ASX corporate-action extract or
   cited ASX notices for each security. ASX describes its
   [ReferencePoint corporate-action data](https://www.asx.com.au/connectivity-and-data/information-services/reference-data)
   as covering splits, dividends and other major actions. The extract records
   security identity, action type, ex-session, exact rational share ratio,
   dividend amount/currency where relevant, publication version and source
   reference. The operator confirms rights and coverage before use. IBKR's
   [Wall Street Horizon event fields](https://www.interactivebrokers.com/campus/wp-content/uploads/sites/2/2023/09/WSHEclassesandfieldsforIBAPI2022-12-23.pdf)
   include split ex-date and new-to-original share ratio, but that service
   would be corroboration only if separately approved and available.
2. Use IBKR `TRADES` final daily bars as the primary split-only price series.
   Convert the approved share ratio to the exact ex-session *price* ratio
   (original shares / new shares). Apply the cumulative rational price factors
   to raw as-traded OHLC, keeping dividends separate and never adjusting
   analytical prices for them. Preserve original IBKR response, action
   references, retrieval time and all calculation versions.
3. For a historical session before any later split, reverse the cumulative
   factor from `TRADES` only as a candidate raw OHLC. Accept it only if all
   four recovered prices are exact ASX ticks and independent as-traded evidence
   confirms them. An archived pre-split IBKR response is suitable evidence;
   exchange trade records supplied by the operator can verify the inverse but
   do not replace IBKR as the primary bar source. Verify raw volume separately.
   ASX's published Daily Official List description mentions close and volume,
   not a full OHLC set, so that product alone is insufficient to verify all
   four prices.
4. If an action is missing or ambiguous, an inverse fails tick or OHLCV checks,
   independent raw evidence is unavailable, or raw volume cannot be
   established, that symbol abstains. No forward fill, dividend-adjusted input,
   Yahoo replacement, rounded reconstruction or guessed factor is permitted.

The operator decision requested is whether to approve ASX action evidence as
the split-factor authority and what independently retained raw-price/volume
evidence may be used for split-affected historical sessions. Any pilot with
real IBKR or ASX records, subscription change, or backfill needs separate
authorization. The conservative default is to abstain for affected symbols.
