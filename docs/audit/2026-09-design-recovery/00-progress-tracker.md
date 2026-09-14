# QAT Design Recovery & Design Intent Audit: progress tracker

**This is the one place the audit's progress is tracked.** It follows the
numbering of the operator's own brief (the 12 September 2026 message, transcript
`ede4fc1d` line 739, 07:49Z), section by section, with what is done, where the
evidence is, and what is still to do.

Adopted 14 September 2026 at the operator's direction: "Use the brief's
numbering … This is how things get lost or confused on what's being done and
what's to do." The plan's own "Stage 0–10" numbers are retired (CE-030). The
crosswalk at the end is only for reading older documents.

## How to read this

| Mark | Means |
|---|---|
| **§N** | a section of the brief's instructions, §1 to §22 |
| **RN** | a section of the final report, in the order brief §19 lists them, R1 to R24. Report files are named by their R number: `09-….md` is R9 |
| **Phase N** | brief §20's remediation phases. The audit **recommends** them; it does not carry them out |
| ✅ | done, with evidence cited |
| 🟡 | drafted; waits for the operator's review at Checkpoint B |
| 🔶 | in progress |
| ⬜ | not started |
| ⛔ | blocked |

**Rules for keeping this true**
1. Update it at the end of every session, and whenever a status changes. Date
   each change in the change log at the bottom.
2. Status is kept **here only**. HANDOFF and the audit plan point here and do
   not repeat it.
3. A ✅ cites its evidence. With no evidence, it is not ticked.
4. A status goes backwards if the work turns out to be wrong. The change log
   says why.

---

## 1. At a glance (14 September 2026, 18:00 AEST)

| § | The brief asks for | Report | Status | Next action |
|---|---|---|---|---|
| opening | assess the approach, find synergies, propose a plan | the plan | ✅ 12 Sep | — |
| §1 | the non-negotiable rules | — | ✅ in force | — |
| §2 | the baseline | R3 | ✅ 12 Sep | re-measure only if `src/` or config changes |
| §3 | the original design | R4 | ✅ 12 Sep; baseline set by the operator 14 Sep | — |
| §4 | the current system | R5 | ✅ 14 Sep | 6 items still NOT DETERMINED (R5 §5.4) |
| §5 | the design-drift map | R6, R7 | 🟡 14 Sep | Checkpoint B |
| §6 | "is QAT still trading my strategy?" | R8 | 🟡 14 Sep. **Answer: no** | Checkpoint B |
| §7 | the risk-control stack | R9 | 🟡 14 Sep | Checkpoint B |
| §8 | the execution / OMS / broker boundary | R10 | 🟡 14 Sep | Checkpoint B |
| **§9** | **the AI/LLM boundary** | **R11** | **⬜ next** (facts gathered in R5) | — |
| **§10** | **the regime logic** | **R12** | **⬜ next** (facts gathered in R5) | — |
| §11 | data and evidence integrity | R13 | ⬜ (IBKR statements archived) | — |
| §12 | accidental complexity | R15 | ⬜ | — |
| §13 | control interactions and traps | R16 | 🟡 14 Sep | Checkpoint B |
| §14 | past failures and the controls they produced | R14 | 🟡 14 Sep | Checkpoint B |
| §15 | three architecture diagrams | R17, R18, R19 | ⬜ | — |
| §16 | simplification candidates | R20 | ⬜ | — |
| §17 | coherence questions A–J | R22 and R1 | ⬜ | — |
| §18 | Green / Amber / Red | R24 | ⬜ | — |
| §19 | the 24-section report | R1–R24 | 🔶 R3–R10, R14 and R16 drafted | see section 4 of this tracker |
| §20 | remediation sequence, recommended only | R23 | ⬜ | — |
| §21, §22 | don't aim for a good result; keep asking the key question | — | in force | — |

**Order of work from here:** ~~§7 and §13~~, ~~§8 and §14~~ (drafted 14 Sep) →
**§9 and §10** → §11 → §12 and §16 → §15, §17, §18, §20 and R1, R2, R21–R24 →
**Checkpoint B**.

