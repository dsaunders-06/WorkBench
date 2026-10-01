# Phase 1 stable startup replay checkpoint

Date: 25 September 2026

Status: verified locally; not deployment or trading approval.

## Safety boundary

Startup recovery now obtains one stable broker view before it changes the position-entry record, closed-trade ledger, absorbed-fill state or tracked position quantities. It reads positions, fills, positions, fills and positions in sequence. The two canonical fill snapshots and all three position-quantity snapshots must agree.

If the broker view changes during capture, recovery retries from a clean observation. After three unstable attempts, the kill switch trips and startup recovery leaves the ledger, synthetic lot and fill watermark unchanged.

## Replay behavior

- The stable fill snapshot sizes any synthetic lot needed to record an exit missed while the app was stopped.
- The same snapshot is passed into fill absorption; absorption does not issue another broker fill query.
- Tracked quantities are resynchronised from the position map captured with that snapshot rather than a later independent query.
- Fill responses are reduced to one highest cumulative receipt per broker order before snapshots are compared.
- A fill arriving after the final snapshot remains above the captured scan watermark and is handled by the next normal sweep.
- Strategy selection, signal generation and order submission are unchanged.

## Verification

- Three new startup-replay regressions pass: changing fill visibility retries, permanently unstable fills fail closed, and changing positions fail closed.
- OMS, safety, performance and broker suites: 1,395 passed.
- Complete repository suite: 3,761 passed, 26 skipped, 1,097 existing warnings in 350.70 seconds.
- Ruff passed.
- Black passed (578 files unchanged before this Markdown-only checkpoint file was added).
- Mypy passed over 186 source files.
- Bandit passed; its existing comment-parser warnings remain.
- `git diff --check` passed.

## Remaining limits

This checkpoint closes the Phase 1 requirement for coherent startup replay across a changing broker view. Phase 1 still requires explicit migration of legacy entry records without an accounted quantity and controlled application of historical corrections. The recovery build has not been deployed and no trading resumption is approved.
