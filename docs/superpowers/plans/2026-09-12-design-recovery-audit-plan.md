# Design Recovery & Design Intent Audit: assessment of the approach, and plan

**Status:** proposal for review, 12 September 2026. Nothing in the system has
changed. The audit has not started. **Revised the same day** with the
operator's answers (origin in four Claude chats; the authority column adopted,
plus a Claude error log; the operator's separate market-opinion tool is out of
scope) and a correction to what the
session transcripts cover (CE-013 in `docs/CLAUDE_ERROR_LOG.md`).
**Baseline at writing:** `master` at `ae2c91a` (2 commits unpushed). Deployed
M175 (`5e322ca`). App running since 10:55 (weekend, stood down).

## ▶ PROGRESS (updated 14 September 2026, 10:00). Read this first

> ⛔ **SUPERSEDED 14 September 2026, 14:45 (operator's direction).** Progress
> is tracked **only** in `docs/audit/2026-09-design-recovery/00-progress-tracker.md`,
> by the brief's own section numbers (§1–§22) and report sections (R1–R24).
> The "Stage 0–10" numbering below is **retired**, because it reused the
> brief's numbers with different meanings (CE-030); the tracker has the
> crosswalk. This table is kept as it stood at 10:00 and is no longer updated.

| Stage | Status | Output |
|---|---|---|
| 0: decisions | ✅ complete (12 Sep) | Stage 0 list below; permissions in item 9 |
| 1: baseline | ✅ complete (12 Sep) | `docs/audit/2026-09-design-recovery/03-current-baseline.md` |
| 2: original intent | ✅ complete (12 Sep) | `.../04-original-design-intent.md` |
| 3: current reconstruction | ✅ complete (12–14 Sep) | `.../05-current-architecture.md` and `.../stage3/` (4 verbatim investigator reports) |
| **⛔ Checkpoint A** | ✅ **decided 14 Sep** | report §4.00 and §4.001: the operator's baseline (below) |
| **4: drift map and strategy integrity** | ✅ **draft complete 14 Sep**; the operator **answered Q1–Q3 the same morning** (report §8.5; register AE-34) and §7–§8 are re-classified by the answers | `.../06-original-vs-current.md`, `.../07-design-drift-map.md` (59 items), `.../08-strategy-integrity.md`, `.../stage4/authority-evidence.md` (AE-01 to AE-33) |
| 4a: error-log back-fill | **first tranche 14 Sep**: CE-020 to CE-028, a CE-017 later note, items under "To establish". The systematic pass (fix commits, ROADMAP and HANDOFF incidents) is still to do | `docs/CLAUDE_ERROR_LOG.md` |
| 5: risk stack and control interactions | not started | report §9, §16 |
| 6: execution boundary and incident → control mapping | not started | report §10, §14 |
| 7: AI boundary and regime | not started (Stage 3 has the facts) | report §11–12 |
| 8: evidence integrity | not started (IBKR statements are in the archive) | report §13 |
| 9: complexity and simplification candidates | not started | report §15, §20 |
| 10: synthesis | not started | full 24-section report |
| ⛔ Checkpoint B | – | operator reviews the draft |

**The governing baseline (Checkpoint A, operator, 14 Sep):**
* **Purpose:** an app making **recommended trades using AI**, around
  **different trading strategies**.
* **Decisions:** **human, or AI autonomous**. Autonomous means acting on its
  recommendation and completing the trade, **subject to the embedded safety
  rails and the selected strategy**.
* **Philosophy and strategies:** the paper. The paper's human-sign-off rule is
  superseded.

**Headline facts for Stage 4 to classify (report §5, §4.001):**
* Autonomous completion within rails and strategy **exists**.
* **No AI takes part in forming any trade recommendation.**
* **One strategy runs**, where the purpose names several.
* The swing entry is the first commit's agent-written rule, not the
  operator's methodology (§4.15).

**⚠️ OPEN LIVE SAFETY DEFECT, CE-017.** An exit cancels a position's broker
stop before the kill switch is checked, and the switch then blocks the
replacement (IAG.AX was unprotected for about an hour on 9 Sep). Reported 14
Sep. The operator chose "decide later, continue audit". **Not fixed.**

**What Stage 4 found (14 Sep; report §6–8):**
* **The transcripts cover every day from 24 July** (CE-020), so authority is
  now evidenced for the whole history. Of 59 drift items:
  * 26 operator-directed;
  * 22 agent-proposed and operator-approved (most inside whole plans or lists);
  * 10 agent-only;
  * 1 unknown.
* **Autonomy was the operator's from the start.** The build brief the
  operator pasted on 24 July added "a future function to allow automated
  orders tied to tested rules and selectable methodology" to the paper's text
  (AE-01), and on 26 July the operator directed the mode (AE-05).
* **No AI in the decision was Claude's choice, not the operator's** (CE-021).
  The 26 July plan the operator approved gave the AI an entry veto. Claude
  built without it and said so afterwards.
* **QAT's swing is the paper's swing in outline and not the operator's
  method**, and has not been since the first commit (§8.3).
* **CE-017's ordering was approved on a wrong claim of Claude's**
  ("self-healing within a scan cycle"), six days after the same trap was
  closed in the manual path.
* **The operator's answers (14 Sep, §8.5):**
  * Q1: one recommendation, formed by the AI and "informed around strategy
    and rules", with the modes differing only in fulfilment;
  * Q2: the methodology is "the spec for Swing Trading", with a test
    condition of 10 working days and 60 once the machinery is proven;
  * Q3: the vision was "lost amongst multiple development branches …
    sometimes from misinformation, or not anchoring back to the
    fundamentals".

  So QAT is not trading the operator's swing strategy. It was requested for
  the first build and not implemented (CE-026).

**How Stage 4 was run:**
* Categories A–G, plus the **Authority** column (operator-directed /
  agent-proposed and operator-approved / agent-only / unknown).
* Authority evidence: the chats (C1–C4) up to 26 Jul; ~~commit messages,
  ROADMAP and HANDOFF (as claims) from 25 Jul to 2 Sep; transcripts from
  3 Sep~~ **the operator's own messages in the Claude Code transcripts from
  24 Jul** (corrected 14 Sep, CE-020); commit messages, ROADMAP and HANDOFF
  as claims throughout.
* Stage 4a runs alongside: each D-class item is cross-referenced to the
  errors that produced it.

**Next: Stage 5** (the risk stack and control interactions, report §9 and
§16). Stage 5 does these:
* Measure which rail refused what, by day, from `risk_decisions.csv`.
* Trace the aggregate-cap chain. §8.2 lists the facts: the 11 September
  refusals were 449 decisions on 4 symbols at 7.35–7.62%, and the sizer and
  promotion thresholds are unreachable at current throughput.
* Measure how far the trims take the risk actually taken per trade below
  1% (§8.1, position sizing).

Stage 4a's systematic pass can run alongside it.

---

## 1. Verdict on the approach

**Adopt it, with eight amendments.** It asks the right question at the right
time. Entries are already blocked by the aggregate risk cap, so pausing
development costs almost no evidence. Its distinction between "code exists"
and "behaviour demonstrated" matches what this project has learned the hard
way. The control-trap analysis (its section 13) has a live example to work on
today.

The amendments come from checking whether the audit can actually be done with
the evidence that exists. Section 2 shows what I found. Section 3 lists the
amendments.

---

## 2. What evidence exists (located 12 September, read-only)

> ⚠️ **Provenance of this section.** The `C:\ShareTrader` rows, and every
> quotation from the paper in §2–§4 of this plan (§20.A, §4.10, the section
> list), come from reads made on 12 September **without the operator's
> permission** (CE-016). The operator approved `C:\ShareTrader` later on
> 12 September (Stage 0, item 9) and describes it as the original version of
> this app. Each quotation becomes audit evidence only once Stage 2 has
> re-read it under that approval. Until then it records what was seen and
> when.

**The founding specification is outside the repository.** The code cites
"spec §E", "spec §I" and "paper §4.10" 92 times across 66 files. None of those
documents was ever committed. They sit in `C:\ShareTrader\`:

| Artefact | Date | What it is | Role in the audit |
|---|---|---|---|
| `ShareTrader MkI.txt` | 15 Jul | First concept. Puts a local LLM "AI Trading Analyst" at the top of the decision chain, issuing Buy/Hold/Sell with confidence | Antecedent |
| `Archive\claude_market_dashboard*.py`, `claude_market_dashboard.py` | 13–26 Jul | The ShareTrader reference app QAT was ported from. It traded autonomously (`autonomous_trade_journal.csv`) | Antecedent. Source of several "closes the gap with the reference" changes |
| `Swing Trader methodology.md` | 21 Jul | Swing detail: chart patterns, position sizing, stop placement, R:R targets, **ATR trailing stops, partial take-profit** | Strategy intent |
| `Investment_Strategy_Advisory_Paper.docx` | 24 Jul | **The founding specification.** 21 sections. §4.10 swing, §6 risk, §9 regimes, §11 HMM, §14 AI permissions, §18 risk engine. **§20 is the "Master Prompt for an AI Coding Agent", modules A–O**: "spec §E" is the regime engine, "spec §I" the broker adapter and OMS | **Primary baseline** |
| Repo commit `fa9ba47` | 25 Jul 07:13 | First commit: "M1–M9, in progress". It arrived with the engines already built | The first *implementation*. Not the design |
| **Four Claude chats (claude.ai, not Claude Code)** | before 25 Jul | The operator's first development of the app, before the move to Claude Code (operator, 12 Sep). They likely produced the paper and M1–M9 | **Primary evidence of origin and early authority. Not yet obtained** |
| Claude Code transcripts (`~\.claude\projects\C--Claude-Programming\`) | **one from 4 Aug; 33 from 3 Sep on** | 202 MB. ⚠️ Retention is Claude Code's default 30 days (`cleanupPeriodDays` unset), which **has already deleted 5 Aug – 2 Sep**, and deletes each remaining file 30 days after its last activity. *Corrected: this row first read "34 sessions, 4 Aug – 12 Sep" (CE-013)*. **⚠️ Corrected again 14 Sep (CE-020): both versions dated the files by their modified time. Their contents run continuously from 24 Jul 15:52 AEST, before the first commit. Nothing was deleted** | Evidence of who authorised what, **from 24 July** (corrected 14 Sep; was "from 3 September only") |
| `ROADMAP.md` (4,798 lines), `docs/HANDOFF.md` (~6,500), `docs/superpowers/specs/` (25 specs) | 25 Jul on | Agent-written rationale and incident records | Claims to test, with dates |
| `C:\Share Trader Project\` | 10–11 Sep | The operator's separate, independent market-opinion tool. **No autonomy and no trading capability** (operator, 12 Sep) | **Out of scope. Not QAT evidence** |

**What the founding spec says about authority** (paper §20.A, verbatim in
part): the LLM "proposes and explains, while a human approves every live
order". "Only a human sign-off action may release an order to the OMS."
"**There is no auto-trade toggle.**" "Never implement autonomous live trading."

**What the paper says about swing** (§4.10, summarised): pullbacks to support
in an uptrend or breakouts from consolidation, each with a clear invalidation
level. Size so the distance to the stop equals 0.5–1% of equity. Target
reward-to-risk of at least 2:1. Suited to sideways-to-moderately-trending
markets. The methodology file adds trailing stops and partial take-profit.

---

## 3. Amendments to the approach

**A1. Name the reference baseline.** "The original design" has four
generations: the MkI concept (LLM decides), the reference app (autonomous),
the paper (human approves every order, no auto toggle), and the first commit
(an agent's implementation of the paper). They disagree on the most important
question, which is who has authority to trade.
*Proposal:* treat the **paper, and §20 in particular, as Original Intent**,
with the **four Claude chats as its provenance**. The chats show how the
paper and M1–M9 came to be, and any decision in them that departs from the
paper. Treat MkI, the methodology file and the reference app as antecedents,
to be cited when a later change "closed a gap with the reference". Treat
`fa9ba47` as the first implementation and compare it with the paper too,
because drift may begin at commit one.
**To confirm after the chats are read** (12 Sep: the operator identified the
chats as the origin).

**A2. Add an authority dimension.** Categories A–G have nowhere to put a change
you directed that alters the original intent. Autonomy is the clearest case. B
("does not change intent") would be false and E ("behaviour change") would
hide that you chose it. The ASX move and the 30 July widening of swing's
regimes are the same shape.
*Proposal:* keep A–G, and add an **Authority** column with four values:
operator-directed; agent-proposed, operator-approved; agent-only; unknown.
Each value carries its evidence reference.
**✅ Adopted 12 Sep.** The operator also asked for a separate **Claude error
log**: every error Claude has made, timestamped, with details and how to
avoid it. It is `docs/CLAUDE_ERROR_LOG.md`, seeded with 14 verified entries.
Back-filling the history is Stage 4a below.

**A3. Treat the evidence gaps explicitly.** *(Corrected 12 Sep, CE-013.)*
Three periods have different evidence:
* **Before 25 July:** the four Claude chats. Obtainable if the operator
  exports them.
* **25 July – 2 September:** commit messages, ROADMAP and HANDOFF only. The
  Claude Code transcripts for this period are gone (30-day retention), except
  one session from 4 August. It covers autonomy (26 Jul), the governor,
  protection, costs, the ASX move, and the first live orders.
* **3 September on:** transcripts exist, but each is deleted 30 days after its
  last activity. The 3 September sessions go first, on about 3 October.

> ⚠️ **Corrected 14 Sep (CE-020).** The middle period is not a gap. The
> transcripts cover every day from 24 July 15:52 AEST, including the session
> that built the first commit (`64d334fe`, 24–30 July). Stage 4 takes authority
> from the transcripts for the whole period, and from the chats before 24 July.

*Proposal:* mark authority UNKNOWN for 25 Jul – 2 Sep wherever commit
messages, ROADMAP and HANDOFF don't name who decided. **Preserve the
remaining transcripts before the next Claude Code start-up**, which is when
cleanup runs. That means copying them to an archive folder, raising
`cleanupPeriodDays`, or both. Both need your OK.

**A4. Independence.** The same kind of agent that wrote the code, ROADMAP and
HANDOFF would be auditing them. HANDOFF is agent narrative, and reading it
first would carry its framing into the audit.
*Proposal:* reconstruct the current system (§4 of the brief) **from the code
and the raw logs only**. Use HANDOFF and ROADMAP as dated claims to test, never
as evidence of behaviour. An option, only if you ask for it: have
fresh-context investigators, who have never read HANDOFF, do the §4
reconstruction, then reconcile their results.

**A5. Depth tiers.** 952 commits, 184 modules and 45,000 source lines won't
all get the same scrutiny.
*Proposal:* **full depth** on the live decision path (data → regime → swing →
sizing → risk → gate → OMS → broker → reconciliation → ledger) and on the AI
boundary. **Survey depth** for the 14 undeployed strategies, the UI, the
backtester and research harness, and reporting.

**A6. Define the freeze.** The brief freezes development. It does not say
whether the app keeps operating.
*Recommended:* **operate unchanged.** M175 keeps running each session, in
paper, with no code, configuration or deploy changes. The reasons:
* The nine open positions have time stops and signal exits that only the
  running app executes.
* Running is the only way the aggregate cap unwinds.
* Items 1 and 3 below are observations the audit needs.
* The audit reads live logs.

The alternative, switching to `recommend` so every order needs your
signature, is itself a configuration change, and the paper's original rule
would require it.
**✅ Decided 12 Sep: keep `auto` running unchanged.** Operator's reason: the
automation exists so a human does not slow trade decisions, or corrupt them
through timing, while the system is being tested. *For the drift map:* this is
operator-directed authority for autonomous paper execution, recorded 12
September. It departs from paper §20.A ("there is no auto-trade toggle"). The
authority for the original 26 July introduction stays UNKNOWN (A3).
*Emergency exception:* if the audit finds a live safety defect, I stop, report
it, and change nothing without your authorisation.
⛔ **Superseded 14 Sep, about 10:19 (operator):** "Trading will be suspended
during the course of this audit." The app is not launched. The configuration
is unchanged (`auto`), so a launch would trade. What stops, and what still
rests at the broker, is recorded in HANDOFF standing instruction 2. Register
AE-35.

**A7. Broker-side truth needs you.** Brief §11 compares broker and application
records. The app's logs and a read-only API probe cover recent executions
only. The complete record since 24 August is IBKR's account statements, and
signing in to download them is yours to do.
*Proposal:* you download the Activity statements for 24 Aug – 11 Sep, or
approve a read-only probe and accept a shorter window.
**Clarified 12 Sep.** Claude cannot fetch the statement itself: it needs a
sign-in to IBKR's Client Portal, and Claude does not enter credentials. What
Claude *can* source: (a) the broker's own execution and commission reports as
the app logged them (`execDetails`, `commissionReport`, back to 24 August in
the rotated logs), and (b) a read-only API probe of recent executions and
open orders. Both are the broker's data as seen through QAT's connection. The
statement is the only source independent of QAT, and it is what an auditor
would reconcile against. One download of about five minutes, as CSV.
⚠️ **The rotated logs are also evidence at risk.** `qat.log` sat at 89% of
its 5 MB cap on 12 Sep. Each rotation deletes the oldest file, so the 24–25
August execution lines disappear within a few rotations. Archive them with
the transcripts (A3).

**A8. Scope: the operator's separate market-opinion tool. ✅ Resolved 12 Sep:
out of scope.** `C:\Share Trader Project\` is an independent market-opinion
tool the operator is building separately. **It has no autonomy and no trading
capability** (operator, 12 Sep). It is not part of QAT and is not audited.
*Corrected 12 Sep at the operator's direction.* An earlier version of this
paragraph described that tool from a search Claude ran without permission
(CE-015, CE-016). That description is withdrawn.

---

## 4. Early indications to test, not findings

Seen while assessing. Each needs the audit's evidence before it counts as a
finding.

1. **Autonomous sign-off contradicts the founding spec.** `ab1ba97` (26 July,
   M13) added `execution_mode = auto` behind a confirmation dialog. It is
   paper-only, and live autonomy stays locked. Its stated reason was to close
   a gap with the reference app. Authority: UNKNOWN (A3).
   *Superseded by Stage 2 (report §4.0, 12 Sep):* the paper's "no auto-trade
   toggle" rule was written by Claude, and the operator's brief did not ask
   for it (C4). The operator had directed autonomy a week earlier (C2 [125],
   17 Jul). Which layer governs is a Checkpoint A decision.
2. **The swing specification is generic.** The paper allows pullbacks or
   breakouts. The code implements one specific form: a pullback to EMA20
   inside EMA20 > EMA50, reclaim, a stop at 2.5 × ATR(14) and a fixed 2R
   target. The methodology's trailing stop and partial take-profit are not in
   the code. "Reconstruct the original swing precisely" may resolve to UNKNOWN
   below the paper's level of detail.
3. **A possible control trap.** Aggregate risk-at-stop is measured at current
   prices against fixed stops. If that holds, a position that rises consumes
   more of the 5% budget, and winners block new entries. That is a hypothesis
   about the ~7.6% reading on 11 September, not a finding.
4. **Regime metadata is missing on every closed trade** (`regime_at_entry`
   blank on all 12 rows). That breaks brief §10's "is regime information
   recorded with trades" before the audit starts.
5. **The AI boundary has a recorded origin.** `ab1ba97` states that the gate
   uses no LLM because "an earlier build of the reference app put a model in
   front of protective exits and it declined 100% of 494 sell signals in a
   day". That is useful for brief §9 and §14.

---

## 5. Synergies with the outstanding items

| # | Outstanding item | Feeds audit section | Under the freeze | Proposed handling |
|---|---|---|---|---|
| 1 | Verify M173's TIF fix on a real market exit | §8 proven vs theoretical | Observation, no change | Continue watching. The audit records its status either way |
| 2 | Orphan rail cannot cancel (by choice) | §8 orphan handling, §16 | Frozen | Becomes a §16 candidate with evidence. No change |
| 3 | First `COMMISSION VERIFIED` (M175) | §11 commission integrity | Observation | Continue watching |
| 4 | Weekly open/close saving | none | **Deferred** (a feature) | Park |
| 5 | M41 earnings hold-through policy | §6 earnings treatment, §7 | **Deferred** (a policy change) | The audit establishes the original intent for earnings first. Decide afterwards |
| 6 | Stage 4 regime re-sourcing | **§10 directly** | **Deferred** (a redesign) | The audit documents the inputs and the 86% VIX dominance as evidence. No redesign |
| 7 | Reach 20 / 30 closed trades | **§13 directly** | Blocked by the cap either way | The audit traces the causal chain behind the cap (indication 3). That is the synergy with the highest value |
| 8 | Watch the status column | §11 | Observation | Continue |
| 9 | HMM's sensitivity to a seventh column | §10 | Deferred | Documented as a known sensitivity |
| 10–11 | Corporate actions / IBKR news | §7, §14 | Closed by decision | The audit records the decisions and their authority. It does not re-open them |
| — | `regime_at_entry` blank (capability doc §8.1) | **§10, §11** | Frozen | Investigate the cause (code reading only). A fix waits for authorisation |
| — | TNE remnant row and label; LOV repair row | **§11** | Frozen | Inventory of repaired and synthetic records |
| — | Ledger audit not scheduled | §11, §16 | Frozen | Candidate |
| — | `session_check.ps1` footer names the wrong gate | §21 (documentation drift) | Frozen | Recorded. Not fixed during the freeze |
| — | Stale `README.md` / `PRODUCT_DESCRIPTION.md` | §3 evidence caution | Frozen | Recorded. Not rewritten (the brief's rule) |
| — | M43 halts, M44 execution quality | §7, §8, §14 | Deferred | Recorded as original-design gaps, if the paper names them |
| — | Unpushed batch (the two capability docs, the CI Node 24 bump) | none | CI only, no trading effect | **Recommend pushing before the freeze starts**, so CI stays healthy. Your call |

The unifying observation: **items 5, 6, 7 and 9 are all design questions the
audit answers first.** Deciding them before the audit would be exactly the
kind of drift the audit is meant to find.

---

## 6. The plan

Every stage is read-only against the system: code, git, logs, ledgers,
documents. Any analysis script lives in the scratchpad, never in `src/`.
Anything that needs a code change to produce evidence is reported as a
required investigation, per the brief.

**Stage 0: your decisions (before anything starts)**
1. ✅ Origin: four Claude chats (answered 12 Sep). ✅ **Export received 12 Sep**:
   `C:\Users\mailm\Downloads\conversations.json`, 8.5 MB, sha256
   `84660483C3B5…5D70`. It holds six conversations: the four substantive chats
   (13 Jul "No-code stock trading bot"; 13–26 Jul "AI-powered stock trading
   with Claude and Alpaca", 319 messages; 23 Jul "Code review"; 24 Jul
   "Comprehensive investment strategies advisory paper", which produced the
   founding paper) and two untitled chats exported with no content. The file
   lacks its opening `[`, so it reads as an extract of a larger export. The
   main chat runs to 26 Jul 22:29, past the autonomy commit (26 Jul 18:23), so
   it may close part of the A3 gap. Not yet read. Then confirm the baseline
   (A1).
2. ✅ Authority column adopted, plus the error log (answered 12 Sep).
3. ✅ The separate market-opinion tool is out of scope. It has no autonomy
   and no trading capability (answered 12 Sep).
4. ✅ **Evidence preserved** (12 Sep, operator agreed). 464 files were copied
   to `%USERPROFILE%\Documents\QAT-audit-evidence\2026-09-12\`: transcripts,
   the qat.log set, the chat export and both statements, with a sha256
   manifest (463 matched their sources at copy time; this session's own
   transcript was still growing). `cleanupPeriodDays` is set to 365 in
   `~\.claude\settings.json`. The archive stays out of git because it holds
   personal details.
5. ✅ **Fresh-context investigators: yes, for Stage 3** (12 Sep), with the
   operator's condition: they **establish fact, not judge** what is good or
   bad. Each gets the code and raw logs only, never HANDOFF, ROADMAP or the
   capability documents, and reports what the code does with file:line
   evidence. No assessments, no recommendations. Judgement stays in the
   report stages, where it is cited.
6. ✅ Operation during the freeze: keep `auto` running unchanged (12 Sep).
   ⛔ **Superseded 14 Sep: trading is suspended for the course of the audit**
   (operator). Stage 5 onward therefore works from the records up to
   12 September. No new live evidence arrives until trading resumes.
7. ✅ **Broker statements received** (12 Sep). `DUQ200898_20260824.pdf` (24 Aug
   only) and `DUQ200898_20260824_20260911.pdf` (24 Aug – 11 Sep, 25 pages,
   sha256 `8E578080…0E69`, NAV 1,004,063.00 → 989,653.14). Both are archived.
8. ✅ Push everything before the freeze, nothing held over (12 Sep).
9. **Locations outside the two project folders (operator, 12 Sep evening):**
   * ✅ approved: `%LOCALAPPDATA%\QuantAdvisoryTerminal` (QAT's data folder),
     read-only;
   * ✅ approved: `Documents\QAT-audit-evidence\`;
   * ✅ approved: Claude Code's own folders (`~\.claude`, and its temp folder
     under `AppData\Local\Temp\claude`);
   * ✅ **approved later the same evening: `C:\ShareTrader`**, read-only. The
     operator describes it as **the original version of this app**. It holds
     the founding paper, the MkI concept, the swing methodology and the
     predecessor app. What was read there before this approval (CE-016) is
     re-read under the approval, not carried over.
   * Everything else stays off-limits (§7).

**Stage 1: Baseline (brief §2).** Commands already proven read-only:
`session_check.ps1`, `handoff_state.py`, the four checks, the suite, the live
`.env` masked, `git` state. *Deliverable:* report §3.

**Stage 2: Original Intent (brief §3).** Read the four Claude chats first,
for the order in which ideas and decisions arrived. Then read the paper in
full, including its tables. Table 14.1, the AI permission boundary, did not
come through a text-only read. Read the master prompt A–O, the acceptance
criteria (§20.O), MkI, the methodology file and the reference app's structure. Then compare
`fa9ba47` and the 25–27 July commits against the paper.
*Deliverables:* report §4, the Original-Intent architecture diagram, and a
"paper vs first commit" delta.

**Stage 3: Current reconstruction (brief §4).** Trace from code and raw logs
only (A4). One table per stage of the flow: modules, inputs, outputs,
authority, state, persistence, failure and refusal behaviour, whether
AI-assisted, and whether it can reach the broker. Import-graph checks for
boundaries (does `ai_advisory` reach OMS or broker code at all?).
*Deliverables:* report §5, the As-It-Is architecture diagram.

**⛔ Checkpoint A: you review Stages 2 and 3.** Every later stage compares
these two baselines, so they must be right first.
**✅ Decided 14 Sep** (report §4.00, §4.001):
* **Purpose:** an app making recommended trades **using AI**, around
  **different trading strategies**.
* **Decisions:** **human, or AI autonomous**. Autonomous means acting on its
  recommendation and completing the trade, subject to the embedded safety
  rails and the selected strategy.
* **Philosophy and strategies:** the paper. The paper's human-sign-off rule is
  superseded.

The operator made no corrections to §4 or §5.

**Stage 4: Drift map and strategy integrity (brief §5, §6).** For each
component, use `git log -S` / `git log --follow` for when it arrived, the
commit message and ROADMAP for why, and transcripts from 4 August for who
decided. Then a line-by-line swing comparison: the paper and methodology
against `strategies/swing.py` and every rail that touches a swing order.
*Deliverables:* report §6–8, the drift map with the authority column.

**Stage 4a: Back-fill the Claude error log.** Runs alongside Stages 4–8,
because the same reading surfaces the errors. Sources: the four chats; commit
messages whose subject says fix, repair, revert or correct; ROADMAP and
HANDOFF incident sections; `docs/archive/`; the surviving transcripts. Each
error goes into `docs/CLAUDE_ERROR_LOG.md` with its evidence, or under "To
establish" if the evidence is thin. The drift map cross-references each
D-class item (agent-generated complexity) to the errors that produced it.
*Deliverable:* a complete error log, with counts by severity and type in the
final report.

**Stage 5: Risk stack and control interactions (brief §7, §13).** Map every
control's position in the pipeline, what it refuses and trims, and which
refusals overlap. Measure throughput from `risk_decisions.csv`: which rail
refused how many entries, by day. Trace the aggregate-cap chain (indication 3)
from positions, stops and prices, as data analysis only.
*Deliverables:* report §9 and §16, the control-interaction diagram.

**Stage 6: Execution boundary and incident → control mapping (brief §8, §14).**
Trace signal to ledger. For each incident (24 Aug duplicates, 3 Sep staged
order, 9 Sep trips, orphaned legs, fill-price basis, corporate actions),
record the control it produced, whether that control was necessary, whether
it is proportionate, and the secondary complexity it added. Then a matrix of
proven live against code-only, cited to log lines.
*Deliverables:* report §10 and §14.

**Stage 7: AI boundary and regime (brief §9, §10).** Inputs and outputs, the
structured schema, tool access, persistent state, what happens when the model
is unavailable. The regime pipeline end to end, from the existing ablation
evidence. Why regime metadata is blank on trades (code reading).
*Deliverables:* report §11 and §12.

**Stage 8: Evidence integrity (brief §11).** An inventory of every repaired or
synthetic record: `scripts/repair_*`, `.bak-*` files, script-written rows,
fragments, blank fields. The ledger against broker statements (A7). For each
issue, record which it affects: operations, risk, performance, validation,
auditability or promotion.
*Deliverable:* report §13.

**Stage 9: Complexity and simplification candidates (brief §12, §16).** Every
candidate gets the brief's questions, a one-sentence purpose test, and a
recommendation from the brief's list. Nothing is removed.
*Deliverables:* report §15 and §20.

**Stage 10: Synthesis (brief §15, §17, §18, §19).** The three architecture
diagrams, explicit answers to brief §17 A–J, the classification, the freeze
recommendation and the remediation sequence.
*Deliverable:* the full 24-section report.

**⛔ Checkpoint B: you review the draft report.** Then it is final.

**Where it lives:** `docs/audit/2026-09-design-recovery/`. The report, an
evidence appendix (every claim with its file:line, commit hash or log line),
and a list of unknowns. Committed only when you say so.

**Effort, honestly:** Stages 1–3 take about one working session, and the
report stages about two or three more. Stage 8 depends on when the statements
arrive. Expect 4–5 sessions of work across the next week or so, with the app
running unchanged beside it (A6).

---

## 7. Explicitly outside the audit

Any fix, refactor or parameter change, including the ones the audit finds.
Rewriting the stale documents. Re-opening M39 or IBKR news. Designing the
stage 4 regime. The operator's separate market-opinion tool.

**Search boundary (operator, 12 Sep).** Claude reads and searches only
`C:\Claude Programming` (development) and `C:\QuantAdvisoryTerminal`
(deployment). Any other location on the operator's computer needs the
operator's permission first, location by location. That includes
`%LOCALAPPDATA%\QuantAdvisoryTerminal`, `C:\ShareTrader`, the evidence archive
and `~\.claude`. The permissions granted are recorded in the Stage 0 list.

## 8. After the audit

Your Phases 4–7 (safety review, controlled simplification, freeze, evidence
accumulation) start only from an approved report. The report's remediation
sequence will propose the order. It will not recommend resuming feature
development because tests pass.
