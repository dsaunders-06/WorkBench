# Phase 3: recommend-mode integration — draft implementation plan

**Status:** planning only. No code, data release, app run, order or Stage B
work is authorized by this document. The [draft specification](phase-3-recommend-mode-integration-spec.md)
and [Phase 2 closure](phase-2-closure.md) govern the proposed work.

1. **Freeze the operational contract.** Decide bar source priority, the ASX
   close/finality cutoff, revision handling, universe membership and calendar
   authority. Define the `OPERATIONAL` record schema and explicit separation
   from sealed research and shadow outcomes. Review the Phase 4 real-money
   limits before any live-account enablement.
2. **Build the three-year history store.** Ingest finalized raw and split-only
   daily bars with source/version hashes. Detect gaps, duplicates, ordering,
   corporate-action mismatches, stale sessions and insufficient history;
   fail closed per symbol. Test backfill and correction as appended versions.
3. **Build one adapter around the pure engine.** Schedule it after bar
   finality, pass a frozen operational snapshot, preserve exact Decimal
   evidence, and map only `QUALIFIED` setups to immutable card candidates.
   Extend transitive-import and runtime isolation tests before UI wiring.
4. **Integrate cards with Phase 1 risk and OMS.** Show pattern evidence,
   entry limit, stop, Phase 1-sized quantity and risk, source age, and the
   mandatory unvalidated label. Require `recommend` mode, paper by default,
   a fresh risk calculation and explicit human sign-off for each OMS order.
   Test rejection, expiry, changed inputs, application restart and auto-mode
   misconfiguration without transmission.
5. **Append the shadow lifecycle.** Record every card and disposition in an
   append-only store; add hypothetical replay events as later finalized bars
   arrive, independent of paper fills. Test idempotence, correction lineage,
   corporate actions, halts and terminal handling. Keep the store outside
   promotion evidence and prevent retroactive selection of an effect or rule.
6. **Review and rehearse paper-only operation.** Run isolated fixtures and
   supervised paper rehearsals only after implementation review. Verify
   no-autonomy gates, source-failure abstentions, card/OMS reconciliation,
   append-only records and rollback. Real money requires a separate operator
   decision on the Phase 4 limits and an operational release review.

Open design decisions for the operator: the approved bar vendor/broker and
failover order; exact daily finality time and correction window; calendar and
universe authorities; retention and access policy for the append-only shadow
record; how long a card remains actionable after close; and numerical Phase 4
position, sector, aggregate-risk, liquidity and gap limits. None is frozen by
this plan.
