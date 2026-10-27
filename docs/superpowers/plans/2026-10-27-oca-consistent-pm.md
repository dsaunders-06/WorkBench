# Consistent OCA snapshots and delayed sibling settlement

> Execute inline with TDD and one fresh final review. DS's corrected27October prompt supersedes the Wednesday-only prompt.

**Base:** 0a0a1bd; branch probe/oca-exit-handoff-20261027. Bundle prerequisite e89203a. Offline only; no push, Gateway, real approval creation, schedule or probe execution. Do not write/replace anything under the morning phase1-oca-exit-handoff-20261027 directory. Its70-file before manifest is stored outside it under qat-offline-20261027/oca-pm-consistent-build.

**Delivery:**14:00 AEDT; if verification cannot finish, report the miss and deliver for Wednesday rather than bypass a check.

## Binding behavior

- Positions/open-orders/positions per snapshot, including final/settlement reads. Different position identities/quantities invalidate the poll; no gap, protection or overage conclusion. Immediate account, unrelated-order/position, fractional and negative holding guards remain.
- Record each owned SELL overage. Per-owned-order condition must persist for10seconds across consecutive consistent polls; unavailable or cleared evidence resets its streak. During the grace period no new exit is added. Persistent oversized SELLs are cancelled once, settled first, then ordinary emergency cleanup runs. Exact-account/ownership checks are never bypassed by permission to cancel own SELLs.
- PM27 start14:45 inclusive–15:00 exclusive, separate phase1-oca-exit-handoff-20261027-pm output/approval/lock. Wednesday28 start11:30–15:00 exclusive. Both hard end15:30; later cleanup may operate before hard end after a valid start. Approval signing date must be on/before session, hash-bound; no signature/file is created by this build.

## Steps

- [x] Baseline144 offline tests; write RED cases for all five requested scenarios and corrected session/directory gates.
- [x] Central consistent-book reader; per-order grace streak; safe ordered cancellation/terminal settlement; updated finalization path.
- [x] Adapt superseded tests, retaining observed IBKR decoder fixtures and prior safety regressions; focused GREEN.
- [x] Fresh whole-change independent review; regression fixes; full suite/Ruff/Black/mypy/Bandit.
Post-commit delivery operations (local commit, immediate all-branch backup, branch-only bundle, independent restoration and protected-directory verification) are recorded in the external delivery report.

## Review focus

1. No mutation/conclusion from an inconsistent position pair; every settlement/final read uses the same protocol.
2. Streaks reset on unknown evidence and cannot be advanced twice from one snapshot.
3. Three lagging sibling polls never halt or add an unsafe exit;10-second persistence cancels only owned oversized SELLs first, once.
4. PendingCancel settles without resend; immediate transmission guards still block unsafe market orders.
5. Start-window15:00 differs from hard-end15:30; the morning27 directory is rejected before any write.

## Review and verification evidence

Baseline 144 focused cases passed. Requested replays first failed (18 failed, six passed), then passed with the consistent-book and delayed-sibling implementation. The focused suite now has 182 passing cases, including two wire-price variants, active-monitor transient/persistent lag, timer reset after an inconsistent snapshot, Windows case-insensitive morning-directory rejection, and hard-end versus start-cutoff gates.

Fresh independent whole-change review found a finalization regression: inconsistent positions, or a mixed own/foreign order response, could discard observed live owned orders when the owner's cache was terminal. Both counterexamples were reproduced RED and fixed by retaining order-lifecycle evidence before later book validation. Position evidence remains unavailable; retained orders authorize waiting only. The reviewer rechecked both fixes and reported no residual material findings. Existing foreign-exposure transmission halts remain binding for new orders.

Ruff, Black, mypy (226 source files) and Bandit passed after the final source changes. Full-suite completion and bundle verification are recorded in the external delivery report. The superseded/incomplete full-suite passes were stopped after source changes; they are not reported as successful verification.

The 14:00 AEDT delivery deadline was missed; at the recheck the current time was 14:50 AEDT. Delivery is for Wednesday review. No PM attempt is authorised by this build, and no run or wake-up is created. The source retains the exact two requested session windows; no start gate is extended.

Final full suite: 4812 passed, 24 skipped, 1095 warnings in 501.83 seconds. Focused: 182 passed. All required static checks passed. No production files changed.
