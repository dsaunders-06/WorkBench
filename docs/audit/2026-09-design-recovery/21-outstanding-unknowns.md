# QAT Design Recovery & Design Intent Audit, R21: Outstanding Unknowns

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §19, section 21; brief §21: "If the evidence is insufficient, say:
UNKNOWN — INSUFFICIENT EVIDENCE." Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026, by collecting every NOT DETERMINED and
UNKNOWN from R3–R24. Each entry gives what would settle it. Nothing here was
guessed to fill a gap.

## 21.1 Settled since first raised

R4 §4.13 listed six intent questions as UNKNOWN on the premise that the
sessions were lost. The transcripts cover every day from 24 July (CE-020), and
R6 §6.0 answered all six from them:
* the operator authorised autonomy (AE-05);
* the operator accepted the paper's human-approval rule as the starting state
  only (AE-01);
* how the first commit was built (AE-01, AE-02);
* swing first, not alone (AE-05, AE-08);
* the AI's role in entries was approved, then dropped by Claude (AE-05);
* "learning" means evidence and backtesting (AE-13).

They are not repeated below (CE-036).

## 21.2 Intent: the operator's to settle

| # | Unknown | Where raised | What settles it |
|---|---|---|---|
| U1 | **How large the AI's part in the recommendation is**: originating it, confirming it, or adjusting it. Q1 settles that it forms the recommendation | R4 §4.001; R18 §18.1 | the operator |
| U2 | **Q-R11**: whether the 8 Sep "the LLM operates exclusively as an editor and copywriter" applies to the matrix only, or to the AI generally | R11 §11.7 | the operator, at Checkpoint B |
| U3 | **The intended regime inputs for an ASX book.** The paper names them by concept only; re-sourcing was deferred | R7 #11; R18 §18.1 | the operator |
| U4 | **The live-trading path**: no design detail agreed | R18 §18.1 | the operator, after evidence accumulation |

## 21.3 The broker: a broker read, or runtime observation

| # | Unknown | Where raised | What settles it |
|---|---|---|---|
| U5 | **Why JHX's resting stop did not fill below its trigger** (11 Sep) | R10 §10.4; R16 §16.1; tracker section 2 | the TWS Orders panel (status, trigger price, trigger method). Held by the operator until after the audit |
| U6 | Whether `reqExecutions` returns other client ids' executions | R5 §5.4; R10 §10.5 | runtime observation |
| U7 | Whether a 202 on a bracket child can reverse a real entry | R5 §5.4; R10 §10.5 | runtime observation |
| U8 | How an adopted leg's fill is classified | R10 §10.5 | runtime observation |
| U9 | Whether IBKR's `avgFillPrice` is populated when `place_order` returns, and whether the permId is present at transmission | R5 §5.4 | runtime observation |

## 21.4 The records: what the files cannot show

| # | Unknown | Where raised | What settles it |
|---|---|---|---|
| U10 | ~~Why the retained log has no lines from 10:06:27 to 11:12:37 on 24 Aug~~ | R12 §12.5; R13 §13.6 | **Settled 15 Sep.** Commit `ab5175d` records it: Claude's session watcher held the log open and rotation failed silently. `qat.log.6`'s size matches the commit's figure (CE-037, CE-038) |
| U11 | Which of TNE's executions on 3 Sep was the 60 shares the ledger booked | R13 §13.7 | IBKR's execution-level report for 3 Sep |
| U12 | Why DXS's 24 Aug unwind sales never reached the app's absorption | R13 §13.7 | UNKNOWN — the log after 14:07:51 carries nothing for it |
| U13 | ~~Who or what realigned the LOV repair row on 27 Aug~~ | R13 §13.7 | **Settled 15 Sep**: Claude's `repair_collapsed_row.py`, after the operator's "do it now" (R13 §13.7) |
| U14 | ~~Which message authorised the LOV repair (26 Aug) and the SEK repair (9 Sep)~~ | R13 §13.7 | **Settled 15 Sep**: both operator-approved (LOV: option "1", 15:09; SEK: "App is closed", 17:15, in answer to "Close the app and I'll start on the ledger repair"). R13 §13.7 |
| U15 | Whether a symbol excluded as stale cost any entry (exclusions are not logged as events) | R9 §9.2 | UNKNOWN — INSUFFICIENT EVIDENCE for the past; a log line would settle it in future |
| U16 | Whether the price-drift check ever evaluated a price and passed (it logs refusals and skips only) | R10 §10.5 | as U15 |
| U17 | Why the 24 Aug 11:21 run's recovery label held until the run ended; and whether TNE's recovery-labelled decisions at 10:21–10:35 were the launch artefact | R12 §12.6 | UNKNOWN — the second falls in the log hole (U10): its cause is now known, but the lines were never written |
| U18 | Why three launches were configured for the local model on port 8000; how many AI Advisor questions were asked before 28 Aug | R11 §11.8 | UNKNOWN — the log records only failures, and the per-question line began on 28 Aug |
| U19 | Whether Yahoo's daily history includes today's partial bar; startup races between feeds and subscribers | R5 §5.4 | runtime observation |

## 21.5 Measurement the audit could not make cleanly

| # | Unknown | Where raised | What settles it |
|---|---|---|---|
| U20 | **How much of the HMM's own classification the US columns decide.** The 28 Aug ablation is confounded for `vix_level` and `yield_curve_slope` (CE-032) | R12 §12.3 | a re-run with the rule path held constant: research, not a change to the app, and only if the operator asks |
| U21 | Whether the correlated-cluster cap can bind at 10 positions | R9 §9.2; R15 C16 | more positions, or a replay |

## 21.6 The complexity flags (R15 §15.3)

Ten answers R15 flagged unclear. The six not already above:
* whether the gate's fixed session times are still wrong, which
  `ib_hours.py` was built to replace (C6);
* whether an exit without `Orchestrator.stop_all` leaves anything
  half-written (C9);
* why `DGS3MO` and `DGS10` are fetched at all (C11);
* whether the cash cap or the engine is meant to decide an entry's size
  (C18);
* whether the governor's two valuation bases are intended (C30);
* whether a regime label that resets at launch and moves within minutes meets
  the intent of "sticky" (C31).

The rest are C16 (U21 above), C22 (the three answers to what is held), C23
(the identity machinery's untested paths) and C29 (which record is the
decision record). They are questions for Phase 4 rather than unknowns about
the past.

## 21.7 The count

21 unknowns were listed (U1–U21), plus the six complexity flags of §21.6.
**Three were settled in the back-fill** (U10, U13, U14), which leaves **18
open**:
* 4 are the operator's to decide (U1–U4);
* 5 need a broker read or runtime observation (U5–U9);
* 7 concern the records:
  - 5 cannot now be settled (U12, U15–U18);
  - 1 needs IBKR's execution-level report (U11);
  - 1 needs runtime observation (U19);
* 2 need measurement (U20–U21).