---

## 2. Open items that need the operator

| Raised | Item | State |
|---|---|---|
| 14 Sep ~13:25 | ⚠️ **JHX.AX closed on 11 Sep at 39.01, below its resting stop (recorded 39.39), and the stop did not fill.** 1,097 shares are still held (IBKR statement, 24 Aug–11 Sep). The app counted JHX at its whole value from 12:04 on 10 Sep, and for the whole session on 11 Sep. **Why the stop did not trigger is NOT DETERMINED.** A broker read would settle it: JHX's stop in the TWS Orders panel (status, trigger price, trigger method). Found during §7; belongs to §8 | **HELD until after the audit** (operator, 14 Sep ~15:00: "hold the JHX item till after the audit is complete"). No broker read, nothing changed. Taken up again when the audit completes |
| 14 Sep | ⚠️ **CE-017**: an exit releases a position's broker stop before the kill-switch check. The operator chose "decide later, continue audit" | open; not fixed |
| 14 Sep ~10:19 | **Trading suspended for the audit.** The app is not launched. The config still says `auto`, so a launch would trade | holding |
| — | **Checkpoint B**: the operator reviews the full draft report | when R1–R24 are drafted |

---

## 3. Section by section

### Opening request (the brief's first line)
"Firstly assess, then compare it against any outstanding development items for
synergies, then propose a plan."

| Item | Status | Where |
|---|---|---|
| Assess the approach | ✅ 12 Sep | plan §1 (adopted, with eight amendments A1–A8) |
| Synergies with the outstanding items | ✅ 12 Sep | plan §5 |
| Propose a plan | ✅ 12 Sep | plan §6 |

### §1 Non-negotiable rules
| Item | Status | Where |
|---|---|---|
| No features, refactors, logic, parameter, threshold or execution changes; no fixes without authorisation | ✅ in force since 12 Sep | HANDOFF standing instruction 1 |
| Report a needed code change as a required investigation, never make it | ✅ in force | e.g. CE-017 reported, not fixed |
| The six-way distinction (original / enhancement / defensive fix / agent fix / accidental / unknown) | ✅ used | R7 classes A–G, plus the Authority column (operator addition, 12 Sep) |

### §2 Establish the baseline → R3
All seventeen items ✅, measured 12 Sep 20:10–20:30, in
`03-current-baseline.md`: commit, branch, version, module count (184),
source lines (45,143), tests (3,703 collected; 3,677 passed, 26 skipped), lint,
type and security status, and the deployment, trading, autonomous-strategy,
broker, market-data, risk, regime, execution and AI configuration.
* Not measured, and marked as such: the rollback directories (outside the
  search boundary) and the broker's positions (Gateway was down).
* `src/` has not changed since (`handoff_state.py`, 14 Sep 10:35).

### §3 Recover the original design → R4
| The brief's question | Status | Where in R4 |
|---|---|---|
| What was QAT meant to do? | ✅ | §4.1; governed by the operator's statement, §4.00 |
| What was it NOT meant to do? | ✅ | §4.2 |
| The original trading strategy | ✅ | §4.3, §4.15; **the operator named `Swing Trader methodology.md` as the specification**, R8 §8.5 Q2 |
| The role of the AI/LLM | ✅ | §4.4, §4.001; **operator's answer**, R8 §8.5 Q1 |
| The role of deterministic logic | ✅ | §4.5 |
| The role of the risk engine | ✅ | §4.6 |
| The role of the OMS | ✅ | §4.7 |
| The role of the broker interface | ✅ | §4.8 |
| Who may decide; who may transmit | ✅ | §4.9 |
| The original safety principles | ✅ | §4.10 |
| The path from data to order | ✅ | §4.11 |
| Human approval; what is autonomous; what stays advisory | ✅ | §4.12 |
| Mark unsupported answers UNKNOWN | ✅ | §4.13, re-examined against the transcripts in R6 §6.0 |

