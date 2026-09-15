# QAT Design Recovery & Design Intent Audit, R15: Accidental Complexity

**Brief §12 ("Identify accidental complexity"). DRAFT for Checkpoint B.**
**Prepared:** 15 September 2026. Read-only: nothing in the system was changed
and nothing is proposed for removal here. The brief: "Flag anything where the
answer is unclear. Do NOT remove it." Recommendations are in R20.

**Sources**
* The candidates named by earlier sections: R7's class **D** (agent-generated
  complexity) and **F** (overlapping control) items; R14's "secondary
  complexity" column; facts in R5 and R9–R13.
* A new read-only tool, `s12-s16-complexity/tools/complexity_inventory.py`,
  run 15 Sep on the tree at `ce5dec9` (`src/` level with the deployed M175).
  It builds the import graph from `qat.app`, the packaged build's only entry
  point (`QuantAdvisoryTerminal.spec:16`). `src/qat` has no dynamic imports,
  so a module outside that graph cannot run in the app. It also measures the
  prose in the code and lists settings with no reader.

**Left out on purpose**
* The retired US-era broker and price-source code. The operator decided on
  28 Aug to keep it as that era's evidence trail, and asked on 31 Aug that it
  not be cited as a cost or a reason for change.
* Two items the operator closed on 10 Sep: corporate actions (M39) and IBKR
  news. They appear below as facts only, marked **closed**, and are not
  re-opened.

---

## 15.1 Size and reach

From the tool (physical lines, comments and blank lines included):

* **184 modules, 51,473 lines.** The app can import **166** of them. **18
  modules, 3,827 lines, are never imported by the app**, and so are not in
  the packaged build.
* **Prose is 37% of the code**: 18,814 lines of `#` comments and docstrings
  against 27,786 lines of code. The heaviest cases:
  - `version.py` is 2,164 lines, **96% prose**: a milestone history kept in
    comments above one constant, `MILESTONE = "M175"`;
  - `config.py` is 73% prose;
  - the order core, `oms.py`, is 46% prose (1,317 of 2,842 lines);
  - `ib_adapter.py` is 43% prose.
* **Settings: 110 fields, and every one has a reader.** Three are read only
  indirectly: two through a `config.py` property, one by `getattr`. Two more,
  `storage_backend` and `database_url`, are read only by a module the app
  never imports (C2).

## 15.2 The inventory

The brief's nine questions per item, in order:

| Code | Question |
|---|---|
| **Why** | Why does this exist? Who decided? |
| **Problem** | What problem does it solve? |
| **Still?** | Is that problem still present? |
| **Real?** | Was the problem real or hypothetical? |
| **Elsewhere?** | Is another component already solving it? |
| **Trading?** | Does it change trading behaviour? |
| **Fail?** | Does it increase failure modes? |
| **Harder?** | Does it make the system harder to reason about? |
| **1 sentence?** | Can its purpose be explained in one sentence? |

⚑ marks an answer the evidence leaves unclear.

