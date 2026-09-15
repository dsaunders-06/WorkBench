# QAT Design Recovery & Design Intent Audit, R19: Design-Drift Architecture

**Brief §15, third diagram ("QAT design drift"). DRAFT for Checkpoint B.**
**Prepared:** 15 September 2026. The brief: "Show the significant
differences between the two" (R18 against R17).

**How to read it**
* Each arrow runs from the intended component (left, R18) to what exists
  (right, R17).
* The label gives R7's class, then who decided (R7's Authority column):
  - **E**: behaviour change; **D**: agent-generated complexity; **C**:
    defensive fix; **A**: original design;
  - **OD**: operator-directed; **AP/OA**: agent-proposed, operator-approved;
    **AO**: agent-only.
* **Red** is drift the operator never directed. **Amber** is a change the
  operator directed or approved. **Green** is consistent with the operator's
  own sequencing.

The significant differences are those R7 rates **H** or that sit on the path
from signal to order. The full list of 59 items is R7.

```mermaid
flowchart LR
    classDef ao fill:#fdecea,stroke:#c0392b,stroke-width:2px
    classDef od fill:#fff4e0,stroke:#d68910,stroke-width:2px
    classDef ok fill:#eafaf1,stroke:#1e8449,stroke-width:2px

    subgraph INTENDED["QAT as originally intended (R18)"]
        I1["AI forms the recommendation<br/>within strategy and rules"]
        I2["Decision matrix across<br/>several strategies"]
        I3["Different strategies,<br/>swing first"]
        I4["Swing = the operator's methodology,<br/>decided on the daily close"]
        I5["Swing test hold:<br/>10 working days"]
        I6["Validation of market data"]
        I7["Kelly with measured<br/>win rate and payoff"]
        I8["Autonomy tied to tested rules"]
        I9["Order lifecycle: pending,<br/>transmitted, then filled"]
        I10["Positions always protected;<br/>exits mechanical"]
        I11["Regime inputs chosen<br/>for the market traded"]
        I12["An audit record of<br/>every decision and trade"]
    end

    subgraph CURRENT["QAT as it is (R17)"]
        C1["No AI in any trade decision;<br/>AI answers go to screens only"]
        C2["No matrix: each strategy<br/>gated alone on regime mass"]
        C3["One strategy deployed: swing"]
        C4["The first commit's EMA rule,<br/>on the forming intraday bar"]
        C5["30-trading-day time stop"]
        C6["validation.py never run"]
        C7["Placeholders 0.55 / 1.5 until 20 trades;<br/>measured Kelly may be zero"]
        C8["Promotion evidence enforced<br/>on live only"]
        C9["Booked at transmission;<br/>fills absorbed in a 5-minute poll"]
        C10["Exit releases legs before the<br/>kill-switch check: CE-017"]
        C11["US VIX, curve, credit;<br/>VIX below 15 sets low_vol"]
        C12["Ledger: regime blank 12 of 12,<br/>TNE understated, 7 repairs"]
    end

    I1 -->|"E · AO · R7 #3"| C1
    I2 -->|"E · AO · R7 #5"| C2
    I3 -->|"A · OD · R7 #4"| C3
    I4 -->|"E · AO · R7 #15, #18"| C4
    I5 -->|"E · AP/OA batch · R7 #20"| C5
    I6 -->|"E · AO · R7 #10"| C6
    I7 -->|"E+B · AP/OA · R7 #22"| C7
    I8 -->|"gap · AP/OA · R7 #2"| C8
    I9 -->|"E+C · OD kept · R7 #42"| C9
    I10 -->|"C then D · AP/OA on a wrong claim · R7 #45"| C10
    I11 -->|"E · OD to defer · R7 #11"| C11
    I12 -->|"E · AO defect · R7 #14, R13"| C12

    class C1,C2,C4,C6,C12 ao
    class C5,C7,C8,C9,C10,C11 od
    class C3 ok
```

## 19.1 The differences, with their evidence

| # | Intended (R18) | Current (R17) | Class · authority | Risk (R7) | Evidence |
|---|---|---|---|---|---|
| 1 | The AI forms the recommendation, within the strategy and the rules | No AI output reaches any trade decision | E · AO (CE-021) | H | R7 #3; R11 §11.5 |
| 2 | A decision matrix activates strategies by regime | Each strategy is gated alone on regime mass; no allocator | E · AO (CE-027) | M, H with a second strategy | R7 #5 |
| 3 | Several strategies, swing first | One strategy deployed | A · OD | L | R7 #4 (the operator's sequencing, not drift) |
| 4 | Swing is the operator's methodology, decided on the daily close | The first commit's rule, on the forming intraday bar | E · AO (CE-026) | H | R7 #15, #18; R8 §8.5 |
| 5 | Test hold of 10 working days | 30-trading-day time stop | E · AP/OA, batch | M | R7 #20; R8 §8.5 Q2 |
| 6 | Market data validated | `validation.py` never runs | E · AO (CE-027) | M | R7 #10; R15 C1 |
| 7 | Kelly from measured win rate and payoff | Placeholders until 20 closed positions; on the record so far, measured half-Kelly would be zero | E+B · AP/OA | M | R7 #22; R16 §16.2 |
| 8 | Autonomy tied to tested rules | The scorecard is enforced on live only | gap · AP/OA (operator informed, AE-06) | M | R7 #2 |
| 9 | Pending, transmitted, then filled | Booked at transmission; the common root of many incidents | E+C · OD (kept 3 Sep, AE-28) | H | R7 #42; R14 §14.3 |
| 10 | Positions always protected; exits mechanical | An exit releases its legs before the kill-switch check | C, then D · AP/OA on a wrong claim (AE-29) | H | R7 #45; CE-017 |
| 11 | Regime inputs fit for the market traded (the paper names them by concept) | US series; the US VIX sets low_vol below 15; a launch artefact | E · OD to defer | H | R7 #11; R12 §12.3 |
| 12 | An audit record of every decision and trade | Regime blank on 12 of 12 ledger rows; TNE understated; seven repairs | E · AO (defect) | M | R7 #14; R13 |

## 19.2 What the drift diagram shows

1. **Most of the red drift sits at the front of the path**: data (6),
   strategy (2, 4) and recommendation (1). It is agent-only and dates from the
   first two builds (R7 §7.7). The other red item is the evidence record at
   the end (12), a defect.
2. **Most of the amber changes sit at the back**: sizing (7), fulfilment (8),
   orders (9) and protection (10). The operator approved or directed them,
   one of them (10) on a claim of Claude's that was wrong. Two amber items sit
   earlier: the time stop (5), and the regime inputs, whose re-sourcing the
   operator deferred (11).
3. **The one difference that is not drift** is the single strategy (3). It is
   the operator's own sequencing: swing first.
