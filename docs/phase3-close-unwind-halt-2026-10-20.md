# Phase 3 paper close: 20 October partial unwind and halt

**The paper account is not flat.** Four approved closes completed; the fifth halted before its market sell because a cancellation did not settle. Independent inventory found the remaining position without a confirmed protective stop. No close retry or further order was attempted. Hold this evidence branch unmerged for DS review; the Wednesday automation remains paused.

The run used clean `unwind/close-script` commit `4632d655d8ae28c9557623a8e20526bc6167d6a2`, auditor-confirmed with green CI [39337739969](https://github.com/dsaunders-06/WorkBench/actions/runs/39337739969), and the DS-reapproved action-list SHA-256 `acc578fa5df3bf65a6f9372a796d860a8dc500b686a4ceced50423db6a963978`. The first 10:09 halt was valid under the original comparison rule. DS then corrected the rule: visible account, positions and working-order identity/terms/status must match; marks and balances, earlier-session completed orders and earlier-session executions are recorded only. The resumed independent inventory matched on every required field. Verify-only resolved the pending identity and cleared only its matching exit-recovery plan. The first reset attempt failed to persist because of a filesystem permission error, and the run stopped without a close.

Under a fresh DS instruction at 11:45 AEDT, step 4 was repeated without repeating verify-only. The independent book still matched. The reset dry run confirmed the original reason; one operator-attributed apply with data-directory write access then persisted a clear switch. A fresh process independently read the clear state, and the immediate post-reset broker inventory matched the pre-reset book.

One close-only `--execute` run was launched with the approved settings, list, hash and window. Its per-holding outcome, in approved sequence, was:

| Holding in approved sequence | Outcome |
| --- | --- |
| 1 | Full sell independently confirmed. |
| 2 | Full sell independently confirmed. |
| 3 | Full sell independently confirmed. |
| 4 | Full sell independently confirmed. |
| 5 | Halted before market sell; cancellation and protection require fresh DS review. |

Independent broker evidence contains 39 executions for the first four closes and none for the fifth. Every execId, quantity, price, reqExecutions time and commission report is preserved outside Git. The broker library logged an 11-hour streamed/requested execution-time discrepancy; raw timestamps are retained for audit. The script and independent inventories agree that the remaining holding was not sold. The persisted kill switch is clear. The close log showed no store-write failure; the halt was the unsettled cancellation.

The raw report and detailed account evidence remain outside Git. The close-run report SHA-256 is `150d7b39e22f56b053341b01de1043ccb76c19324a6be99353c2686cfefc472c`; the immediate post-halt independent inventory is `013e22d863819b9d5a670240fa4c7572b5fe465a4062c890e4c57f22df066a85`; the latest read-only follow-up is `370db76369eeb37c53ae65dcef6026742fc8e8346e9785b237811a54d019b963`. The 39-row execution CSV is `94636b3871b43db8deab238a7371d16e329a843286e15cbb251235291cfedbea`. The pre-close and post-halt 56-file store-manifest SHA-256 values are `19dee1f16a6f508710049976f7e5d26c7f7f6f507c421febf9dc2e9596db21d9` and `695fd5fb95368b87b6824de11701b36a03a821eade8445ece829b7e121b63bb8`. Seven changed stores were independently re-read and matched the post-halt snapshot; all other copied stores were unchanged. The private review and evidence are in `C:\Users\mailm\Documents\Codex\phase3-close-unwind-20261020-run`.

Production files changed: none. Scripts changed on this evidence branch: none. Tests changed: none. This branch changes only this redacted report. Further protection or close action requires a revised DS instruction.