### A. Code the app never runs

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | `data/validation.py`, 134 lines: dedupe, outliers, gaps, timezone, corporate-action adjustment. No caller in `src` | the paper, P §17 and §20.D; first build, agent-only (R7 #10, CE-027) | bad data used silently | **yes**: the live path filters at the source only (investigator 1, B) | real | partly: the vendor's own adjustment, source filters, per-symbol staleness | no | no | **yes**: tested, and never run | yes |
| C2 | `data/store/` (`db.py`, `models.py`, `parquet.py`, 98 lines) and the settings `storage_backend`, `database_url` | first build, a database layer | persistence | no: CSV and JSON files do it | hypothetical | yes | no | no | slightly: two settings that do nothing | yes |
| C3 | The research harness: `backtester/` ablation, macro cache, manifest, replay session and sources, research universe, run comparison, and `evaluation/replay_agreement.py`, 1,823 lines. Used by scripts and tests | the operator: "backtesting is key to validating decisions" (AE-13) | measuring strategy and features offline | yes | real | no | no | **yes, for evidence**: a replay must copy the live wiring. It failed to on 28 Aug (the retracted runs), and its VIX ablation was confounded (CE-032) | yes: two copies of the engine wiring | yes |
| C4 | `preflight.py`, 850 lines. Run only by hand (`scripts/preflight.py`); neither the app nor `deploy.ps1` runs it | configuration traps found in live sessions | a configuration that looks right and is not | yes | real | partly: some warnings at launch | no | **yes**: its checks do not run unless someone runs them, and its VIX check covers a setting the regime does not read (R12 §12.3) | yes | yes |
| C5 | `performance/fill_basis_repair.py`, 417 lines, for the 12 Sep ledger repair (M175) | the operator's M175 runbook | the ledger's prices were not the fills | no: applied 12 Sep | real | yes: the startup price correction | no | no | some: repair logic in the product tree | yes |
| C6 | `broker/ib_hours.py`, 91 lines (9 Sep): parses IBKR's trading-hours strings. Not wired | the auction model (21 Aug dialog, "Full auction model", R7 #51) | session phases from the exchange's own hours | ⚑ the gate models phases from fixed times; whether that is still wrong is not established | real | ⚑ | no | no | yes: built and not connected | yes |
| C7 | `data/ibkr_news.py`, 124 lines (7 Sep). Not wired. **Closed** (outstanding item 11) | — | — | — | — | — | no | no | — | — |
| C8 | `broker/ib_probe.py`, 290 lines: a diagnostic used by 8 scripts | live diagnosis | reading the broker directly | yes | real | no | no | no | no | yes |
| C9 | Functions in the app with no caller: `get_trade_rationale` and the output guard (R7 #56); `Orchestrator.stop_all` (no engine is stopped on exit); `audit_closed_trades` (the ledger self-check); `regenerate_daily` (a script uses it) | first build (the first two); M175 (the audit) | an AI view checked against the limits; orderly shutdown; a ledger that agrees with itself | yes | real | no | no | **⚑ `stop_all`**: whether skipping it leaves anything half-written at exit is not established | yes | yes |

### B. Code that runs, but whose result nothing uses

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C10 | `FeatureEngine` computes features on every tick and publishes `FeatureEvent`, **which nothing subscribes to** (`feature_engine.py:52`). The strategy engine and the bridge each compute their own | first build (spec §D) | one feature computation shared by all | no: never used | hypothetical | yes, twice over | no | slightly: it runs inside the bus handler on every tick | **yes**: three computations of the same kind, one of them unused | yes |
| C11 | `DGS3MO` and `DGS10` are fetched hourly and shown in the Regime Monitor's **driver** table (`regime_monitor.py:588-603`), though the regime does not read them (R12 §12.1) | first build's series list | — | — | ⚑ | — | no | no | **yes**: a table of drivers showing two that drive nothing | yes |
| C12 | The regime's 20-bar refit schedule, which has never run: the model refits once per launch instead (R12 §12.1) | first build | keeping the model current | yes | real | yes: the refit at every launch | no | no | yes: the configured schedule is not the real one | yes |
| C13 | Corporate actions (M39): three hooks in the OMS and bridge for a detector that cannot fire on IBKR. **Closed** 10 Sep (R14 incident 5) | — | — | — | — | — | no | — | yes | — |

### C. Controls that overlap, or cannot bind

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C14 | Gate rail: **pause buys below −4% day P&L**, behind the kill switch's −3% daily-loss trip (R7 #34) | the reference app's "Moderate" profile | a bad day | yes | real | **yes**: the kill switch stops all sign-offs at −3%. It re-checks every 60-second equity poll (`equity_monitor.py:134-140`), so the −4% rail can refuse only in the minute after a reset or while polls fail | never acted (R9) | no | yes | yes |
| C15 | **Gap budget** (6% shock ≤ 5% of equity) beside the aggregate risk-at-stop cap (R7 #29) | the operator (AE-12 dialog) | a loss beyond the stops when prices gap | **yes**: JHX closed below its resting stop on 11 Sep (R9) | real | partly: the aggregate cap assumes stops hold | never acted (R9) | no | slightly | yes |
| C16 | **Correlated cluster 30%**: empty on all 68 approved buys (R9) | a third-party review (AE-08), batch | correlated positions sized as one | ⚑ it cannot form at 10 positions on the record | hypothetical so far | partly: sector 30% | never acted | no | slightly | yes |
| C17 | **Single-name 15%**: cannot bind while placeholder Kelly (12.5% notional) or the cash cap (10%) holds (R9) | the operator (AE-12) | one name too large | not now | real in principle | yes: Kelly and the cash cap | never acted | no | slightly | yes |
| C18 | **The cash cap cuts after the risk engine has sized**: 18 of 20 entries were cut below the engine's approved size, so Kelly, the 1% budget, the regime scalar and earnings set the final size on only 2 (R9; R12 §12.4) | the operator (AE-26) | one order too large for the cash | yes | real | ⚑ it overlaps the engine's own sizing and cash rule | **yes**: it sets most entry sizes | no | **yes**: the careful sizing upstream mostly does not decide the order | ⚑ no: "10% of cash" is one sentence, but what it does to the rails before it is not |
| C19 | **Promotion scorecard**: enforced on live only; the 30-trade bar is unreachable at current throughput (R7 #2, R16 §16.2) | the operator: autonomy "tied to tested rules" (AE-01); informed and left it off on paper (AE-06) | autonomy without evidence | yes | real | no | not on paper | no | yes: it reads as a gate and is not one on paper | yes |
| C20 | **VaR 95 and 99** computed and never gated; ES 97.5 gated (R5 §5.3 #14) | the paper: report VaR, gate ES | tail risk | yes | real | yes (ES) | no | no | slightly | yes |

### D. Complexity that fixes produced (R14)

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C21 | **"Unknown order-scoped IBKR code → halt the account"** | the operator (AE-28, "Unknown → serious → halt") after the 3 Sep staging incident | an unknown broker error treated as harmless | yes | real | partly: reconciliation catches a wrong book | **yes**: it stops all trading | **yes**: it caused 7 of 19 kill-switch trips, 4 from the app's own missing time-in-force and 3 from benign cancels; one fed CE-017 (R14) | yes | yes |
| C22 | **Booking at transmission, and what grew around it**: reversal on rejection, three price-correction paths, a repair script. It caused 3 of 6 reconciliation trips (R14 §14.3) | the first build; kept by the operator on 3 Sep (AE-28, "Drop Task 3") | — (the design choice itself) | — | — | — | **yes** | **yes**: CE-005, the A2M route into the aggregate-cap trap (R16) | **yes**: the book, the ledger and the broker disagree until the next poll | ⚑ no: "what the app holds" has three answers at any moment |
| C23 | **Broker-id identity machinery**: app id, permId, aliases, a resolved-id event (R14 incident 10) | own fills absorbed as foreign, 26 Aug | an order known by two ids | yes | real | no | no | ⚑ investigator 3 found untested paths | **yes**: the journal re-keys to the broker's id (CE-029) | yes |
| C24 | **Resting-order scan**: 10 detections, 1 real; each false positive quarantines the symbol (R10 §10.2) | the 24 Aug orphans (AE-26) | orphaned legs | yes | real | no | **yes**: the quarantine refuses entries | **yes**: wrong 9 times in 10 | slightly | yes |
| C25 | **In-flight tolerance and the position-anomaly store** (R14 incident 3) | a partial fill read as a divergence (31 Aug) | false reconciliation trips | yes | real | no | no | no | slightly | yes |
| C26 | **The missed-exit replay** sizes a closed lot from one partial execution (R13 §13.2; tracker section 2) | startup catch-up | exits missed while the app was closed | yes | real | no | no | **yes**: TNE lost 2,991 shares from the ledger | yes | yes |
| C27 | **Repair scripts**: seven repairs rewrote the ledger; only one left a mark in the record (R13) | incidents, by runbook | wrong records | partly | real | no | no | yes: a record can change without a trace in it | **yes** | yes |

### E. Two ways of doing one thing

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C28 | **Two leg-cancel implementations**, the exit's and the manual close's, with different tests for "gone" and **opposite order against the kill-switch check** (R5 §5.3 #5; R10 §10.2; CE-017) | the 2 Sep manual close (operator); the 7 Sep exit fix (on a wrong claim, AE-29) | protective legs left on a flat symbol | yes | real | each is the other | **yes** | **yes: CE-017, the live defect** | yes | yes |
| C29 | **Two decision records**: `decision_journal.csv` (per symbol, on change only, re-keyed to the broker's id) and `risk_decisions.csv` (every evaluation, exits without sizing inputs). A report heading counts every non-auto-signed journal row as "blocked" (R7 #59) | first build | a record of each decision | yes | real | each is the other | no | no | **yes**: they count different things (CE-029) | ⚑ no |
| C30 | **The governor values positions on two bases**: the broker mark for aggregate risk and the gap budget, average cost for name, sector and cluster (R5 §5.3 #13) | M90 moved one to the mark (14 Aug) | winners understated | yes | real | — | yes, at the margin | ⚑ | yes | no |
| C31 | **The regime's two outputs**: the label sets size; the probability mass sets eligibility. The label is sticky only for about 3 minutes and resets at every launch (R12). The engine's own log line has to explain the difference on every transition (`engine.py:552-556`) | M27b (31 Jul, operator "Both") | a 0.02 label margin deciding a session | yes | real | — | **yes** | no | **yes** | ⚑ no |
| C32 | **Staleness in two places, none in the kill switch**: the strategy engine drops a symbol 2,100 s after its last bar; the gate needs a print this session. The kill switch's staleness trip was removed on 31 Jul, and its docstring still claims one (CE-022) | incidents | stale prices trading | yes | real | each does a different job | yes | no | yes (the docstring) | yes |

### F. Prose and records

| # | Item | Why | Problem | Still? | Real? | Elsewhere? | Trading? | Fail? | Harder? | 1 sentence? |
|---|---|---|---|---|---|---|---|---|---|---|
| C33 | **Prose is 37% of the code**, and some of it is false: `_column`'s "a zero contributes no bonus" (CE-032); the kill switch's staleness docstring (CE-022); `service.py:130-131` (the report has no position sizes); the system prompt's "a human decides" (R11 §11.4); `config.py`'s "nothing reads" `macro_growth_series` (investigator 4) | each change explained where it was made (Claude's practice) | why the code is as it is | — | — | HANDOFF, ROADMAP, commits, which say much the same | no | no | **yes**: a reader meets unverified claims beside the code, and some are wrong (CE-018) | yes |
| C34 | **`version.py`: 2,035 comment lines of milestone history** above one constant | the build stamp (M27b) | which build is running | yes | real | yes: git and the build stamp | no | no | yes | yes |
| C35 | **27 backups in the data folder**, none indexed (R13) | each repair or migration | keeping the record before a change | yes | real | no | no | no | slightly | yes |

**Outside the system, noted:** `docs/HANDOFF.md` is 6,950 lines (388 KB). Its own header says "Keep this file short. It went stale by
growing." It is the development record, not the system, and the operator's
Q3 answer names "misinformation" as one way the vision was lost. R23 is the
place for it.

## 15.3 The flags (answers the evidence leaves unclear)

| # | Unclear |
|---|---|
| C6 | whether the gate's fixed session times are still wrong, which `ib_hours.py` was built to replace |
| C9 | whether exiting without `Orchestrator.stop_all` leaves anything half-written |
| C11 | why `DGS3MO` and `DGS10` are fetched at all |
| C16 | whether the cluster cap can bind at 10 positions (never formed on 68 buys) |
| C18 | how the cash cap and the engine's sizing are meant to relate: which is meant to decide an entry's size |
| C22 | the book at a given moment: the app's quantity, the broker's, and the ledger's can differ |
| C23 | the identity machinery's untested paths |
| C29 | which record is "the" decision record |
| C30 | whether the two valuation bases are intended |
| C31 | whether a label that resets at launch and moves within minutes meets the intent of "sticky" |

## 15.4 What the inventory shows

1. **Little is dead weight.** 3,827 lines (7% of the physical lines) never
   run in the app, and most of that is the research harness (1,823) and
   pre-flight (850), which scripts use. The code nothing uses at all is
   small: the storage layer, the unused feature computation, the validation
   module the paper asks for, and two unwired IBKR parsers.
2. **The expensive complexity is live and was produced by fixes** (group D):
   the halt-on-unknown rule, booking at transmission and its repairs, and the
   two leg-cancel paths, one of which is CE-017.
3. **Several careful mechanisms rarely decide anything.** The cash cap sets
   most entry sizes. The four rails in C14–C17 have never acted. The regime's
   first label is an artefact of the launch. None of that is visible from the
   code alone (C18, C14–C17, C31).
4. **The code carries its own history as prose, and the prose is not always
   true.** 37% of the lines are comments and docstrings. The audit has found
   five of them false so far (C33).
