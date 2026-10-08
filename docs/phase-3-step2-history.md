# Phase 3 step 2 — operational history boundary

Operator authorization on 9 October 2026 covers steps 2 and 3 only. The frozen
contract remains binding; the older "not authorized yet" plan status describes
the document-freeze checkpoint, not this later authorization. Steps 4–6 remain
on hold. Phase 2 source is unchanged.

`qat.operational.history` contains no vendor clients. `IBKRBarSource.fetch`
returns immutable `OperationalBar` values; `FakeIBKRSource` supplies recorded
fixtures or an explicit failure. `ingest_session` abstains on source failure,
missing symbols, wrong sessions, non-IBKR source, or unfinished bars. Yahoo's
`compare` port emits audit notes only and cannot supply bars.

The store requires an explicit directory named `OPERATIONAL`, outside the
repository, research and promotion roots. Callers must provide all protected
roots. A namespace marker is checked on every database access. Symlinks,
junctions and hard-linked databases are rejected. Unknown existing stores are
refused before SQLite opens them. There are no research/promotion imports,
configuration discovery, or default paths. Only synthetic test databases are
created in this stage.

SQLite bars are append-only, with database triggers preventing UPDATE/DELETE.
A per-symbol/session version chain hashes the complete payload, version,
acceptance disposition, independent receipt time, namespace, calendar hash and previous hash. Retrieval
time and timezone, finality, raw OHLCV, split-only OHLCV, exact rational factors,
verified corporate-action markers, split ratio, dividend, exchange and currency
are retained. The caller supplies a timezone-aware receipt timestamp independently from vendor
retrieval time; receipt cannot precede retrieval. Corrections received at or before
the ledger's next open become accepted
versions; later corrections append audit versions without replacing the
accepted decision view. An initial historical ingestion is permitted as a
backfill representation; this does not authorize real backfill.

Integrity checks record sorted blocking reasons for expected-session gaps,
staleness, unexpected sessions, duplicate/out-of-order ingestion, invalid
OHLCV/volume, off-tick raw prices, unverified actions, negative dividends,
split-only price mismatches and split-factor discontinuity. `split_ratio`
means the ex-session raw-price ratio (for a two-for-one split, 1/2), not the
share-count ratio. Dividends never enter analytical prices or split factors.
No forward fill or source substitution exists. Ingestion structural faults
remain blocked pending review; this stage provides no unblock operation.
Three calendar years of complete, finalized history are required. Departed
symbols listed as managed retain quality checks but cannot receive new cards.

## Authority file schemas

Both files are UTF-8 JSON. Dates are ISO dates; timestamps include UTC offsets.
Duplicate JSON keys, malformed types, unordered/duplicate sessions and symbols,
and invalid authority versions fail closed. Fixture files are synthetic,
explicitly marked `fixture: true`; their source URLs are provenance placeholders
and are never fetched. The operator supplies real files in a later stage.

Calendar (`asx-calendar-v1`): `schema`, positive integer `version`,
`published_on`, `coverage_start`, `coverage_end`, `source`, boolean `fixture`,
`sessions` (ordered objects containing `session` and timezone-aware `open`),
`closures` (objects containing `session` and an HTTPS ASX `notice`). The
published ledger is authoritative; the repository rule calendar cross-checks
it. A cited ad hoc closure amends the authority; uncited disagreements block.

Membership (`asx200-membership-v1`): `schema`, positive integer `version`,
`published_on`, `effective_from`, `effective_to`, S&P `source`, boolean
`fixture`, sorted unique `symbols`, and sorted unique `managed_symbols`.
The effective interval is inclusive, bounded and versioned, so a stale file
cannot silently extend membership. Managed symbols are explicit input from
operations, not discovered by importing OMS or position stores.

## Verification boundary

The entire test suite denies socket connection, DNS resolution, datagram sends
and async network connections. Windows' standard-library socketpair constructor
is preserved solely for internal IPC needed by asyncio; application loopback
and external connections remain denied. Network-dependent behavior must use doubles. No application
wiring, real data download, vendor connection, UI, OMS, order submission,
shadow lifecycle or paper rehearsal is part of this stage.
