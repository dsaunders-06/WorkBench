# Managed OCA Entry and Halt Cleanup Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh whole-branch review after verification.

**Goal:** An approved paper probe retains responsibility for every own entry/order until terminal or the window deadline, with emergency cleanup for non-transmission halts.

**Spec:** DS's 27 October revision instruction, items 2a–2e. The morning cb7eb9d evidence is preserved privately and is not modified.

**Architecture:** Keep order client1/read-only client99 and all normal OCA tests. Separate transmission halts from cleanup halts; settle every owned order once before one ungrouped emergency market exit. Final flatness uses one client99 positions/orders snapshot. Thread the approval session through deadlines, refs, directories and exclusive revision/session locks.

**Scope:** Modify only the OCA script, its offline tests, and its documentation. No src changes, push, merge, schedule, probe execution, authority/store change or approval-file creation. Recovery e89203a and GTD d70370f stay fixed. Back up the single local commit immediately; deliver only this branch in an e89203a-based bundle by13:15 AEDT.

## Review focus

- A pending entry with a zero position must not be called flat or disconnected before terminal/deadline.
- Cleanup must bypass the reason for a terms mismatch while retaining exact-account, ownership and oversell transmission guards.
- A cancel/fill race must use fresh holdings and terminal buys/SELLs before one market exit; no duplicate cancellation or second executable sale.
- Transmission halts must never send a cleanup order; read-only terminal/deadline observation remains possible.
- Session28 and signing date27 must work without reopening the morning27 attempt or accepting its old26 approval.

## Task 1 — regressions, implementation, verification and delivery

- [x] Record baseline; change fake wire values to observed ungrouped ocaType3, and add pending-entry/zero-position and halt-class regressions. Run RED before source edits.
- [x] Compare group/type only when placed in an OCA group. Classify only account/foreign exposure/oversell as transmission halts; all other halts trigger guarded emergency settlement/exit.
- [x] Guarantee terminal observation until15:30; report own unresolved orders and held quantity at deadline. Flat requires a single fresh client99 snapshot with zero positions and no owned working orders.
- [x] Add27Oct14:00 and28Oct11:30 start gates,15:30 end, session-named approval and revision/session locks. Approval_date is the new file's actual signing date; accept27Oct for either session or28Oct for28Oct, never the superseded26Oct file. The approved hash binds DS's signing-date statement; the script does not sign or independently prove it.
- [x] Run focused/full suite, Ruff, Black, mypy and Bandit. Obtain fresh independent final review and resolve material findings with RED/GREEN tests.
- [ ] Commit locally, immediately back up, create branch-only incremental bundle, verify and restore it independently, report full hashes/head/diff/checks and any limitations.

## Execution ledger

11:45 AEDT: DS-confirmed read-only inventory is flat, no working orders. Offline work may proceed. The existing isolated OCA worktree is clean at cb7eb9d.

Ruling: the revised lock uses a new revision/session namespace, because the morning27 attempt lock must remain immutable and must not block the separately approvable afternoon revision; cost if wrong is rejection of a differently named operator-approved directory/lock. No run is approved by this build.


12:11 AEDT verification checkpoint: baseline90 passed; initial revised tests13failed/4passed RED; complete pre-review focused128 passed. The confirmed-fill/stale-zero cases each failed RED before reconciliation. Fresh independent review identified4Important conditions; the additional false-flat intermediate event was regraded Important because evidence readers must not infer a flat parcel after a partial emergency fill. All five counterexamples were reproduced (12RED cases, plus PendingCancel SELL variants). The one final fix pass now passes142 focused tests. The old cancel-dispatch fixture used live SELLs against zero holdings, which is now correctly a transmission halt; it was changed to two pending BUY entries to retain the dispatch-before-wait assertion without weakening the new oversell guard.

Final review fixes: incomplete final-book requests cannot qualify as flat; zero-held executable SELLs halt before cancels; transient cleanup book failures retry safely before the first cancel; foreign exposure reports promptly after own orders settle; terminal partial emergency exits record a residual and require DS action without a second sale or false-flat event. Final full suite is running after the fixes. The first full run was stopped during review and its partial log is not a full-suite result.

Ruling: classify the misleading intermediate flat event as Important and fix it in the single review pass — an auditor/operator could otherwise read it as protection/flatness evidence; cost if wrong is a stricter residual event instead of an incorrect success label. No review finding is being silently deferred. Actual Gateway behavior remains outside this offline review and needs the separately approved paper run.


Finalization audit: a last client99 snapshot can first reveal an owned PendingSubmit order after the earlier terminal check. The public-run regression failed in both wire variants because the script disconnected early. A read-only final-snapshot drain now observes that order until terminal/deadline and refreshes the final book; no new order/cancel is added. Focused set144 passed after this fix.

Ruling: extend the verified fix for explicit requirement2c when this later counterexample was reproduced — the prior4772-pass suite could not prove that new guard; cost is one additional full-suite run, kept within the13:15 deadline. This author-added guard has no second independent review; its RED/GREEN and fresh final full-suite results are reported transparently.


Final verification:144 focused passed; complete fresh suite4774 passed,24 skipped,1095 existing third-party warnings in489.62seconds. Ruff passed; Black783 unchanged; mypy226 source files clean; Bandit src plus changed script exited0 with no findings and existing comment-parser warnings. The code/test/fixture byte hashes match the verification input snapshot. Commit, immediate external backups and independent bundle restoration are recorded after the commit in the private delivery report. No src file changed, no push/merge/schedule/run occurred.
