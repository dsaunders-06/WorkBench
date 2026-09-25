# Phase 1 release repair design

**Date:** 25 September 2026  
**Status:** Approved design; implementation not started  
**Branch:** `recovery/phase-1-safety-and-truth`  
**Base:** `master` at `5757fd28d96453441a9514b9c696a027b2e46247`

## Purpose

Close the merge-blocking defects found by the complete Phase 1 review without changing strategy selection, signal generation, risk sizing, thresholds or autonomous-trading policy. The repaired recovery layer must preserve one broker execution exactly once across late broker identity resolution, process restart and subscriber failure. Startup and repair tooling must leave evidence unchanged whenever required truth is missing or inconsistent.

This work remains inside Phase 1, **Safety and truth**. Merge, packaging, deployment, first launch and resumption of autonomous trading remain separate controlled actions.

## Findings being repaired

1. A partial fill can first be recorded under the application's order UUID and later arrive under IBKR's permanent ID. If the process restarts around that resolution, the cumulative receipt can lose the relationship between those IDs and apply the full cumulative quantity again.
2. `TradeLedger` can repair an old CSV header during construction, before startup has established a stable broker snapshot.
3. A confirmed sell with no matching lot, or with a timestamp before the lot it would close, can be treated as successfully consumed even though no durable ledger record represents it.
4. The historical-correction command checks one executable name but does not exclude a source-launched QAT process or close the check/write race.
5. A malformed or unreadable position-entry store is treated as an empty first run, allowing startup to continue without durable quantity, basis, strategy and replay evidence.

## Chosen approach

Use one canonical execution identity and make every remaining evidence-integrity failure fail closed. This is narrower than replacing the persistence layer and stronger than patching each alias symptom independently.

The canonical identity for an application order is its application UUID. A broker order that carries that UUID as its order reference resolves to the same identity even when IBKR later reports a permanent numeric ID. Broker orders with no application reference keep their broker ID as their canonical identity.

## 1. Canonical execution identity

### Broker boundary

`BrokerFill` gains an optional application order ID. The IBKR translator copies `Execution.orderRef` into it when the reference is a QAT application order ID. The adapter publishes late-ID resolution whenever both IDs exist; it must not depend on the process-local submitted-order map, which is empty after restart.

Other broker adapters may leave the application ID absent. Existing broker-only execution behavior remains valid.

### OMS identity resolution

The OMS resolves every cumulative fill to:

- a canonical execution ID;
- all known aliases, including the broker permanent ID and application UUID;
- the matching durable order context, when one exists.

Resolution occurs before the foreign/own-order decision, delta calculation, pending-delivery ID construction or subscriber publication.

For a QAT order, pending delivery IDs and subscriber `fill_id` values use the canonical application UUID. A cumulative fill observed first through the application ID and later through the broker ID therefore names the same receipt.

### Durable transition

Late identity resolution persists enough information for either durable file to recover safely if the process stops between writes:

1. persist the application-to-broker identity;
2. make every known alias point to the same cumulative receipt in fill state;
3. persist fill state before permitting the durable order identity to be retired.

On restart, either the durable order identity or the persisted fill aliases must be sufficient to recover the canonical receipt. When an older receipt already exists under a broker ID, resolution adopts its cumulative quantity and all consumer receipt IDs rather than starting a new application-ID receipt. A completed order identity may be removed only after the complete cumulative quantity and its aliases are durable.

Entry records, open lots and commission accumulation use the canonical order identity. Late resolution may add a broker alias for lookup, but it must not create a second quantity, cost floor or ledger receipt.

### Required crash cases

Tests must cover an order that records four shares under its application UUID and later reports ten cumulative shares under its broker ID:

- restart before the broker ID is resolved;
- restart after durable identity resolution but before fill-alias persistence;
- restart after fill-alias persistence;
- replay after the order identity has been retired;
- repeated cumulative ten-share observations.

Every case must finish with ten shares, one order-level commission calculation and no duplicate lot or ledger quantity.

## 2. Confirmed execution delivery

The performance ledger's critical fill consumer must account for the complete confirmed execution delta or fail the delivery.

For sells, lot matching returns the matched and unmatched quantities. A temporally impossible match or any unmatched residual raises a dedicated persistence/reconciliation error before the receipt is marked processed. Previously staged in-memory lot and commission changes are restored.