Sources read: the four claude.ai chats, the paper, MkI, the methodology file,
the reference app's settings block, the first commit, and the Claude Code
transcripts from 24 July (CE-020). **Checkpoint A, 14 Sep:** the operator's
statement of intent, R4 §4.00–§4.001.

### §4 Reconstruct the current system → R5
| Item | Status | Where |
|---|---|---|
| The actual flow, amended where the code differs | ✅ | R5 §5.1 |
| For every stage: modules, inputs, outputs, authority, state, persistence, failure, refusal, interactions, deterministic or AI, can it reach the broker | ✅ | the four investigator reports, `stage3/`; R5 §5.2 summarises five of the eleven columns |
| Cross-verified against the code and logs | ✅ | R5 §5.0 |
| NOT DETERMINED | open | six items, R5 §5.4 (need runtime observation) |

### §5 Design-drift map → R6, R7
| Item | Status | Where |
|---|---|---|
| The table, with the brief's columns | 🟡 | R7, 59 items. "Original intent → current" holds both the Original Intent and Change columns. Evidence is the commit plus the AE entry |
| Classes A–G, not forced | 🟡 | R7 |
| When and why each arrived | 🟡 | R7 "Introduced", "Why" |
| Who decided (operator addition) | 🟡 | R7 Authority; the register `stage4/authority-evidence.md`, AE-01 to AE-35 |
| Original vs current, question by question | 🟡 | R6 |

### §6 "Is QAT still trading the strategy I originally designed?" → R8
| Item | Status | Where |
|---|---|---|
| Reconstruct the original swing precisely | ✅ | R4 §4.15; R8 §8.0 (P and S). S is the specification (operator, 14 Sep) |
| Compare all 23 elements the brief lists | 🟡 | R8 §8.1 (all 23, plus volume and trade management) |
| Code each difference 1–6 | 🟡 | R8 §8.1 |
| The answer | 🟡 | R8 §8.3, §8.5: **no.** The methodology was requested for the first build and never implemented (CE-026) |

### §7 Audit the risk-control stack → R9 🟡 (drafted 14 Sep)

**Report:** `09-risk-control-assessment.md`. **Evidence tools (read-only):**
`s07-s13-risk-and-interactions/tools/`: `rails_by_day.py`,
`risk_per_trade.py`, `aggregate_series.py`, `gate_and_halts.py`.

**Each control the brief names.** Every one is mapped in code (Stage 3 reports)
and its effect measured, or marked NOT DETERMINED, in R9 §9.2.

