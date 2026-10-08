# Phase 3: recommend-mode integration — draft implementation plan

**Status:** planning only. Step 1 is the operator-frozen contract in the
specification; implementation steps 2–6 are not yet authorized. No code, data
release, app run, order or Stage B work is authorized by this document. The
[specification](phase-3-recommend-mode-integration-spec.md)
and [Phase 2 closure](phase-2-closure.md) govern the proposed work.

1. **Record the operational contract — complete as a document.** IBKR is the
   sole primary bar source; Yahoo only cross-checks. Generate cards at about
   17:30 Sydney time after bar finality, accept versioned corrections through
   the next session's open, use ASX calendar/notices and dated quarterly
   S&P/ASX 200 membership, and expire cards at the next open. Keep the
   `OPERATIONAL` namespace separate from sealed research and shadow outcomes.
   Retain backed-up append-only shadow records indefinitely. The Phase 4
   starting limits are for pre-live evaluation, not active paper controls.
2. **Build the three-year history store — not authorized yet.** Ingest
   finalized IBKR raw and split-only daily bars with source/version hashes;
   log Yahoo cross-checks without substituting them. Detect gaps, duplicates,
   ordering errors, corporate-action mismatches, stale sessions and insufficient history;
   fail closed per symbol. Test backfill and correction as appended versions.
3. **Build one adapter around the pure engine — not authorized yet.** Run it
   after the verified 17:30 Sydney-time close workflow, pass a frozen
   operational snapshot, preserve exact Decimal evidence, and map only
   `QUALIFIED` setups to immutable card candidates.
   Extend transitive-import and runtime isolation tests before UI wiring.
4. **Integrate cards with Phase 1 risk and OMS — not authorized yet.** Show
   pattern evidence, entry limit, stop, Phase 1-sized quantity and risk, source age, and the
   mandatory unvalidated label. Require `recommend` mode, paper by default,
   a fresh risk calculation and explicit human sign-off for each OMS order.
   Expire each card at the next ASX open and revoke it on an accepted correction.
   Test rejection, expiry, changed inputs, application restart and auto-mode
   misconfiguration without transmission.
5. **Append the shadow lifecycle — not authorized yet.** Record every card
   and disposition in an append-only, indefinitely retained, backed-up store
   with read-only review access; add hypothetical replay events as later
   finalized bars arrive, independent of paper fills. Test idempotence, correction lineage,
   corporate actions, halts and terminal handling. Keep the store outside
   promotion evidence and prevent retroactive selection of an effect or rule.
6. **Review and rehearse paper-only operation — not authorized yet.** Run
   isolated fixtures and supervised paper rehearsals only after implementation
   review. Verify
   no-autonomy gates, source-failure abstentions, card/OMS reconciliation,
   append-only records and rollback. Real money requires a separate operator
   decision on the judgment-based Phase 4 starting limits (10% single
   position, 5% total stop risk, 25% sector, 2% minimum stop distance and 1%
   of 20-day median volume) and an operational release review.

Implementation details still requiring review include how IBKR confirms a
final bar, how a Yahoo discrepancy is surfaced without substitution, the
calendar-notice ingestion and conflict workflow, the exact correction and
card-revocation event schema, and shadow-store access and backup mechanics.
The operator must evaluate and decide the Phase 4 starting limits before any
real-money release. None of these details authorizes steps 2–6 now.
