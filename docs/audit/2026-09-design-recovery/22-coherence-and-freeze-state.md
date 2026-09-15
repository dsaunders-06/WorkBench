# QAT Design Recovery & Design Intent Audit, R22: Coherence, and the Recommended Freeze State

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §17 ("Determine whether QAT remains conceptually coherent"), questions
A–J. J is the recommended freeze state (report section 22). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026, from the drafted sections R3–R20. Nothing
was changed.

The brief asks for explicit answers and, in §21, not to aim for a good
result. Each answer below leads with a plain yes or no, then gives the
evidence. Where the evidence is thin the answer says so.

---

## A. Is the original strategy still recognisable in the implementation?

**Only in outline. Against the specification the operator named, no.**

* It is recognisable as the paper's generic swing: a pullback to the 20-day
  EMA in an uptrend, a 2.5 × ATR stop and a 2R target (R8 §8.1).
* It is not the operator's method. The operator confirmed on 14 Sep that
  `Swing Trader methodology.md` is the specification (R8 §8.5 Q2). Missing
  from QAT are:
  - the rejection tail, the wait for the daily close and the next-open entry;
  - the weekly filter, volume confirmation and the resistance check;
  - the half-off at 1R, the breakeven stop and the trailing stop.
* QAT also decides on the forming intraday bar, and holds up to 30 trading
  days against a test condition of 10 working days (R7 #15, #18, #20).
* The rule is the first commit's, written by the agent. The methodology was
  requested for the first build and not implemented (CE-026).

## B. Is the architecture still consistent with the original intent?

**The scaffolding is; the decision core is not.**

* **Consistent** (R18 against R17):
  - the layers and the event bus;
  - a risk engine between signal and order;
  - an OMS where only sign-off transmits;
  - a broker adapter to IBKR, reconciliation and a kill switch;
  - human or autonomous fulfilment, selectable.
* **Not consistent**, at the point where a trade is decided (R19):
  - no AI takes part in forming the recommendation (R7 #3);
  - there is no decision matrix, and one strategy runs (R7 #4, #5);
  - market data is not validated (R7 #10);
  - features are computed three times, one of them unused (R15 C10).

## C. Has safety complexity materially altered trading behaviour?

**Yes.** The rails, and how they interact, decide more of what trades than
the strategy does:
* **Size:** no entry took its 1% risk budget (0.13–0.70% of equity, median
  0.45%). The 10%-of-cash cap cut 18 of 20 entries after the risk engine had
  sized them (R9 §9.2; R15 C18).
* **Whether to enter:**
  - the position count refused 4,265 decisions (R9);
  - on 11 Sep all 449 refusals traced to one position counted at its whole
    value (R16 §16.1);
  - the resting-order quarantine refused entries on detections that were
    wrong 9 times in 10 (R10).
* **Exits:**
  - the kill switch refused 158 exit decisions (R9);
  - the minimum hold held IAG's exit back for 7 days (R16);
  - "halt on an unknown IBKR code" caused 7 of the 19 trips (R14).

Most of these controls followed real failures and were necessary (R14 §14.3).
The point is not that they are wrong. It is that they, and not the strategy,
set much of what the account does.

## D. Has agent-driven development introduced architectural drift?

**Yes, and the most important drift is agent-only and dates from the first
two builds.**
* Of the 59 drift items, 10 are agent-only (R7 §7.7). They include:
  - the swing rule (CE-026);
  - no decision matrix and no validation (CE-027);
  - dropping the AI's approved role in entries (CE-021).
* Later, the exit's leg release (CE-017) was approved on a claim of Claude's
  that was wrong (AE-29).
* Most later changes were operator-directed or operator-approved (R7 §7.7).
  The operator's Q3 answer names the mechanism: "branches … formed,
  sometimes from misinformation, or not anchoring back to the fundamentals".

## E. Are there controls that now interact in ways the original design did not anticipate?

**Yes** (R16):
* the kill switch disables the protective re-arm that the exit's leg release
  relies on (CE-017);
* one position at its whole value, from a stop the app does not know or a
  price at or below the stop, fills the aggregate cap and refuses every entry
  (A2M, IAG, JHX);
* on the record so far, measured half-Kelly would be zero at the 20-trade
  switch, stopping the entries that produce the evidence (derived,
  conditional);
* the cash cap overrides the engine's sizing (R15 C18);
* the minimum hold holds back an exit signal given on the entry day.

## F. Is QAT still understandable by one technically competent person?

**No, not reliably, as it stands.**
* It is 51,473 lines in 184 modules, with 110 settings and an 18-rail gate
  (R15 §15.1). Each component can be read. The behaviour is set by their
  interactions (E), and the records disagree about what is held (R15 C22).
* 37% of the code is prose, and the audit has found five pieces of it false
  (R15 C33).
* **The builder and the operator both misread it on the record:**
  - CE-017's ordering was approved on a wrong claim;
  - "86% VIX dominance" was a confounded measurement (CE-032);
  - "the TNE remnant" survived three documents before the broker's statement
    disproved it (CE-034);
  - by the code's own comment, the regime's label/mass split cost "a live
    session's worth of investigation" on 7 Aug (`engine.py:535-541`; a
    comment, so a claim).
* It took this audit four investigators and three days to reconstruct.

## G. Is there anything currently implemented that should NOT be part of QAT?

**Yes. In the auditor's view:**
1. **The exit's leg release before the kill-switch check (CE-017).** It can
   leave a position unprotected and prevents its own recovery. It did so on
   9 Sep.
2. **The missed-exit replay's sizing from one partial execution** (R13
   §13.2). It removes shares from the ledger.
3. **The system prompt's "Final trading decisions are made by a human"**,
   which is false in `auto` (R11 §11.4).
4. **The 30-trading-day time stop**, which no operator decision chose over
   the specification's 10 working days (R8 §8.5).
5. **Code nothing uses**: the storage layer, the unused feature computation,
   and `version.py`'s comment history (R20, the three REMOVE rows).

Each is a recommendation for the operator. None has been changed.

## H. Is anything important from the original design now missing?

**Yes:**
* **the AI's part in forming the recommendation** (Checkpoint A; Q1). The
  largest gap (R7 #3);
* **the operator's swing method**, including its trade management (A);
* **the decision matrix** that activates strategies by regime (R7 #5);
* **data validation** (R7 #10);
* **Kelly from measured inputs**: placeholders until 20 trades, and on the
  record so far measured Kelly would be zero (R7 #22; R16);
* **the paper's order lifecycle**, where a position exists once filled, not
  once sent (R7 #42);
* **an audit record that carries why a trade happened**: the regime is blank
  on 12 of 12 ledger rows (R7 #14);
* **the AI's rationale beside each order at sign-off** (P §14.1; R7 #56).

## I. Is the current system suitable for continuing evidence collection?

**No, not as it stands.** The evidence it would collect:
* **measures a strategy the operator did not specify.** It trades the first
  commit's rule, not the methodology (A). Paper results would validate the
  wrong strategy;
* **is recorded by a ledger with a known defect**: an exit that fills in
  pieces while the app is closed loses shares from the ledger (R13 §13.2).
  The ledger also books at transmission and carries no regime (R13);
* **cannot reach its own gates at the current rate**: 8 positions closed
  towards the 20-trade Kelly switch and the 30-trade promotion bar, with a
  possible zero-Kelly lock at 20 (R16 §16.2);
* **runs behind an open safety defect** (CE-017), and **a resting stop that
  did not fill below its trigger** (JHX) is not yet explained (tracker
  section 2).

## J. Should development remain frozen pending remediation? The recommended freeze state

**Yes.** The auditor recommends the freeze and the trading suspension both
continue until the operator has reviewed this report (Checkpoint B) and
decided the items below.

| Area | Recommended state | Why |
|---|---|---|
| Code (`src/`) | **Frozen.** No features, refactors or fixes | brief §1; the operator's 12 Sep instruction |
| Configuration | **Unchanged**, including `execution_mode=auto` | the operator's instruction; a change would itself be a decision to make at Checkpoint B |
| Trading | **Suspended**: the app not launched | the operator, 14 Sep; CE-017 is live whenever the app runs |
| Records | **Preserved**: no repairs, no clean-up of backups or logs | brief §11 ("do not silently repair"); R13 |
| Audit work | may continue, read-only | the rest of the report, and the error-log back-fill |
| Broker read for JHX | only if the operator asks | held by the operator until after the audit |

**What would end the freeze**, recommended and not decided here:
1. the operator's review of the full draft (Checkpoint B), including Q-R11;
2. a decision on CE-017;
3. a decision on the swing specification: implement the methodology, or
   record the current rule as the one to test;
4. a decision on the missed-exit replay defect, and on how the ledger's TNE
   shortfall is to be recorded (not silently repaired);
5. the JHX broker read.

R23 sets these out as the remediation sequence.
