# QAT Design Recovery & Design Intent Audit, R20: Simplification Candidates

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §16 ("Produce a simplification candidate list"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026. **Nothing is changed.** The brief: "Do not
actually make the change." Every recommendation is one of the brief's six:
KEEP; KEEP / MONITOR; INVESTIGATE; CONSOLIDATE — FUTURE WORK; REMOVE — ONLY
AFTER AUTHORISATION; UNKNOWN.

The candidates are R15's inventory, C1–C35. Evidence is cited there and not
repeated in full. The development freeze and brief §1 apply: even a
"REMOVE" here is a recommendation for the operator, to be acted on only in
Phase 5 (Controlled Simplification) and only with explicit authorisation.

**Two rules applied to every row**
1. **A safety control is not removed because it looks redundant** (brief §1).
   Controls that have never acted are KEEP / MONITOR unless the record shows
   they cannot act at all.
2. **A decision the operator has already taken is not re-opened.** Rows C7
   and C13 (closed 10 Sep) and C5 (the M175 repair) are KEEP on that ground.

## 20.1 The list

| # | Candidate | Why it looks unnecessary | Evidence | Potential benefit | Potential risk | Recommendation |
|---|---|---|---|---|---|---|
| C1 | `data/validation.py` | no caller; the app never imports it | complexity tool §2; R7 #10 | a tested pipeline stops implying protection the app does not have | the paper requires validation (P §17); retiring it would settle a design question by deletion | **INVESTIGATE**: wire it per the paper, or record that it is not wanted |
| C2 | `data/store/` and the two storage settings | never imported; persistence is CSV and JSON | tool §2; `db.py:12-13` | 98 lines and two settings that do nothing go | none found | **REMOVE — ONLY AFTER AUTHORISATION** |
| C3 | The research harness (1,823 lines) | not in the app | tool §2 | — | losing the only way to test a change offline (AE-13) | **KEEP / MONITOR**: a replay's wiring must be checked against the live engines before its results are used (the 28 Aug retraction; CE-032) |
| C4 | `preflight.py` (850 lines) | nothing runs it automatically | tool §2; `tasks.py` and `deploy.ps1` do not call it | checks that cannot be forgotten, or one fewer place to maintain | its VIX check covers a setting the regime does not read (R12 §12.3) | **INVESTIGATE**: run it at deploy or launch, or state that it is manual |
| C5 | `performance/fill_basis_repair.py` | a one-off, applied 12 Sep | R13 | a smaller product tree | it is the record of how the 12 Sep repair was made | **KEEP** (with C27 later) |
| C6 | `broker/ib_hours.py` | built 9 Sep, not wired | tool §2 | — | the auction model it was built for is still modelled from fixed times | **INVESTIGATE** |
| C7 | `data/ibkr_news.py` | not wired | tool §2 | — | — | **KEEP**: closed by the operator (outstanding item 11) |
| C8 | `broker/ib_probe.py` | not in the app | used by 8 scripts | — | losing live broker diagnosis | **KEEP** |
| C9a | `get_trade_rationale` and the output guard | no caller | R7 #56 | — | under Q1 the AI forms the recommendation, and this is the only code that checks an AI answer against the limits | **KEEP** |
| C9b | `Orchestrator.stop_all` | never called | investigator 4 §1.1 | — | ⚑ whether an exit without it leaves anything half-written | **INVESTIGATE** |
| C9c | `audit_closed_trades` | no caller in the app | R5 §5.3 #18 | — | a ledger self-check that runs only when someone runs it | **INVESTIGATE**: whether it should run at startup |
| C10 | `FeatureEngine` and `FeatureEvent` | computes on every tick; nothing subscribes | `feature_engine.py:52`; investigator 1 C | less work in the tick path; one fewer of three feature computations | none found | **REMOVE — ONLY AFTER AUTHORISATION** |
| C11 | Fetching `DGS3MO` and `DGS10` | the regime ignores them | R12 §12.1; `regime_monitor.py:588-603` | a driver table that shows only drivers | the AI's macro prompt receives them | **INVESTIGATE**: label them, or stop fetching |
| C12 | The 20-bar refit schedule | never runs; the model refits at each launch | R12 §12.1 | the stated schedule matches the real one | — | **INVESTIGATE** |
| C13 | Corporate-action hooks (M39) | cannot fire on IBKR | R14 incident 5 | — | — | **KEEP**: closed by the operator, 10 Sep |
| C14 | Gate: pause buys below −4% day P&L | the −3% kill switch acts first, re-checked every minute | `equity_monitor.py:134-140`; R7 #34; R9 (never acted) | one fewer day-loss threshold to reason about | loses the minute after a reset | **CONSOLIDATE — FUTURE WORK** (with the daily-loss rail) |
| C15 | Gap budget | never acted; overlaps the aggregate cap | R7 #29; R9 | — | **stops do not always hold**: JHX closed below its stop on 11 Sep | **KEEP / MONITOR** |
| C16 | Correlated-cluster cap | empty on all 68 approved buys | R9 | — | it matters once more names, or larger ones, are held | **KEEP / MONITOR** |
| C17 | Single-name cap | cannot bind under placeholder Kelly or the cash cap | R9 | — | it binds once measured Kelly or a larger cash cap applies | **KEEP / MONITOR** |
| C18 | The cash cap cutting after the engine | it overrides the engine's sizing on 18 of 20 entries | R9; R12 §12.4 | one place decides an entry's size | — | **INVESTIGATE**: which is meant to decide size |
| C19 | Promotion scorecard, off on paper | it reads as a gate and is not one on paper | R7 #2; R16 §16.2 | — | it is the evidence rule for live trading (AE-01, AE-13) | **KEEP / MONITOR** |
| C20 | VaR 95 and 99, not gated | computed and unused by any rail | R5 §5.3 #14 | — | the paper asks for it to be reported | **KEEP** |
| C21 | "Unknown IBKR code → halt" | 7 of 19 trips, none for a real unknown hazard | R14 | fewer false halts; less exposure to CE-017 | a genuinely new error would pass unhalted | **INVESTIGATE** (Phase 4 safety review; the operator directed it, AE-28) |
| C22 | Booking at transmission, with its reversal, three price-correction paths and a repair script | the common root of many incidents | R14 §14.3 | one answer to "what is held" | the operator kept it on 3 Sep (AE-28); the alternative was judged too large then | **INVESTIGATE** (Phase 4) |
| C23 | Broker-id identity machinery | aliases and re-keying | R14 incident 10; CE-029 | — | it prevents double absorption of the app's own fills | **KEEP / MONITOR** |
| C24 | Resting-order scan's quarantine | right 1 time in 10 | R10 §10.2 | fewer false entry refusals | orphans are real (24 Aug, 4 Sep) | **INVESTIGATE**: the false-positive rate |
| C25 | In-flight tolerance and the anomaly store | extra reconciliation logic | R14 incident 3 | — | false halts return | **KEEP** |
| C26 | The missed-exit replay | loses shares from partial fills | R13 §13.2 | a correct ledger | — | **INVESTIGATE** (open item, tracker section 2) |
| C27 | Seven repair scripts | one-offs; six left no mark in the record | R13 | one audited repair path that marks what it changes | — | **CONSOLIDATE — FUTURE WORK** |
| C28 | Two leg-cancel implementations | two ways of doing one thing, in opposite order against the kill switch | R5 §5.3 #5; CE-017 | one tested path | — | **CONSOLIDATE — FUTURE WORK**, in the CE-017 decision (Phase 4) |
| C29 | Two decision records, and the "blocked" heading | they count different things | CE-029; R7 #59 | one record of each decision; a truthful heading | the journal's dedupe keeps it readable | **CONSOLIDATE — FUTURE WORK** |
| C30 | Two valuation bases in the governor | the same position valued two ways | R5 §5.3 #13 | one basis | ⚑ they may be intended | **INVESTIGATE** |
| C31 | The regime's label and mass | two outputs, one of which settles only minutes after launch | R12 | — | — | **INVESTIGATE** (with R12's launch artefact) |
| C32 | Staleness in two places | two rules | investigator 1 B; CE-022 | — | each does a different job | **KEEP**; the false docstring is in C33 |
| C33 | Prose in the code (37%), some of it false | history and argument kept beside the code | tool §4; CE-018, CE-022, CE-032 | code that states only what it does; claims kept where they can be checked | losing explanations that are right | **CONSOLIDATE — FUTURE WORK**: move history to the records, correct the false claims |
| C34 | `version.py`'s 2,035 lines of milestone history | the history is in git and HANDOFF | tool §4 | a 67-line module | — | **REMOVE — ONLY AFTER AUTHORISATION** (the comments, not the build stamp) |
| C35 | 27 backups in the data folder | many, unindexed | R13 | — | they are the evidence of each repair | **KEEP / MONITOR** (index, never delete) |

