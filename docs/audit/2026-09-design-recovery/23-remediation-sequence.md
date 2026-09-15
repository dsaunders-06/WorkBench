# QAT Design Recovery & Design Intent Audit, R23: Recommended Remediation Sequence

**Brief §20 ("Remediation sequence"). DRAFT for Checkpoint B.**
**Prepared:** 15 September 2026. **Recommended only. Nothing here is to be
implemented** without the operator's explicit authorisation, phase by phase.
The brief: "Do not recommend returning to feature development simply because
the code passes tests." This sequence does not. The suite has passed
throughout (3,677 passed on 15 Sep), and every defect in this report sits
beside passing tests.

The brief's seven phases are kept in their order. Phases 1–3 are this audit.
Each later phase names its entry condition, its content and its exit.

---

## Checkpoint B: the gate before Phase 4

The operator reviews R1–R24 and decides five things. Each is a decision, not
a fix:

| # | Decision | Options the evidence leaves | Where |
|---|---|---|---|
| D1 | **CE-017**: the exit's leg release before the kill-switch check | reorder, refuse before touching the broker (as the manual close already does), or accept with a procedure | R10 §10.2; R16 §16.3; R22 G1 |
| D2 | **The swing to test**: the methodology (the specification, Q2) or the current rule, recorded as the one under test | implement S, or record the current rule | R8 §8.5; R22 A; R24 §24.5 |
| D3 | **The AI's part** (U1), and Q-R11 | originate, confirm or adjust (Q1 settles "forms"); or defer by decision | R11 §11.5; R21 U1–U2 |
| D4 | **The ledger**: the missed-exit replay defect, and how TNE's shortfall is to be recorded | fix the replay; record the shortfall as a documented correction, not a silent repair (brief §11) | R13 §13.2 |
| D5 | **JHX**: the broker read the operator held until after the audit | read the TWS Orders panel | R21 U5 |

## Phase 1: Design Recovery (this audit, drafted)

What QAT was meant to be: R4 and R18, governed by Checkpoint A and Q1–Q3.
**Exit:** the operator confirms R4, R18 and the readings in R8 §8.5 at
Checkpoint B.

## Phase 2: Evidence Validation (this audit, drafted)

What the implementation does: R5, R9–R14 and R16, measured from the records
to 12 Sep and cited to code and log lines. **Exit:** Checkpoint B. The
unknowns that need a broker read or runtime observation (R21 U5–U9) carry
into Phase 7.

## Phase 3: Drift Classification (this audit, drafted)

Intentional evolution separated from accidental complexity: R6, R7, R15, R19
and R20. **Exit:** Checkpoint B.

## Phase 4: Safety Review

**Entry:** Checkpoint B, with D1 decided.
**Purpose** (the brief): "Ensure that proposed simplification does not
weaken proven safety mechanisms."

Recommended content, in this order:
1. **CE-017**, as decided in D1. It is first because it is the one defect
   that has left a position unprotected (IAG, 9 Sep).
2. **The two leg-cancel paths** (R20 C28). They are one question with CE-017:
   make one path with one test for "gone".
3. **"Unknown IBKR code → halt"** (C21): which codes should halt. It caused
   7 of 19 trips, and each halt disables the re-arm.
4. **Booking at transmission** (C22) and what grew around it (reversal,
   price corrections). The operator kept it on 3 Sep; review it with the
   incidents since (R14 §14.3).
5. **The resting-order scan's false positives** (C24): 9 in 10 wrong, each
   refusing entries.
6. **The missed-exit replay** (C26), as decided in D4.
7. **The interaction traps** (R16): the full-value aggregate count, and the
   possible zero-Kelly lock at 20 trades. Both decide whether evidence can
   accumulate at all.
8. **The regime's launch artefact and the cash cap's override of sizing**
   (C31, C18): not safety defects, but both decide trades in ways nobody
   chose.

**Rule for the whole phase:** no control is removed because it looks
redundant. Controls that never acted (C14–C17, C19) stay unless the review
shows they cannot act at all.

**Exit:** a reviewed, authorised change list, with each change's safety
effect stated.

## Phase 5: Controlled Simplification

**Entry:** Phase 4's list authorised.

* **Candidates:**
  - R20's three REMOVE rows (C2, C10, C34);
  - its five CONSOLIDATE rows (C14, C27, C28, C29, C33);
  - the INVESTIGATE rows the operator chooses to act on.
* **Design recovery work belongs here, if D2 or D3 choose it**: implementing
  the swing specification, or the AI's part in the recommendation. These are
  changes to trading behaviour, so each needs its own authorisation, tests
  against the specification (not only against the code), and a review
  against R18.
* **One change at a time**, each deployed with `scripts/deploy.ps1` and
  observed before the next, so a new incident can be traced to one cause
  (R14 §14.3 point 4).

**Exit:** the recovered architecture and strategy, matching R18 where the
operator decided it should.

## Phase 6: Freeze

**Entry:** Phase 5 complete.
* Freeze the recovered architecture, the strategy and the configuration as
  one named, deployed build.
* Record the strategy under test in words the operator approved: the
  specification, or the recorded rule (D2).
* State the settings the test runs under, including `execution_mode`.

**Exit:** the operator's sign-off on the frozen build.

## Phase 7: Evidence Accumulation

**Entry:** Phase 6. Controlled paper (or shadow) trading on the frozen
build.

* **The test condition is the operator's:** 10 working days, extended to 60
  once the machinery is proven (Q2).
* **Before it starts, the evidence chain must be able to carry the
  evidence:**
  - the ledger records the regime on every trade (R13);
  - a partly-filled exit while the app is closed is booked correctly (D4);
  - commission verification has run at least once (R10: code only today);
  - the time-in-force fix has been seen on a real exit (R10: never run).
* **Observe the unknowns that need runtime** (R21 U6–U9, U19) during the
  first sessions.
* **Measured Kelly and promotion**: agree in advance what happens at 20 and
  at 30 closed positions, given the possible zero-Kelly lock (R16 §16.2).
* **Feature development stays frozen** until the evidence meets the bar the
  operator set: autonomy "tied to tested rules" (AE-01) and "the fullest
  confidence the mechanism works" (AE-13).
