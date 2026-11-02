# Append-only authority continuity implementation plan

> Implement natively against DS's adopted 2 November design and simplified schemas. Use a fresh independent branch review before delivery.

Goal: recover a contiguous missed-session range without rewriting any original authority, daily line, accepted bar or halt watermark; resolve and freeze the approved nine-name scope once per pass.

Base b111437 (whose base is e89203a). One branch phase3/authority-continuity; local only, no push. No real ledger/store/authority/approval/successor file writes. No Gateway or order path. No strategy/backtester/ticks edits. OCA remains frozen and separately attended; daily task is unchanged.

1. Test-first interface: session/base-bound immutable selection drives source requests, frozen active inputs and quality eligibility. No managed union or re-selection broadens cards. Missing scope has no raw fallback.
2. Strict independently pinned evidence: exact ten-field catch-up approval and six-field restriction successor per DS. Manifest is opaque SHA-256 only, not parsed. No signed_at, prefix hash or operational-root approval fields. Approval signing date lies between range end and actual recorded_at date. Ordinary loads check approval/successor bytes; dry/apply/independent verification also rehash review.
3. Physical catch_up_v1 record: legacy eight-field lines remain unchanged. Expand approved-calendar trading sessions, exact contiguity from tip, no overlap/gap/future session. Previous hash and sequence bind independently approved expected tip. No retroactive shadow pass or backdated daily rows.
4. Writers share pure validation; default dry-run writes nothing; apply validates again under exclusive ownership, fsyncs one append, fresh reader verifies. Daily 4 November appends after the five-session range. Temporary lock is removed by its owner; a preexisting/stale lock refuses, never repaired automatically.
5. Verified restriction narrows original membership: MFG last active30October, effective2November; no BJY, rename or history edit. The catch-up record binds successor state for subsequent daily lines. Source fingerprint is frozen in snapshot. Both shadow paths use the same selection and refuse missing successor after retirement.
6. Focused/full offline suite, Ruff/Black/mypy/Bandit; fresh independent code review; local commit and immediate all-branch backup; branch-only e89203a-prerequisite bundle (includes approved b111437 ancestry), diff against b111437 and independent restore.

Tests must preserve original file bytes and ledger prefix, accepted rows and MFG halt watermark; reject malformed/hash-changed evidence, bad dates/ranges, unknown fields, changed tip and competing writers; allow ordinary loads without review bytes but require them at writes/independent verification. Prove one source resolution, no CLI repeat and no data request for unavailable scope. Only temporary fixtures execute writers.

B1/B2 are separate evidence work; B2 waits until Tuesday's16:20task has stopped. Actual reviewed evidence, DS-created signed approval/successor hashes, auditor-confirmed commit and explicit application authority remain prerequisites. C is draft only. No runtime application is authorised by this build.