The EventBus reports the critical subscriber failure to the OMS. The OMS then:

- restores its pre-delivery in-memory state;
- retains the pending cumulative receipt;
- leaves the fill watermark unchanged;
- trips the kill switch with a reconciliation-required reason.

The recovery does not invent cost basis or P&L for an adopted position. Resolving an unmatched execution requires evidence-backed reconstruction or an explicit future reconciliation record.

## 3. Read-only startup until broker truth is stable

Constructing `TradeLedger` must not rewrite `closed_trades.csv`. Loading accepts the existing append-only schema rule: an older header may be a strict prefix of the current fields, while wider, reordered or otherwise incompatible rows are refused.

After the OMS captures a stable positions/fills snapshot, startup may run an explicit ledger-schema migration before restoring lots or replaying fills. That migration:

- verifies the current file still matches the bytes that were inspected;
- creates and verifies a byte-identical backup;
- writes the corrected header to a temporary file;
- flushes and atomically replaces the ledger;
- reopens and validates the result;
- restores the original automatically if post-write validation fails.

An unstable or unavailable broker snapshot returns before this migration, leaving the ledger byte-for-byte unchanged. A migration failure trips the kill switch and stops bridge startup before lot restoration or fill replay.

## 4. Position-entry evidence

Only `FileNotFoundError` means a first run with no entry records. Permission errors, malformed JSON, a non-object root, malformed rows and non-finite or invalid numeric fields are evidence failures.

The bridge records the load failure, trips the kill switch and refuses startup replay or migration. It does not overwrite, quarantine, rename or partially load the source file. A later operator repair must work from the preserved bytes and independent broker evidence.

Legacy but valid rows remain supported and continue through the approved quantity migration.

## 5. Shared operational data lock

QAT acquires an operating-system-backed exclusive lock in the fixed application-state directory before legacy-layout migration, settings construction or any component that can read or mutate operational records. The fixed location avoids needing to read configuration before the lock exists and also prevents two instances configured with different data paths. QAT holds the lock until normal shutdown; the operating system releases it if the process crashes.

The historical-correction command acquires the same fixed application lock before its final validation and holds it through backup, staging, replacement, verification and journal publication. Failure to acquire the lock is a refusal. The lock works for packaged and source-launched QAT processes and removes the process-name race. Tests inject a temporary lock path; production resolves it from the application-state path rather than the current working directory.

The existing process-name check may remain as an explanatory diagnostic, but it is not authority to write. A stale lock file without an active operating-system lock does not block recovery.

## 6. Compatibility and migration

- Existing `absorbed_fills.json` files without aliases remain readable. Their current keys become canonical broker-only identities until a durable application mapping proves otherwise.
- Existing `inflight_orders.json` records provide the application/broker mapping used to canonicalize receipts after restart.
- Existing valid entry rows without quantity remain eligible for the approved legacy migration.
- Existing current-schema ledgers require no migration and are not rewritten.
- No strategy, signal, risk or autonomy configuration semantics change.

## 7. Verification

Implementation proceeds test-first, one finding at a time:

1. canonical late-ID crash matrix and commission/lot assertions;
2. unmatched and impossible sell delivery remains pending and halts;
3. unstable startup leaves ledger bytes unchanged and stable migration is backed up and atomic;
4. corrupt entry evidence halts without mutation;
5. packaged-name and source-process lock contention refuse correction.

After focused tests pass, run the wider OMS, broker, performance and safety suites, then the complete repository suite. Ruff, Black, Mypy, Bandit and Git whitespace checks must pass. A fresh independent review must cover the complete repair diff, followed by GitHub CI on the published tree.

## 8. Release boundary

After the repairs pass review, Phase 1 receives a new release identity rather than reusing M175. The release checkpoint will document the exact commit, tree, tests and remaining operational boundaries.

The first deployed launch will use the paper account in `recommend` mode with autonomous strategies cleared. It is a supervised migration event because all nine current position-entry records are legacy records. Before launch, the operational data and configuration receive verified backups. After launch, the operator verifies the packaged build stamp, paper account, stable snapshot, legacy-entry backup and migration, positions, open orders, protective stops, kill-switch state, ledger audit and absence of unintended transmissions.

Autonomous paper trading does not resume as part of this repair or deployment.
