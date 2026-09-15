# QAT Design Recovery & Design Intent Audit, R2: Audit Scope

**Brief §19, section 2. DRAFT for Checkpoint B.**
**Prepared:** 15 September 2026. The scope was set by the operator's brief
(12 Sep, transcript `ede4fc1d`, 07:49Z) and the plan the operator adopted
with eight amendments (`docs/superpowers/plans/2026-09-12-design-recovery-audit-plan.md`).

## 2.1 What was audited

* **The system:** QAT at the deployed build, M175 (`5e322ca`). `src/` was
  level with it throughout (R3).
* **Its records:** the log (27 Jul – 12 Sep), `closed_trades.csv`,
  `risk_decisions.csv`, `decision_journal.csv`, the entry records, the
  report files and 27 backups.
* **The broker's record:** the IBKR statement for 24 Aug – 11 Sep, the only
  source independent of QAT (R13).
* **Its history:** 951 commits up to the deployed build (982 to 15 Sep,
  the rest audit documents), dated with `git log -S`.
* **Its design intent:**
  - the operator's words in the Claude Code transcripts (every day from
    24 Jul, typed messages and dialog answers), and in the four claude.ai
    chats before that;
  - the paper;
  - the swing methodology;
  - the reference app in `C:\ShareTrader`.

**Depth** (plan A5):
* **full depth** on the live decision path (data → regime → swing → sizing →
  risk → gate → OMS → broker → reconciliation → ledger) and on the AI
  boundary;
* **survey depth** for the 14 undeployed strategies, the UI, the research
  harness and reporting.

## 2.2 How

* **The current system was reconstructed from code and raw logs only**, by
  four fresh-context investigators who never read HANDOFF, ROADMAP or any
  Claude-written document (plan A4; R5 §5.0). Their reports are kept verbatim
  in `stage3/`.
* **Claude-written documents were treated as claims to test**, never as
  evidence: HANDOFF, ROADMAP, README, commit messages, code comments and the
  capability documents (CE-018). The audit found several of them wrong
  (CE-032, CE-034; R15 C33).
* **Authority came from the operator's own words**, register
  `stage4/authority-evidence.md` (AE-01 to AE-35). Each drift item carries
  who decided it (plan A2).
* **Each figure came from a small read-only tool**, kept beside its section
  and lint-clean. Every figure was written with its tool output open
  (CE-031).
* **Two checkpoints:**
  - A (14 Sep): the operator's statement of intent;
  - B (pending): the operator's review of this report.

## 2.3 Boundaries

* **Nothing was changed.** No fix, refactor, parameter or configuration
  change, and no repair of records (brief §1, §11). Defects found were
  reported. The one live safety defect (CE-017) was reported the day it was
  found, and the operator chose to continue the audit.
* **Trading was suspended** from 14 Sep (the operator). The audit works from
  the records up to 12 Sep and observed no live session.
* **The search boundary** (the operator, 12 Sep):
  - `C:\Claude Programming` and `C:\QuantAdvisoryTerminal`;
  - approved read-only: QAT's data folder, the evidence archive, Claude
    Code's own folders and `C:\ShareTrader`.

  Two early breaches are logged (CE-015, CE-016).
* **Out of scope:**
  - the operator's separate market-opinion tool (plan A8);
  - re-opening M39 and IBKR news;
  - designing a new regime system (brief §10);
  - rewriting stale documents.

## 2.4 Limits the reader should weigh

* **The auditor is the same kind of agent that built QAT and wrote most of
  its documents.** The investigators' independence (2.2) and the
  claims-to-test rule are the mitigations. The error log records **36 of
  Claude's errors**, several of them made during the audit itself.
* **No broker access.** The broker's positions and resting orders were not
  read (Gateway closed). The JHX stop (R21 U5) is the open consequence.
* **No runtime observation.** Behaviour that leaves no log line (staleness
  exclusions, passes of the drift check) is NOT DETERMINED (R21).
* **The log has a 66-minute hole** on 24 Aug (R13 §13.6).
* **The rollback directories** beside the install are outside the boundary
  and were not measured (R3 §3.6).

## 2.5 Evidence preserved

`Documents\QAT-audit-evidence\` holds dated snapshots with sha256 manifests:
* `2026-09-12`: 463 files, including the logs, the chats and the IBKR
  statements;
* `2026-09-14`, `2026-09-14-stage4`, `2026-09-14-s07-s14`;
* `2026-09-15`, `2026-09-15-s11`, `2026-09-15-s12-s16`.

Claude Code's retention was raised to 365 days. The statements and the chat
export are never committed (personal details).
