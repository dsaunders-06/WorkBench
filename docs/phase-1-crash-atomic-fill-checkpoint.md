# Phase 1 crash-atomic fill checkpoint

Date: 24 September 2026

Status: verified locally; not deployment or trading approval.

## Safety boundary

A confirmed broker fill is now journalled before any subscriber receives it. The journal entry remains pending until every critical durable consumer succeeds and the cumulative receipt is atomically saved. A critical failure trips the kill switch, rolls back the OMS's in-memory accounting, preserves the pending delivery, and does not advance the broker-fill watermark.

The trade ledger and position-entry store are the critical consumers. Optional display and diagnostic subscribers retain the existing log-and-continue behavior.

## Replay behavior

- Entry records store stable cumulative-fill identities with their accounted quantity in one atomic JSON replacement.
- Closed-trade rows store the same fill identity.
- Every set of closed-trade rows produced by one fill is written as one atomic ledger replacement.
- Open lots restored from entry records restore their processed buy-fill identities.
- A pending delivery is replayed before the next broker query, including after process restart.
- Replaying a successful entry write does not add the quantity twice.
- Replaying a partial close does not close the remaining lot twice, in the current process or after restart.
- Failed entry or ledger writes leave the fill pending and halt order flow.
- A corrupt fill-delivery journal restores no authority to trade; the kill switch trips for operator review.

Older entry JSON and closed-trade CSV rows remain readable. Their missing fill identities mean unknown rather than already delivered.

## Verification

- Four new crash and replay regressions pass.
- OMS, performance and safety suites: 1,016 passed.
- Complete repository suite: 3,758 passed, 26 skipped, 1,097 existing warnings in 347.84 seconds.
- Ruff passed.
- Black passed (578 files unchanged).
- Mypy passed over 186 source files.
- Bandit passed; its existing comment-parser warnings remain.
- `git diff --check` passed.

## Remaining limits

This checkpoint makes delivery of a confirmed fill replay-safe across the OMS, entry record and closed-trade ledger. It does not complete Phase 1. Coherent replay across changing broker snapshots, explicit migration of legacy entries without an accounted quantity, and controlled application of historical corrections remain open. Strategy logic is unchanged.
