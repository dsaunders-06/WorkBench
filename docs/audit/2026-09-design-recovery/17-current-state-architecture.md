# QAT Design Recovery & Design Intent Audit, R17: Current-State Architecture

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §15, first diagram ("QAT as it is"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026, from the drafted sections R5 and R9–R16. It
represents the deployed build (M175) as it runs, not as it could be: "Do not
design an ideal future architecture. Represent reality."

**How to read it**
* **Solid lines** are paths the live record shows running (R10 §10.3).
* **Dashed lines** exist in code and have never run live, or run but decide
  nothing.
* **Red** marks a known defect: CE-017, the TNE ledger shortfall.
* Code the app never imports (R15 §15.1) is not drawn.

```mermaid
flowchart TD
    classDef codeonly stroke-dasharray: 5 5
    classDef defect stroke:#c0392b,stroke-width:3px

    subgraph DATA["Market data"]
        YF["yfinance: 1-minute poll every 60 s<br/>modelled 20-minute delay"]
        BARS["Daily bars, including today's forming bar<br/>300 seeded at each launch"]
        FRED["FRED hourly: VIXCLS, T10Y3M, BAA10Y<br/>(DGS3MO, DGS10 fetched, shown, unused)"]
    end

    REG["Regime engine: 4-state HMM + fixed rules + hysteresis<br/>refits once per launch; first label often a launch artefact"]
    STRAT["Strategy engine: swing only, on the forming bar<br/>(14 other strategies present, not deployed)"]
    BRIDGE["Signal bridge: de-dup, weekly budget,<br/>10-day minimum hold, 30-day time stop"]
    RISK["Risk engine: min(Kelly on placeholders, 1% ÷ stop)<br/>× regime scalar × earnings → governor → ES → cost rail"]
    OMS["OMS: allow lists, quarantines, kill switch,<br/>10%-of-cash cap (cut 18 of 20 entries)"]
    PEND["Pending sign-off"]
    GATE["Autonomy gate, 18 rails<br/>(signed every ASX-era order in the log)"]
    BLOT["Blotter: human sign-off"]:::codeonly
    SIGN["Sign-off: the only caller of place_order"]
    IBKR["IBKR paper (Gateway)<br/>MKT parent + STP and LMT legs, OCA, GTC"]
    BOOK["Position booked at transmission,<br/>at the reference price"]
    RECON["Reconciliation every 300 s:<br/>quantity compare, mismatch → kill switch"]
    LEDGER["Ledger closed_trades.csv<br/>7 repairs; TNE loss understated"]:::defect
    PERF["Reports, equity curve, scorecard"]
    KS["Kill switch: blocks every sign-off<br/>19 trips, 7 from unknown IBKR codes"]
    EXIT["Exits: trend-break signal, time stop<br/>release the legs BEFORE the kill-switch check"]:::defect
    PROT["Protection: bracket at entry; re-arm every 300 s;<br/>resting-order scan (1 detection in 10 real)"]
    MAN["Manual close, sells only"]:::codeonly
    AI["AI advisory, local model: AI Advisor, Workbench,<br/>Regime Monitor, report notes. No path to any trade decision"]
    SCREENS["Screens and report text"]

    YF --> BARS
    BARS --> REG
    FRED --> REG
    BARS --> STRAT
    REG -- "probability mass: eligibility" --> STRAT
    REG -- "label: size scalar" --> RISK
    STRAT -- "signal, every tick" --> BRIDGE
    BRIDGE -- "buy" --> RISK
    RISK --> OMS
    OMS --> PEND
    BRIDGE -- "sell" --> EXIT
    EXIT --> PEND
    PROT --> PEND
    PEND --> GATE
    GATE --> SIGN
    PEND -.-> BLOT
    BLOT -.-> SIGN
    KS -- "refuses" --> SIGN
    SIGN --> IBKR
    SIGN --> BOOK
    IBKR -- "executions" --> RECON
    RECON --> BOOK
    BOOK --> LEDGER
    LEDGER --> PERF
    PERF -.->|Kelly inputs after 20 trades, 8 so far| RISK
    MAN -.-> IBKR
    AI --> SCREENS
```

## 17.1 Each box, with its evidence

| Box | What the diagram claims | Evidence |
|---|---|---|
| Market data | yfinance polled every 60 s with a modelled 20-minute delay; daily bars include today's forming bar; 300 bars seeded at launch | R5 §5.1; investigator 1 A |
| FRED | three series feed the regime; `DGS3MO` and `DGS10` are fetched and shown only | R12 §12.1; R15 C11 |
| Regime engine | HMM + fusion rules + hysteresis; one refit per launch; the launch artefact | R12 §12.1–§12.2 |
| Strategy engine | swing only, evaluated every tick on the forming bar; 14 strategies undeployed | R5 §5.3 #6; R7 #4 |
| Signal bridge | de-dup, weekly budget, minimum hold, time stop | R5 §5.1 |
| Risk engine | sizing is the smaller of Kelly on placeholders and the 1% budget, times the regime and earnings scalars | R9 §9.1–§9.2 |
| OMS | the cash cap cut 18 of 20 entries after approval | R9 §9.2 |
| Autonomy gate / Blotter | the gate signed every ASX-era order in the log; the Blotter has never signed one live | R10 §10.3 |
| Sign-off → IBKR | the only caller of `place_order`; bracket structure | R10 §10.1 |
| Booked at transmission | quantity booked whatever status IBKR returns | R5 §5.3 #2; R14 §14.3 |
| Reconciliation | 300-s poll; 6 trips, all from the app's own record | R14 incident 3 |
| Ledger | seven repairs; TNE's loss understated by 6,937.44 | R13 |
| Kill switch | 19 trips; 7 from the halt-on-unknown-code rule | R9; R14 |
| Exits | legs released before the kill-switch check (CE-017) | R10 §10.2 |
| Protection | brackets, re-arm, the resting-order scan's hit rate | R10 §10.2–§10.3 |
| Manual close | never run live | R10 §10.3 |
| AI advisory | display only; no path to any trade decision | R11 §11.2 |
| Kelly feedback | switches to measured inputs at 20 closed positions; 8 so far | R16 §16.2 |