| # | Control | Measured effect (records to 12 Sep) | Status |
|---|---|---|---|
| 1 | Per-trade risk (1%) | 20 entries took **0.13%–0.70%** of equity, median 0.45%. None took the full 1% | 🟡 |
| 2 | Stop distance | recorded per entry; swing's stop is 2.5 × ATR | 🟡 |
| 3 | Position sizing | `min(Kelly, 1% ÷ stop)` rebuilt for every entry | 🟡 |
| 4 | Half-Kelly (placeholders 0.55 / 1.5) | **bound 13 of 20**; on the record so far, measured Kelly would be zero (R16 §16.2) | 🟡 |
| 5 | Volatility targeting | none separate: a minimum, not a blend | 🟡 |
| 6 | Aggregate risk-at-stop (5%) | 453 rows, 6 symbols, 2 days; also all 4 governor trims | 🟡 |
| 7 | Position count (10) | **4,265 rows, 27 symbols, 41 symbol-days, 10 days** | 🟡 |
| 8 | Single-name (15%) | never acted; cannot bind while placeholder Kelly (12.5%) or the cash cap (10%) holds | 🟡 |
| 9 | Sector (30%) | never acted; peak 6.6% before an approved buy | 🟡 |
| 10 | Correlated cluster | never acted; **empty on all 68 approved buys** (Claude's 7 Aug claim now measured) | 🟡 |
| 11 | Gap budget | never acted | 🟡 |
| 12 | Cash cap (10% of spendable cash) | **cut 18 of 20** after approval, median to 77% | 🟡 |
| 13 | Cash reserve / no leverage | never acted | 🟡 |
| 14 | Cost-to-risk (10%) | 1 refusal (3 Sep) | 🟡 |
| 15 | Earnings sizing | applied on 745 evaluations, **none approved**; 12 of 19 approved entries had no earnings date (the rail abstains) | 🟡 |
| 16 | Daily loss limit (3%; gate −2% / −4%) | **never acted**: 0 trips, 0 gate blocks | 🟡 |
| 17 | Drawdown limit (20%) | never acted | 🟡 |
| 18 | Kill switch | **19 trips** (7 unrecognised IBKR errors, 6 reconciliation, 4 reconnect, 2 manual); refused 158 exit decisions | 🟡 |
| 19 | Session gates | **delayed 9 entries, refused none** | 🟡 |
| 20 | Staleness | **NOT DETERMINED** from the records (exclusions are not logged as events) | 🟡 |
| 21 | Promotion evidence | off on paper; 8 of 30 | 🟡 |
| 22 | Pending-order exposure | transmitted orders counted since `72191a9` (27 Aug), after the 26 Aug eleven-position failure; the de-lever sweep and the checker exclude pending | 🟡 |
| — | Silent drops before the risk engine | not recorded; the weekly budget never refused; the minimum hold held IAG's exit back on 7 days | 🟡 |

**The brief's seven questions:** all answered in R9 §9.3 🟡.

**Found in passing:** the JHX stop that did not fill (section 2 above; held
until after the audit).

### §8 Audit the execution / OMS / broker boundary → R10 🟡 (drafted 14 Sep)
**Report:** `10-execution-boundary.md`. **Tools:**
`s08-s14-execution-and-incidents/tools/execution_evidence.py`,
`incident_episodes.py`.

**All 14 of the brief's questions are answered in R10 §10.2, and the
proven-live vs code-only matrix is R10 §10.3** 🟡. Headlines:
* **The deployed M175, and M174, have never transmitted an order.**
* **Every order in the ASX era was signed by the autonomy gate.** The human
  paths (Blotter, manual close) have never run live.
* **The market-exit path has run for 3 symbols, and each run tripped the
  kill switch.** SEK's exit filled while the app held it as rejected.
* **Booking at transmission** caused 3 of the 6 reconciliation trips.
* The 3 Sep fixes were not in the build that traded on 4 Sep.

The table below is the question list as it stood before R10; kept for the
record.

| The brief's question | Facts already in hand |
|---|---|
| Where can duplicate transmission occur? | CE-003; the guard is R7 item 41 |
| Where is an order recorded as a position before the broker confirms? | yes, at sign-off (R5 §5.3 #2, `oms.py:1134-1137`). On 4 Sep a cancelled A2M sell was booked, and the app dropped A2M's stop from its own records |
| Where can staged or untransmitted orders occur? | CE-005 (3 Sep) |
| Where is the fill price obtained? | R5 §5.3 #2; the M175 fill-basis repair |
| Can app prices differ from broker prices? | yes; the ENTRY PRICE CORRECTED lines; M65 and M175 |
| How are orphans detected, and handled? | the resting-order scan detects; it never cancels (R7 item 47) |
| How are protective stops set, and re-armed? | brackets (R7 item 43); re-arm (item 44) |
| How does the kill switch interact with broker protection? | CE-017 (R7 item 45) |
| Does every path get the same controls? Do exits and entries follow equivalent safety paths? | investigator 2's ordered list 2: exits skip most rails |
| What is proven live, and what only in code? | ⬜ a matrix cited to log lines |
| **New, 14 Sep:** a resting stop that did not fill below its trigger (JHX) | section 2 above |

### §9 Audit the AI/LLM boundary → R11 ⬜
The twelve questions (inputs, outputs, structure, influence on strategy,
sizing, approval and execution, tools, broker access, persistent state, when
the LLM is unavailable, the trading path without it) have facts in R5 §5.3
#21–22 and investigator 4 §3. The principle to test is the brief's; the
operator's Q1 answer (R8 §8.5) states the intent it is measured against.

### §10 Audit the regime logic → R12 ⬜
The pipeline items (inputs to strategy eligibility) have facts in investigator
1 section D and R3 §3.5. The six determinations have partial evidence:
* which inputs drive the label: the late-August ablation (86% VIX dominance,
  HANDOFF item 66);
* whether AU inputs are current: M170 (AU FRED series 99 days stale);
* whether regime is recorded with trades: no, 12 of 12 blank (R5 §5.3 #16).

### §11 Audit data and evidence integrity → R13 ⬜
The fourteen checks and six impact types. Evidence to inventory:
* the `.bak` files in the data folder (27, counted 14 Sep);
* `scripts/repair_*`;
* the IBKR statements (archived 12 Sep) against the ledger;
* the TNE remnant and the LOV repair;
* the 24 August impossible trades;
* the 12 blank regime fields.

### §12 Identify accidental complexity → R15 ⬜
The nine questions per item. The candidates start from R7's D and F items.

### §13 Identify control interactions → R16 🟡 (drafted 14 Sep)
**Report:** `16-control-interactions.md` (with the diagram, §16.4).
**Tool added:** `evidence_chain.py`.

| Item | Status | Evidence |
|---|---|---|
| **The aggregate-cap trap.** Every large over-cap reading since 25 Aug (4, 9 and 10–12 Sep) came from **one position counted at its whole value**: the governor does that when it knows no stop, or when the price is at or below the stop (`governor.py:266-267`). Three routes: **A2M** 4 Sep (a sell the broker cancelled was booked, and the app dropped the stop from its own records; derived from code and log order); **IAG** 9 Sep (CE-017); **JHX** 10–12 Sep (price at or below its resting stop) | ✅ traced | `aggregate_series.py`; the 12 Sep reading of **7.48% reproduced exactly** from the IBKR 11 Sep closes: eight positions 31,246 + JHX 42,794 = 74,040 ÷ 989,604 |
| **All 449 refusals on 11 Sep trace to JHX.** Without it the book was at 3.16% against 5% | ✅ | same |
| The plan's hypothesis that winners consume the budget | ✅ **refuted** for 10–12 Sep | the book was below cost at the 11 Sep close (value 493,473.05 against cost 498,215.56, IBKR statement) |
| The brief's own example chain | 🟡 traced (R16 §16.2) | 8 closed in 14 trading days (0.57 a day). **On the record so far, measured half-Kelly would be zero at the 20-trade switch**, which would stop the entries that produce evidence (a lock; derived, conditional). Promotion is enforced on live only |
| Kill switch ↔ protective re-arm (CE-017) | 🟡 | R16 §16.3 a |
| Other chains | 🟡 | R16 §16.3 b–h: booking a cancelled sale drops the stop record; the 26 Aug race (fixed); cash cap → the position count binds first; IAG's exit signal on its entry day, held back by the minimum hold; the session gate and the skipped drift check; pending orders suppressing signals (code only); the records cannot show two rails binding |
| The diagram | 🟡 | R16 §16.4 (mermaid) |

### §14 Distinguish safety from complexity → R14 🟡 (drafted 14 Sep)
**Report:** `14-failure-to-control-mapping.md`. **All eight incident types the
brief lists are assessed** (necessary / proportionate / secondary complexity),
plus two more the records show (the 26 Aug race, and own fills absorbed as
foreign). Headlines:
* Most controls followed real failures and were necessary.
* **Booking at transmission** is the common root of many incidents.
* **Fixes produced the next incidents:**
  - "unknown code → halt" caused 7 of the 19 trips (4 from the app's own
    missing TIF, 3 from benign cancels);
  - the cancel-first exit became CE-017;
  - the orphan scan is right 1 time in 10.

### §15 Architecture diagrams → R17, R18, R19 ⬜
* R17, QAT as it is: start from R5 §5.1.
* R18, QAT as originally intended: only components the evidence supports.
* R19, the drift between them.

### §16 Simplification candidates → R20 ⬜
The brief's table, with one of six recommendations per candidate. Nothing is
changed.

### §17 Is QAT conceptually coherent? → R22 (and R1) ⬜
Partial answers exist but are not yet written as answers:
* A (original strategy recognisable): R8 §8.3, recognisable in outline, not
  the operator's method;
* H (what is missing): the AI's part in the recommendation, the allocator,
  the methodology (R6 §6.2).

### §18 Final classification → R24 ⬜

### §19 The report → see section 4 below

### §20 Remediation sequence → R23 ⬜
Recommend only (Phases 1–7 in section 5 below).

### §21 Don't aim for a "good" result; §22 the most important question
In force throughout. R1 is to answer §22's question directly.

---

## 4. The report, R1 to R24 (brief §19)

| R | Section | File | From brief § | Status |
|---|---|---|---|---|
| R1 | Executive Summary | — | all | ⬜ last |
| R2 | Audit Scope | — | opening, §1 | ⬜ (scope is in the plan §2–§3, §7) |
| R3 | Current Baseline | `03-current-baseline.md` | §2 | ✅ 12 Sep |
| R4 | Original Design Intent | `04-original-design-intent.md` | §3 | ✅ 12 Sep; Checkpoint A 14 Sep |
| R5 | Current Architecture | `05-current-architecture.md`, `stage3/` | §4 | ✅ 14 Sep |
| R6 | Original vs Current Comparison | `06-original-vs-current.md` | §3–§5 | 🟡 14 Sep |
| R7 | Design Drift Map | `07-design-drift-map.md`, `stage4/` | §5 | 🟡 14 Sep |
| R8 | Strategy Integrity Assessment | `08-strategy-integrity.md` | §6 | 🟡 14 Sep |
| R9 | Risk-Control Assessment | `09-risk-control-assessment.md` | §7 | 🟡 14 Sep |
| R10 | OMS / Execution / Broker | `10-execution-boundary.md` | §8 | 🟡 14 Sep |
| R11 | AI / LLM Boundary | — | §9 | ⬜ |
| R12 | Regime | — | §10 | ⬜ |
| R13 | Data & Evidence Integrity | — | §11 | ⬜ |
| R14 | Historical Failure → Control Mapping | `14-failure-to-control-mapping.md` | §14 | 🟡 14 Sep |
| R15 | Accidental Complexity | — | §12 | ⬜ |
| R16 | Control Interaction | `16-control-interactions.md` | §13 | 🟡 14 Sep |
| R17 | Current-State Architecture | — | §15 | ⬜ |
| R18 | Original-Intent Architecture | — | §15 | ⬜ |
| R19 | Design-Drift Architecture | — | §15 | ⬜ |
| R20 | Simplification Candidates | — | §16 | ⬜ |
| R21 | Outstanding Unknowns | — | §3, §21 | ⬜ (collect from R4 §4.13, R5 §5.4) |
| R22 | Recommended Freeze State | — | §17 J | ⬜ |
| R23 | Recommended Remediation Sequence | — | §20 | ⬜ |
| R24 | Final Design-Integrity Classification | — | §18 | ⬜ |

---

## 5. Remediation phases (brief §20): recommended, not done

| Phase | Name | Where it stands |
|---|---|---|
| 1 | Design Recovery | this audit: §2–§6 (done or drafted) |
| 2 | Evidence Validation | this audit: §4 done; §7–§11 and §13–§14 in progress or to do |
| 3 | Drift Classification | this audit: §5 drafted; §12 and §16 to do |
| 4 | Safety Review | **after** the operator approves the report |
| 5 | Controlled Simplification | only after explicit approval |
| 6 | Freeze | after 5 |
| 7 | Evidence Accumulation | after 6: controlled paper or shadow trading |

---

## 6. Operator decisions that govern the audit

| Date | Decision | Where recorded |
|---|---|---|
| 12 Sep | Freeze development; run the audit per the brief | the brief; HANDOFF instruction 1 |
| 12 Sep | Add an Authority column; keep a Claude error log | plan A2; `docs/CLAUDE_ERROR_LOG.md` |
| 12 Sep | The origin is four claude.ai chats (export provided) | plan Stage 0 item 1 |
| 12 Sep | The separate market-opinion tool is out of scope | plan A8 |
| 12 Sep | Preserve the evidence; retention raised to 365 days | plan Stage 0 item 4 |
| 12 Sep | Fresh-context investigators for fact-finding only | plan Stage 0 item 5 |
| 12 Sep | Search boundary, and the locations approved | HANDOFF instruction 3 |
| 14 Sep | **Checkpoint A**: the statement of original intent, and what AI-autonomous means | R4 §4.00, §4.001 |
| 14 Sep | CE-017: "decide later, continue audit" | error log CE-017 |
| 14 Sep ~10:19 | **Trading suspended for the audit** (supersedes 12 Sep "keep auto running") | HANDOFF instruction 2; register AE-35 |
| 14 Sep | Answers to Q1–Q3 | R8 §8.5; register AE-34 |
| 14 Sep ~14:40 | **Track by the brief's numbering, in this document** | this file; CE-030 |
| 14 Sep ~15:00 | **JHX's unfilled stop is held until after the audit**; continue the audit | section 2 of this file |

## 7. Beyond the brief (operator additions)

| Addition | Status |
|---|---|
| Authority column on the drift map | ✅ in R7 |
| Claude error log | 🔶 CE-001 to CE-031 recorded. The systematic back-fill (fix commits, ROADMAP and HANDOFF incidents, transcripts from 24 Jul) is still to do |
| Checkpoint A (operator reviews R4 and R5) | ✅ 14 Sep |
| Checkpoint B (operator reviews the full draft) | ⬜ |
| Evidence snapshots at each session end | ✅ 12 Sep and 14 Sep so far |

## 8. Retired numbering: the crosswalk

For reading documents written before 14 Sep 14:40. Do not use these numbers
for new work.

| Old "Stage" | Brief § | Report |
|---|---|---|
| Stage 0 | operator decisions | — |
| Stage 1 | §2 | R3 |
| Stage 2 | §3 | R4 |
| Stage 3 | §4 | R5 (folder `stage3/`) |
| Checkpoint A | — | R4 §4.00 |
| Stage 4 | §5, §6 | R6, R7, R8 (folder `stage4/`) |
| Stage 4a | error-log back-fill | — |
| Stage 5 | §7, §13 | R9, R16 (folder `s07-s13-risk-and-interactions/`) |
| Stage 6 | §8, §14 | R10, R14 (folder `s08-s14-execution-and-incidents/`) |
| Stage 7 | §9, §10 | R11, R12 |
| Stage 8 | §11 | R13 |
| Stage 9 | §12, §16 | R15, R20 |
| Stage 10 | §15, §17–§20 | R1, R2, R17–R19, R21–R24 |

## 9. Change log (this tracker)

| When (AEST) | Change |
|---|---|
| 14 Sep 2026 14:45 | Created at the operator's direction. Statuses taken from the report files, the error log and this session's §7/§13 measurements. |
| 14 Sep 2026 ~15:00 | JHX item marked HELD until after the audit (operator). |
| 14 Sep 2026 ~16:45 | §7 → 🟡 (R9 drafted: every control measured or marked NOT DETERMINED; the seven questions answered). §13 → 🟡 (R16 drafted: the full-value trap, the example chain traced to a possible Kelly lock, eight other interactions, the diagram). Next: §8 and §14. Error log to CE-031. |
| 14 Sep 2026 ~18:00 | §8 → 🟡 (R10: the 14 questions, the proven-live matrix). §14 → 🟡 (R14: ten incidents mapped to their controls). Next: §9 and §10. CE-031 has two later notes (R10, R14 catches). |
