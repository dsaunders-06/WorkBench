# 27 October OCA exit-handoff paper probe — build for review

This isolated script is an experiment for G2, not production exit support or evidence of continuous broker protection. No run is scheduled or authorised by this build. DS must approve the reviewed commit and the exact private approval-file SHA-256 separately. No QAT application, AI, OMS or live account is involved.

## Fixed scope and start conditions

`scripts/phase1_oca_exit_handoff_paper_probe.py` is date-gated to 27 October 2026, 11:30 inclusive to 15:30 exclusive Australia/Sydney. No new order or cancel is sent at or after 15:30. Start once, with a flat approved paper account and no working orders, localhost Gateway 4002, order client 1 and independent read-only client 99. The exact DS-specified account is pinned by its SHA-256 in the script and supplied only in the private approval. Every wire request rechecks that it is the sole managed account. Client 99 cannot place, cancel or bind orders. Do not start another client using either ID.

Use a separate private directory named `phase1-oca-exit-handoff-20261027`, outside every Git working copy. DS supplies `approval.json`; the script never creates or signs it. Its eight exact fields are account, approved_by `DS`, approval_date `2026-10-26`, session `2026-10-27`, symbol `BHP.AX`, operator `DS`, cap_per_order_aud `800`. A separately approved exact SHA-256 is mandatory. An exclusive attempt lock is claimed before connecting; never remove it to retry. The build does not provide a signed file, digest or launch instruction.

A minimum A$500 reference parcel, rounded up to whole shares with at least two shares, follows the existing local paper-probe convention. Every order is checked against A$800. A limit buy is bounded by its limit price. Protective and cleanup market orders use the observed IBKR ask as the sizing reference; a market fill cannot guarantee an A$800 realised value. This limitation must remain in the auditor/DS approval, rather than being described as a guaranteed execution cap. Bid, ask, reception timestamp and market-data type are recorded. No other data source is used.

## Experiment, types 2, 3, then 1

For each type, confirm a flat book with no working orders, buy the minimum parcel, then place a SELL stop and target in a single fresh OCA group. Confirm both working before submitting an approximately half-parcel market SELL in that same group. The initial acquisition-to-protection interval is recorded too; the script does not claim the initial buy is continuously protected.

Client 99 polls positions and all open orders about once per second. Every snapshot records the holding, stop status, remaining stop quantity, group/type, order identities and raw position/order evidence. Gaps in poll coverage are recorded. A stop counts as protection only if it is a working SELL stop in the pinned group with unchanged stop terms and exactly the remaining holding. Broker OCA quantity reductions are allowed; action, order type, group/type and prices are pinned.

After the half sale, an exact remaining stop leads to a second same-group handoff for the balance. A missing or undersized stop leads immediately to market cleanup using the last IBKR reference, without waiting for execution-detail requests or restoring a stop. The unprotected interval is a finding. If a market exit itself partially fills while protection disappears, cancel its unfilled remainder once and wait until terminal before submitting cleanup; never create two independently executable exit sales. If any working SELL exceeds the holding, oversell safety takes precedence and no further order is sent.

Resolve all buys/market exits before any cleanup sale. Do not cancel protective legs while shares remain just to make an exit possible. Only after client 99 confirms zero holding may outstanding owned orders be cancelled. Dispatch each necessary cancel once before waiting; PendingCancel, including an unsolicited PendingCancel, is waited through without resending. Inactive is also waited through. Waits are bounded by 15:30 and may last more than 20 minutes. An unresolved order stops the experiment and requires DS action. The next type requires independent flat/no-working-order confirmation.

## Halts, evidence and interpretation

Safety halts are exact-account failure, unrelated position/order, changed order identity/terms, ambiguous transmission acknowledgement or oversell risk. They forbid further transmission. Evidence failures and ordinary experiment states are recorded; bounded cleanup can proceed only with fresh account, position and order checks. A failed observation is not proof of broker rejection or of a protection gap.

The final independent client-99 inventory is attempted after both completion and a halt, including a safety halt; it never transmits. Unknown or invalid holdings are reported as unavailable, never truncated or inferred from an earlier snapshot. Any held shares, working orders, unavailable final inventory or halt produces **DS action required**, with the independently observed held quantity or explicitly unavailable quantity.

Private raw JSON includes every client-99 snapshot, protection intervals, SDK errors/status/fill/commission events, requested orders and cancels, reqExecutions evidence and completed orders, final inventory and its timestamp. The final report prints its path and SHA-256. Keep all raw evidence and account identifiers outside Git. Review acceptance/joining for every OCA type, stop quantity after every fill, both handoffs, all cancel states and final flat state.

One-second sampling cannot prove uninterrupted protection between polls. Absence of an observed oversell does not prove IBKR blocks overfill; type-specific observations and any unanswered question must be reported explicitly. This probe deliberately tests partial exits; it does not deliberately create an oversell race to manufacture a blocking result. G2 remains open unless the broker evidence supports its full acceptance criteria.

## Offline validation

Tests use real ib_async Trade, OrderStatus, Execution, Fill and CommissionReport objects behind a fake broker and clock. They cover type order and half/full exits, type-1 stop cancellation, disappearing and oversized stops, delayed cancels, unrelated exposure, holding changes during a quote, ambiguous acknowledgements, changed protective terms, prompt gap cleanup, intermediate partial fills, independent final inventory and invalid final quantities. No Gateway connection or order-capable script execution occurs during tests.
