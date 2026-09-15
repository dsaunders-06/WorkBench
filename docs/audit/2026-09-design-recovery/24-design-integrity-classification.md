# QAT Design Recovery & Design Intent Audit, R24: Final Design-Integrity Classification

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §18 ("Final classification"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026, from R3–R22. The classification is the
auditor's, for the operator to accept or reject at Checkpoint B.

## 24.1 The classification

> ## 🔴 RED: DESIGN COMPROMISED
>
> *"The current implementation no longer reliably represents the original
> design and requires recovery before further development or testing."*

## 24.2 Why RED

The original design, as the operator stated it at Checkpoint A, is:
* "a Share Trading App capable of making **recommended trades using AI**";
* "designed around **different trading strategies**";
* decisions "either Human or AI autonomous";
* philosophy and strategies informed by the paper;
* the operator's swing methodology as the swing specification (Q2).

Against that:

| The design's core | The implementation | Evidence |
|---|---|---|
| Trades recommended **using AI** | **No AI output reaches any trade decision.** The AI is advisory only | R11 §11.2, §11.5; R7 #3 (H) |
| **Different trading strategies**, activated by regime (the matrix) | One strategy; no matrix or allocator | R7 #4, #5 |
| **The operator's swing method** | The first commit's rule, on the forming bar; none of the specification's management | R8 §8.5; R22 A |
| Human or AI-autonomous fulfilment, bounded by the rails | **Present.** The gate fulfils within the rails. But what it fulfils is the rule's signal, not an AI recommendation | R10; R19 |
| Evidence that the strategy works (tested rules, measured Kelly) | Placeholders; a ledger with a known defect; a possible zero-Kelly lock | R13; R16 §16.2 |

Three of the four core elements the operator named (the AI's recommendation,
several strategies, the specified swing) are not implemented. The fourth,
autonomy, exists but acts on something other than what the design says it
should act on. That is "no longer reliably represents the original design".

"Requires recovery before further development or testing" follows from R22
I: continued paper trading would test a strategy the operator did not
specify, record it in a ledger with a known defect, and run behind an open
safety defect (CE-017).

## 24.3 Why not AMBER

AMBER needs "the original design remains recognisable". The scaffolding is
recognisable (R22 B). The layers, the risk checkpoint, sign-off-only
transmission, the broker adapter, reconciliation and the kill switch are all
as intended.

But the design the operator described is defined by **what forms and
fulfils a recommendation**, and that part is not recognisable. The strategy
is recognisable only as the paper's generic swing, not as the operator's
(R22 A).

## 24.4 What RED does not mean

* **Not that the safety work is wasted.** Most controls followed real
  failures and were necessary (R14 §14.3). The frozen system trades nothing
  and holds its stops at the broker (tracker section 2, JHX excepted).
* **Not that the drift was mostly unauthorised.** 48 of 59 drift items were
  operator-directed or operator-approved (R7 §7.7). The drift that decides
  the classification is agent-only and dates from the first builds (R19).
* **Not a recommendation to rebuild.** The brief's remediation phases (R23)
  begin with a safety review and controlled, authorised steps.

## 24.5 What would move the classification

The classification rests on readings the operator can confirm or change at
Checkpoint B:
* **If the operator chose to test the current swing rule** instead of the
  methodology, element 3 would become a recorded decision rather than drift.
* **If the AI's part were deferred by decision** (the degree is the
  operator's to set, R4 §4.001), element 1 would become a recorded gap rather
  than a compromise.

With both, the evidence would support **AMBER**: the design recognisable,
and the complexity and defects (CE-017, the ledger replay, the regime's
launch artefact, the cash cap's override) requiring attention.
