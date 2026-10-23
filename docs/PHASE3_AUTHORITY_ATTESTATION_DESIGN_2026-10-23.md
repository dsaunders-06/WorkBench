# Phase 3 daily authority attestation — review draft

**Status:** branch proposal for DS and auditor review. Do not use it to run
cards until the branch is reviewed, CI is green, and it is merged. The four
23 October authority files retain their DS-approved hashes.

The calendar, membership, halt and corporate-action files contain historical
facts and citations. A day with no new event does not rewrite any of them. The
separate `OPERATIONAL/authority_attestations.jsonl` file advances their daily
validity after the [approved maintenance audit](PHASE3_TEN_SYMBOL_AUTHORITY_MAINTENANCE_DRAFT_2026-10-23.md).
Each line records a monotonically increasing sequence, ASX session, all four
approved file SHA-256s, the daily audit evidence SHA-256, named operator,
Australia/Sydney timestamp, previous record hash and its own content hash.
Lines are appended with a flush and filesystem sync. The loader checks the
entire chain, strict fields and consecutive scheduled ASX sessions from the
fixed files' base validity date. It refuses a broken chain, a missing trading
session, a changed current file hash or an incomplete line.

The attestation supplies an **effective** valid-through date. It does not
change a loaded authority object or its content hash. The operational adapter
records the attestation hash in its frozen snapshot, uses the effective date
for all four authority-age gates, and uses it for the v2 membership interval
without discarding an entry's individual effective-to date. The approved
read-only script checks the exact four DS-approved hashes and the ledger before
fetching a card. The configured shadow runner also refuses stale files or a
missing/broken attestation. An unchanged 23 October file set without a 26
October attestation therefore abstains on Monday.

`scripts/attest_phase3_authorities.py` is an offline dry-run/apply tool. It
requires an existing OPERATIONAL namespace, the four approved hash arguments,
the reviewed daily audit file and its hash, a named operator, and the current
ASX session after 16:20. Apply appends exactly one line; a duplicate or skipped
session refuses. The authority files are only read. If an event changes a file,
DS must approve its new SHA-256 before the attestation may name it. Preserve
each superseded file and its approval evidence privately by hash for audit.

This hash chain detects accidental or unreviewed edits against an already
recorded head; it is not a digital signature. Keep a separately recorded head
hash with the daily report so wholesale replacement of the private ledger is
detectable. No broker, OMS or order API is part of the attestation tool.
