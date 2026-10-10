# Phase 3 step 4: advisory recommendation cards

This stage uses finalised OPERATIONAL snapshots and the unchanged Phase 2
engine. It contains no real IBKR source, backfill, broker verification, or
order transmission. The cards panel accepts an injected operational card
service; normal application startup does not create one until the operator
supplies the operational authorities and source in a separately authorised
stage.

## Sizing and sign-off

The sizing basis shown on each card is **fixed 1% risk to stop, no edge
assumed**. Quantity starts with the Phase 2 engine's cost- and liquidity-aware
one-percent stop-risk quantity. Current Phase 1 cash, order-size, regime,
portfolio, cost, kill-switch and account-mode safeguards can reduce or refuse
it. The edge estimator and edge-based sizing path are excluded. Approval
recomputes quantity and risk from fresh paper-account equity and cash; a
change requires another explicit confirmation showing both values.

Approval records an immutable decision and reserves a deterministic OMS
application order ID derived from the card ID. The hand-off presents exact
manual TWS instructions for a buy in the next opening auction at or below the
limit, and the complete exit plan. The opening-auction transmission capability
flag is off; OMS and broker translators independently refuse this intent until
the real broker capability is separately verified. A DAY or GTC limit is not a
substitute, including when the Gateway has a GTC preset.

Display, approval and submission each check the next ASX open expiry and
accepted input corrections. A correction appends a revocation. Expired,
declined and revoked cards cannot be approved or submitted. Card decisions and
exit alerts use an append-only, hash-chained store in the OPERATIONAL namespace.

## Exit plan and managed positions

The entry sign-off covers a structural protective stop at fill, a resting
+1R limit for the rounded-up half, a move of the runner stop to breakeven after
the target fills, upward-only trailing, and close-invalidation or ten-session
time-stop exits at the next available open. The banked stop and target share an
OCA group; the runner has independent protection. Phase 2 precedence produces
one due exit. A documented halt leaves protection resting and defers the due
exit to the first resumed open. Advisory mode emits exact manual TWS alerts;
it does not submit these orders. Manual changes, greater exposure or looser
protection require fresh operator sign-off. A manual-management switch is
recorded while alerts continue.

The ASX corporate-action authority predicts post-consolidation whole shares.
The broker holding is authoritative. A mismatch freezes the symbol pending
operator reconciliation, with no automated changes or new cards. On a match,
the fractional share is treated as a realised cash-in-lieu sale. Fractional
basis is allocated pro rata using exact rational arithmetic, rounded to cents
half-even; residual cents stay with retained whole shares. No fractional
holding is created. Total basis remains in exact cents; per-share basis is for
display only.

This step records card decisions and alerts. The full shadow lifecycle and
paper rehearsal remain step 5 and step 6 and are not implemented here.
