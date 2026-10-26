# Attested Actions Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the already-verified attested-through date consistently to the two remaining operational actions coverage-end checks.

**Architecture:** Keep the existing attestation schema, chain verification, approved-hash checks and loader ownership unchanged. Pass the verified session from each existing shadow loader to the IBKR historical source; use max(coverage_end, attested_through) in source conversion and history quality assessment. The existing adapter already passes its verified date to history assessment.

**Tech Stack:** Python 3.12, pytest, existing temporary authority ledgers, offline IBKR client doubles.

**Spec:** DS's revised A instruction of 26 October; docs/PHASE3_AUTHORITY_ATTESTATION_DESIGN_2026-10-23.md. The earlier explicit-field stop is superseded; no new field or schema is authorised.

## Global Constraints

- Local branch phase3/attested-actions-coverage from e89203a; no push, merge, Gateway/account/web access, production runtime execution or shadow rerun.
- Do not change authority files, ledger records, approved probe branches, real OPERATIONAL store or volume-revision decisions.
- No new ledger reads or chain verification; no schema change. No attestation supplied means existing coverage_end behavior.
- No edits under authoritative_swing, backtester or broker/ticks.py.
- List all src changes separately from scripts/tests/docs; back up the branch outside the working copy after each commit; deliver e89203a-based bundle and checks by 21:30 AEDT.

## Review Focus

1. A trusted date must reach both historical conversion and quality assessment; a regression must fail if either remains unchanged.
2. Both the read-only script and configured shadow runner must forward the date only after their existing verified loader succeeds.
3. An attestation must not extend the historical coverage_start, invent calendar sessions, reopen per-symbol membership intervals or weaken bar validation.
4. An expired/missing/broken attestation or changed approved actions hash must still fail closed before a card source runs.
5. Ledger/authority bytes and loaded authority content hashes must remain unchanged during reads; no real store is touched by tests.

## Task 1: Reproduce, plumb, verify and bundle the consistent coverage rule

**Files:**
- Modify src/qat/operational/ibkr_history.py: optional attested_through constructor argument, default None; source conversion effective end.
- Modify src/qat/operational/history.py: assess_history effective actions end using its existing optional date.
- Modify src/qat/operational/shadow.py and scripts/phase3_shadow_readonly_check.py: forward the date only when existing loader returned a verified attestation hash.
- Add focused temporary-copy regression tests and an authority-age comparison inventory document.

**Interfaces:** IBKRHistoricalBarSource(..., attested_through: date | None = None); assess_history(..., attested_through: date | None = None) retains its current signature. Existing loader outputs/return signatures and all authority objects remain unchanged.

- [x] Step 1: Establish clean offline baseline. The initial attempt lacked the parent test-temp directory and failed fixture setup; create that parent and verify the existing attestation tests before rerunning the full baseline. Do not change product code to fix test-environment setup.
- [x] Step 2: Write a failing behavioral regression: October 23 action files, an intact October 26 attestation over their hashes, and October 26 data must pass conversion AND history actions coverage. Verify that the unchanged implementation fails for coverage, not a setup error.
- [x] Step 3: Add table-driven boundary cases: at/before end, verified extension, session beyond attestation, and no date. Add existing-loader rejection tests for chain/hash failures that produce a shadow abstention with no cards, using only offline clients and temporary files. Check unchanged authority/ledger bytes.
- [x] Step 4: Implement the optional date and max end rule; forward the already-verified date at both source construction sites. Search all src coverage_end/valid_through comparisons; change only identical unbridged gaps.
- [x] Step 5: Run focused tests; correct failures. Run full suite and exact repository Ruff, Black, mypy and Bandit checks. Record commands, exit codes, counts and any limitations outside Git.
- [ ] Step 6: Obtain one independent final review, address material findings with regression tests, commit locally, immediately back up the branch, create and independently verify the e89203a-based bundle, and report SHA-256/head/files/results. Do not merge or push.

## Execution decisions

The user's detailed revised instruction supplies the implementation design and authorisation, so no additional design approval is requested. Execute inline and use one fresh final reviewer. A's earlier stop report is historical and superseded by this correction; it must not be mistaken for the current result.

Native worktree creation reported "Not a git repository" for the chat's projectless folder. A separate local worktree was therefore created from the known repository and exact approved base. Recovery remains at its frozen head.

## Verified implementation checkpoint

The offline full baseline passed: 4,630 passed, 24 skipped. The first behavioral regression failed at the original source gate (4 failed, 7 passed); extending only that source still exposed the history gate (3 failed, 8 passed). Both fixes plus caller plumbing passed the six-file focused set (120 passed); the final new test file, including the additional coverage_start case, passed all 12 cases. The final complete suite passed: 4,642 passed, 24 skipped, with the same 1,095 third-party warnings as baseline.

Repository-wide Ruff and Black passed (780 files unchanged); mypy passed all 226 source files; Bandit exited zero with no findings and existing comment-parser warnings. Restricted-process async test/formatter stalls were resolved by running the same offline checks on the host; no test failure was repaired by weakening product behavior or test assertions.

One fresh independent final reviewer found no material issues in the complete change, regression tests, or authority-age inventory. Commit, immediate external branch backup, bundle restoration verification and final head/hash reporting are the delivery portion of Step 6 and are recorded after the commit in the private delivery report.