## 20.2 The recommendations, counted

| Recommendation | Rows |
|---|---|
| KEEP | C5, C7, C8, C9a, C13, C20, C25, C32: **8** |
| KEEP / MONITOR | C3, C15, C16, C17, C19, C23, C35: **7** |
| INVESTIGATE | C1, C4, C6, C9b, C9c, C11, C12, C18, C21, C22, C24, C26, C30, C31: **14** |
| CONSOLIDATE — FUTURE WORK | C14, C27, C28, C29, C33: **5** |
| REMOVE — ONLY AFTER AUTHORISATION | C2, C10, C34: **3** |
| UNKNOWN | none: **0** |

37 rows: C1–C35, with C9 split into three.

## 20.3 What the list says

* **Only three removals are recommended, and none is a control**: an unused
  storage layer, an unused feature computation, and comment history. They
  are the cheapest simplifications and change no behaviour.
* **Most of the weight is INVESTIGATE**, because the costly complexity is
  live: it came from fixes (C21, C22, C24, C26) or it decides more than it
  appears to (C18, C31). These belong to Phase 4 (Safety Review), not to a
  clean-up.
* **The safety controls that never acted are kept** (C15–C17, C19). The
  record shows only that they have not been needed yet. JHX's gap through
  its stop shows why the gap budget exists.
