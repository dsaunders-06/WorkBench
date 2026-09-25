# Phase 1 legacy entry quantity migration checkpoint

Date: 25 September 2026

Status: verified locally; not deployment or trading approval.

## Safety boundary

Startup now settles every legacy position-entry record that lacks an execution-accounted quantity before it restores ledger lots or replays broker fills. It uses the same stable broker snapshot for migration, lot restoration and replay.

For each legacy record, the quantity at the saved fill watermark is reconstructed from the current broker quantity minus the signed unabsorbed fill deltas. A partial offline sell therefore restores the full pre-exit lot before applying the sell, while a fully closed position still produces its closed trade.

Before any migrated record is written, the original `open_position_entries.json` is preserved byte for byte as `open_position_entries.json.bak-pre-quantity-migration`. A pre-existing backup must match the source exactly. A backup failure, impossible negative quantity or fill predating the recorded entry trips the kill switch and leaves the active entry file unchanged.

Flat legacy records with no pre-replay quantity are removed from the active book. Their original evidence remains in the migration backup, preventing an unrelated later position in the same symbol from inheriting stale entry metadata.

## Startup behavior

- Legacy symbols are registered for fill lookup before the stable snapshot is captured, including symbols no longer present in the broker position list.
- Quantity migration runs before entry-price and strategy reconciliation.
- Lot restoration reads positions from the captured stable snapshot rather than querying the broker again.
- Missed-fill replay consumes that same snapshot.
- A completed migration is restart-idempotent and does not duplicate a closed trade.
- Strategy logic, risk sizing and order submission are unchanged.

## Preserved-data dry run

The preserved application entry file contains nine legacy records without quantities. Against the 24 September read-only IBKR paper snapshot, six correspond to held positions and would receive broker-backed quantities; three are flat and would be retired from the active book. The dry run found no contradictory quantities. No preserved or live application record was changed.

The live AppData directory remains unreadable through its Windows ACL, so this checkpoint does not claim that the preserved file is byte-identical to the current application file. Deployment remains a separate controlled step.

## Verification

- Six migration regressions pass: partial offline exit, full offline exit, flat stale record, contradictory evidence, backup failure and restart idempotency.
- OMS, safety, performance and broker suites: 1,400 passed.
- Complete repository suite: 3,767 passed, 26 skipped, 1,097 existing warnings in 340.35 seconds.
- Ruff passed.
- Black passed (579 files unchanged).
- Mypy passed over 186 source files.
- Bandit passed; its existing comment-parser warnings remain.
- `git diff --check` passed.

## Remaining limit

This checkpoint closes the Phase 1 legacy entry quantity migration blocker in code. Phase 1 still requires controlled application of the independently prepared historical corrections. The recovery build has not been deployed and no trading resumption is approved.
