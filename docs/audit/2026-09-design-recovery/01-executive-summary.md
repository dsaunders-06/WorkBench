# QAT Design Recovery & Design Intent Audit, R1: Executive Summary

**DRAFT for Checkpoint B. Prepared 15 September 2026.** Written last, from
R2–R24. Nothing in the system was changed during the audit.

## The brief's most important question

> *"If I removed all of the subsequent Agent fixes, patches and feature
> additions, what was QAT actually intended to be — and how far has the
> current implementation moved away from that design?"*

**What QAT was meant to be** (the operator, Checkpoint A, R4 §4.00, and
Q1–Q2, R8 §8.5):
* a share-trading app that makes **recommended trades using AI**;
* designed around **different trading strategies**, activated by regime
  within the paper's philosophy;
* the swing strategy first, **to the operator's own methodology**;
* one recommendation, formed by the AI within the strategy and the rules;
* fulfilled either by a human or autonomously, bounded by the safety rails;
* tested on paper before any live capital.

**How far it has moved** (R19):
* **The frame is intact**: the layers, the risk checkpoint, sign-off-only
  transmission, IBKR, reconciliation, the kill switch, and human or
  autonomous fulfilment.
* **The core is not**:
  - **no AI takes part in any trade decision** (R11);
  - **one strategy runs, with no decision matrix** (R7 #4, #5);
  - **the swing it runs is not the operator's method**: it is the first
    commit's rule, decided on the forming intraday bar (R8).

  These three drifts are agent-only and date from the first two builds
  (R7 §7.7; CE-021, CE-026, CE-027).
* Later changes were mostly operator-directed or operator-approved: 48 of 59
  drift items.

## The classification

**🔴 RED: DESIGN COMPROMISED** (R24).
* Three of the four core elements the operator named are not implemented.
  The fourth, autonomy, acts on the rule's signal, not on an AI
  recommendation.
* It would become AMBER if the operator chose, by decision, to test the
  current rule and to defer the AI's part (R24 §24.5).

## What the audit found, in brief

1. **A live safety defect (CE-017).** An exit releases a position's broker
   stop before the kill switch is checked, and the switch then blocks the
   re-arm. IAG was unprotected for about an hour on 9 Sep. It cannot occur
   while the app is not running. It is not fixed (R10, R16).
2. **The rails, not the strategy, decide much of what trades** (R9, R16):
   - no entry took its 1% budget;
   - the cash cap set 18 of 20 entry sizes;
   - on 11 Sep one position counted at its whole value refused every entry;
   - "halt on an unknown IBKR code" caused 7 of 19 kill-switch trips.
3. **The regime label is often an artefact of the launch**, and the US VIX
   below 15 sets it by a fixed rule. The "86% VIX dominance" measurement was
   confounded (R12; CE-032).
4. **The ledger matches IBKR on 7 of 8 closed positions, but not TNE.** TNE's
   loss is understated by 6,937.44, because of a code defect in the
   missed-exit replay. Seven repairs have rewritten the ledger (R13).
5. **The complexity that costs most is live and came from fixes.** Little is
   dead weight: 7% of the code never runs in the app (R15). Of 37
   simplification candidates, 3 removals are recommended, none of them a
   control (R20).
6. **The evidence gates cannot be reached as things stand.** 8 positions
   have closed towards the 20-trade Kelly switch and the 30-trade promotion
   bar, and measured Kelly would be zero at 20 on the record so far (R16).
7. **QAT is not reliably understandable by one person.** The builder and the
   operator both misread it on the record, and 37% of the code is prose,
   some of it false (R22 F; R15).

## Recommendations (R22, R23)

* **Keep development frozen and trading suspended** until Checkpoint B.
* **Decide five things at Checkpoint B** (R23):
  - D1: CE-017;
  - D2: which swing to test, the methodology or the current rule, recorded;
  - D3: the AI's part, with Q-R11;
  - D4: the ledger replay defect, and how TNE's shortfall is recorded;
  - D5: the JHX broker read.
* **Then follow the brief's phases**: safety review, controlled
  simplification, freeze, then evidence accumulation under the operator's
  10-working-day test condition.
* **Not** a return to feature development because the tests pass. They have
  passed throughout (3,677 on 15 Sep), beside every defect above.

## What is not known

18 unknowns remain open (R21; 3 more were settled in the history back-fill):
* 4 are the operator's to decide;
* 5 need a broker read or runtime observation. The most pressing is why
  JHX's resting stop did not fill below its trigger on 11 Sep.

## A note on the auditor

This audit was carried out by the same kind of agent that built QAT and
wrote most of its documents. The mitigations are in R2 §2.2. The error log
records 36 of Claude's errors, several made during the audit itself (R2
§2.4).
