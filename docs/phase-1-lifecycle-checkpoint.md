# Phase 1 lifecycle checkpoint — 22 September 2026

Draft recovery work only. Do not merge or deploy this checkpoint. Master and operational records are outside the change scope.

## Implemented

Order transmission no longer creates a position or ledger lot. Confirmed positive execution quantities and prices drive own-order and broker-side accounting through the same cumulative-delta path. Partial execution followed by rejection retains executed shares; incomplete execution evidence halts new order flow.

Late broker identity resolution now runs during normal IB execution queries using the submitted order reference. The event updates OMS aliases, bridge entry identity and ledger lot/commission identity within the running session.

New entry records retain the execution-accounted quantity. Startup restores that quantity before replaying later executions. The regression case (40 shares before shutdown, 100 cumulative shares at restart) now restores 100 rather than 160 shares, with the tested weighted cost basis. Partial and complete offline sells are also covered. A partial sell notification keeps the entry for the accounted remainder even when the broker is already flat.

## Validation

- Full suite: 3,734 passed, 26 skipped, 1,097 warnings in 298.42 seconds.
- Ruff, Black, Mypy (185 source files), Bandit and Git whitespace checks passed.
- Tests used isolated data paths and an offscreen UI. No operational application, broker connection or trading order was used.
- The earlier safety/replay checkpoint passed GitHub CI. This checkpoint requires its own CI result.
- Independent review of this lifecycle checkpoint is incomplete; the reviewer reached its usage limit. Local inspection and tests do not replace that review.

## Blocking work before deployment

1. Legacy entry records without an execution-accounted quantity still use the older inferred baseline. They require explicit migration/reconciliation; the new restart regression does not prove legacy recovery safe.
2. Entry records, cumulative-fill state and ledger event delivery are not one crash-atomic transaction. Interrupted writes or subscriber failures can still separate these records. Durable quantity persistence is not a claim of exactly-once recovery.
3. Replay preparation and absorption still make separate broker queries. Broker state changing between them, and the later position resynchronisation, need a coherent snapshot/replay design and failure-injection tests.
4. Pending order metadata and late application-to-broker identity do not yet survive every restart. Current-session identity coverage must not be generalised to crash recovery.
5. The manual PositionCloser path still needs the shared protection recovery mechanism and matching failure tests.
6. Historical statement reconciliation and a separate TNE correction proposal were produced in the recovery workspace. No historical ledger correction has been applied; dependent analytics and missing round trips remain to be reconstructed.

The entry record is an aggregate position record, not a durable FIFO lot journal. Multiple entry orders and intervening sales require explicit lot-level persistence; the weighted-average partial-fill test only establishes the covered single-order case.
