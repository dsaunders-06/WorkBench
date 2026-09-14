# QAT Design Recovery & Design Intent Audit, report section 7: Design Drift Map

**Stage 4 of the audit plan. DRAFT for Checkpoint B.**
**Prepared:** 14 September 2026. Read-only: nothing in the system was changed.

## 7.0 How to read the map

**Original intent** is the governing baseline from Checkpoint A (report
§4.00, §4.001). It consists of:
* **OP**: the operator's statement of intent and their recorded direction;
* **P**: the paper, for philosophy and strategies;
* **L1** evidence (**S** the methodology file, **R** the reference app), where
  those two are silent.

The paper's human-sign-off rule is superseded.

**Current** is report §5 and the Stage 3 investigator reports. **Introduced**
is the commit that first added the thing (`git log -S`, dated AEST). **Why**
is the reason the commit or the conversation gave at the time. That is a
*claim*: a reason recorded is not a reason verified.

**Authority** is one of four values (audit plan A2):
* **OD**: operator-directed;
* **AP/OA**: agent-proposed, operator-approved;
* **AO**: agent-only;
* **U**: unknown.

Evidence is `AE-nn` in `stage4/authority-evidence.md`. Two qualifiers are used:
* **batch**: approved as one line of a list;
* **on a wrong claim**: approved on an agent statement later shown to be
  false.

**Class** is the brief's A–G:
* **A**: original design;
* **B**: deliberate enhancement;
* **C**: necessary defensive fix;
* **D**: agent-generated complexity;
* **E**: behaviour change;
* **F**: duplicate or overlapping control;
* **G**: unknown.

Where the evidence supports two classes, both are given, primary first. Where
it supports neither, the entry says so rather than forcing one.

**Risk** is what the item puts at stake today: **H** (safety, or the
integrity of the strategy or the evidence), **M**, **L**.

**What changed since the plan was written.** The plan expected authority for
25 July – 2 September to be UNKNOWN wherever commit messages were silent. The
transcripts for that period exist (CE-020), so almost every item below has a
dated operator decision or a dated absence of one.

---

## 7.1 Purpose, authority and the AI

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 1 | **Autonomous execution** | OP: human or AI autonomous (§4.00); the build brief already planned "automated orders tied to tested rules and selectable methodology" (AE-01). → `execution_mode=auto`, paper only, per-strategy list; gate of 18 rails (§5.1) | `ab1ba97`, 26 Jul | close the gap with the reference app, which traded autonomously | **OD** (AE-05 item 3; AE-01; kept 12 Sep, AE-32) | **A** | L on paper |
| 2 | **Autonomy "tied to tested rules"** | OP: automated orders tied to tested rules (AE-01); "complete autonomy will not be implemented until I have the fullest confidence the mechanism works" (AE-13); "Define precisely what evidence must exist before the autonomy gate permits execution" (AE-20). → The scorecard exists, but `enforce_promotion_evidence` is off on paper (`config.py:599, 614-616`). Membership of `autonomous_strategies` is enough (`gate.py:230-258`). Enforced on live only | `ab1ba97` (opt-in), `9b9fa50` (live-binding), 31 Jul | enforcing on paper is circular: the evidence comes from paper trading | **AP/OA** (AE-06: informed and left; AE-12: M29 approved) | **B** on live; on paper the tie to tested rules is **absent**, a gap against AE-01 that is not classed as drift because the operator was told and accepted it | **M**: the 30-trade bar is unreachable at current throughput (9 of 30 at 7 Sep); see Stage 5 |
| 3 | **The AI's part in the recommendation** | OP: "recommended trades **using AI**"; AI takes part in forming the recommendation (§4.001). On 26 Jul the operator approved a plan with AI veto/shrink on entries (AE-05); on 4 Aug expected earnings "used by AI to deduce it's recommended action" (AE-15); on 21 Aug asked for an AI-formed buy/sell/hold "whilst following the rules of the current strategy" (AE-25). → **No AI output reaches any trade decision** (§5.3 #21). The AI verdict (M136) is an advisory panel | not built 26 Jul; advisory verdict `3274988`…`c1cc92c`, 22–24 Aug | "for *entries* it's a legitimate feature I chose not to build" (AE-05 item 4); the gate commit cites a model that vetoed protective **exits** | entry role: **AO** (departs from the approved plan; disclosed after the build; no response on record). Advisory verdict: **OD** in scope, design chosen by the operator from options that were all advisory (AE-25) | **E** | **H**: the largest gap against the governing baseline. *Answered 14 Sep (§8.5 Q1):* one recommendation, formed by the AI within the strategy and the rules, fulfilled by a human or by the gate. Neither mode acts on an AI recommendation today |
| 4 | **Operating on one strategy** | OP: "different trading strategies"; "the end game is to develop this across all 15 Strategies, with Swing being the first to be fully developed" (AE-05); "Swing method will be principal strategy" (AE-08). → `deployed_strategies=swing`; 14 others present and undeployed; M84/M85 designed, "not activated until I determine so" | `91aa726` (deploy from config), 31 Jul | the operator's sequencing | **OD** | **A**: swing-first is the operator's order, not drift | L |
| 5 | **No decision matrix or allocator between strategies** | P §10 (scoring matrix: regime fit 30%, risk-adjusted performance 20% …); the operator's pasted brief required it ("the orchestrator activates/deactivates strategies based on the current RegimeEvent and the decision matrix", AE-01). → Each strategy is gated alone, on regime mass (`strategies/engine.py:258-290`); no scoring anywhere | absent since `fa9ba47` | not recorded | **AO** (first build; AE-02 shows no discussion; logged as an error, CE-027) | **E** | M now; **H** once a second strategy is deployed |
| 6 | **Human sign-off path** | OP: human mode (§4.00); P §20.I. → Recommend mode; Blotter sign-off with confirmation; bulk sign-off | `fa9ba47`; bulk `9ec8a37`, 25 Jul | P; bulk at the operator's choice | **OD** (AE-04: bulk chosen against Claude's advice) | **A** | L |
| 7 | **Live trading** | OP: "complete autonomy will not be implemented until I have the fullest confidence" (AE-13); P: flag plus in-app confirmation. → Live cannot start at all: `live_trading_confirmed` is never passed and no setter exists (`runtime.py:336-350`, `ib_adapter.py:244-249`) | `fa9ba47` / `15b705b`, 12 Aug | paper-first | **AP/OA** (plan) | **A**, stricter than P: the confirmation dialog P specifies does not exist | L |

## 7.2 Market, data and regime

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 8 | **ASX through IBKR** | OP: US and ASX from C2; "start with ASX" for live (AE-08); "6-12 months testing in that market" (AE-20); P §15 IBKR. → ASX, IBKR paper, AUD | `f7bae43` 19 Aug; `fdd4851` 21 Aug (Alpaca era retired) | the operator's call | **OD** (AE-20, AE-21) | **B** | M (see 11) |
| 9 | **Prices from yfinance, 20-minute delay; IBKR for execution only** | P §20.D: IBKR ticks and bars. → yfinance 1-minute polls every 60 s; IBKR quote used only for the drift check (M168) | `709897a` 19 Aug | ASX data costs $25/month; delayed data judged enough | **OD** (AE-22) | **E** against P, deliberate | M: feeds item 25 (the forming bar) |
| 10 | **Validation pipeline not on the live path** | P §17, §20.D: dedupe, spikes, gaps, corporate-action adjustment, "never use [bad data] silently". → `data/validation.py` has no caller; vendor `auto_adjust` only | functions `fa9ba47`, never wired | not recorded | **AO** (first build; CE-027) | **E** | M |
| 11 | **Regime inputs are US series for an ASX book** | P §11.2 (inputs by concept); OP 26 Aug "are these drivers still relevant"; OP 25 Aug dialog "Both, equally weighted" (ASX and global). → VIXCLS, T10Y3M, BAA10Y drive the label; DGS3MO and DGS10 are fetched and ignored (§5.3 #9) | US era, `1687664` 30 Jul; ASX re-sourcing deferred (Milestone B rejected `4695761`, 31 Aug) | re-sourcing deferred until measured | **OD** to defer (outstanding item 6, frozen) | **E** | **H**: the label sets size (scalar) and eligibility |
| 12 | **HMM + rules + fusion + hysteresis; 7 labels; scalars** | P §11, §20.E. → As specified, less the optional ML ensemble; standardised matrix (M146) | `fa9ba47`; `6f965fc` 26 Aug | P | **AP/OA** (M146 dialog "1", 26 Aug) | **A** | M (hysteresis and slope counted per tick, §5.3 #10) |
| 13 | **Eligibility by probability mass ≥ 0.5** | P §10 (matrix); F: single label. → mass across suitable regimes (`strategies/engine.py:258-290`) | `9b9fa50` 31 Jul | a 0.02 label margin decided a session | **AP/OA** (AE-12 "Both") | **B** | L |
| 14 | **No regime on closed trades** | brief §10; the M37 intent ("record why a trade happened"). → 12 of 12 ledger rows blank; restored lots never carry it (§5.3 #16) | defect, from `f22e870` 1 Aug | — | **AO** (defect) | **E** (evidence) | M: regime analysis of results is impossible |

## 7.3 The swing strategy (line-by-line in §8)

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 15 | **Entry rule** | P §4.10: "pullbacks to support in an uptrend … with a clear invalidation level" (generic). S: touch the EMA20 with a rejection tail, wait for the daily close, buy the next open, weekly chart not falling. R: low within 2% of EMA20 in 3 days, trend gap ≥ 1%. → yesterday's close ≤ EMA20 and the running price > EMA20, in EMA20 > EMA50 (`swing.py:151-178`) | `fa9ba47`, unchanged | "paper §4.10" (docstring) | **AO**, contrary to the operator's 24 Jul choice to port "the swing trader methodology" (AE-02; CE-026) | **E**: the operator confirmed S is the swing specification (§8.5 Q2). Within P's outline | **H** (§8) |
| 16 | **Swing's regimes widened** | P Table 9.1: swing leads in Sideways. → Sideways, Bull, Low-Vol, Recovery (`swing.py:38-65`); size rises with them (scalar 1.0 against 0.7) | `44564c8` 30 Jul | swing eligible on 6.2% of sessions | **OD** (AE-10) | **E**, authorised | M |
| 17 | **Trend-break exit** | S: a close below EMA20 ends the swing (trail method B). R: EMA20 < EMA50. → EMA20 < EMA50, the bare cross, on the running bar (`swing.py:131-146`) | `ab1ba97` 26 Jul | port from R | **AP/OA** (AE-05 plan, Phase 2 "Exits"; the plan ported R's exit, not the specification's) | **E** against the specification (§8.5); was **B** | M |
| 18 | **Decides on the forming intraday bar** | S: "Wait for the daily candlestick to fully close". R: evaluated once at the close. OP: "the live path should run on daily bars" (AE-09). → Daily frame includes today's running, delayed price; evaluated every tick (`strategies/engine.py:391`, `bars.py:290`) | `373041a`/`3458715` 30 Jul | "restore the day's bar" on restart | forming-bar evaluation **AO** (not raised with the operator); daily bars themselves **OD** | **E** | **H**: a BUY can fire intraday on a day that closes back below EMA20 |
| 19 | **Trade management** | S: 50% off at 1R, stop to breakeven, 2–3 × ATR trail after 1R. → none; static bracket | never built | disclosed as skipped (AE-05 item 4); trailing stops measured and argued against on 7 Aug (AE-17) | **AO** (omission, disclosed); no operator direction either way | **E** | M-H |
| 20 | **Time stop, 30 trading days** | OP: "the original Swing Strategy was meant to span a 10 trading day cycle" (AE-17); "say 2 weeks" (AE-08); P: days to weeks. → 30 trading days (`signal_bridge.py:1284-1310`) | `8ca3488` 31 Jul | a third-party review's "e.g., 30"; "never derived from swing" (Claude, AE-17) | **AP/OA** (batch, AE-12); questioned by the operator 7 Aug; a longer stop declined 8 Aug (AE-17) | **E** against the specification's test condition of 10 working days (§8.5 Q2). *Corrected 14 Sep: the operator never chose 30 over 10* | M: with the cap binding it is the main way slots free up |

## 7.4 Sizing and portfolio risk

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 21 | **Per-trade risk 1%** | S 1–2%, R 1%, P 0.5–1% (swing) / 1–2% (engine). → 1% | `fa9ba47` | P, R | **AP/OA** (first build, approved inside milestone plans, AE-02); consistent with every layer | **A** | L |
| 22 | **Kelly on placeholders (0.55 / 1.5) until 20 closed trades** | P §6.3: fractional Kelly "blended with volatility targeting", W and R from rolling stats. → `min(Kelly, ATR cap)`, not a blend; measured only after 20 trades | placeholders `fa9ba47`; measured `ffc4ec9` 1 Aug | Kelly is violently sensitive to a noisy win rate | **AP/OA** (1 Aug "go ahead") | **E** (min, not blend) + **B** (measured inputs) | M: 20 trades are not reachable at present (control trap, Stage 5) |
| 23 | **Brokerage in the risk budget** | S: "subtract that $10 from your total Account Risk". OP: fees must not "grossly erode" profit (AE-08). → cost-to-risk rail refuses when the round trip exceeds 10% of risk (`engine.py:332-347`) | `4b02b40` 28 Jul | measured, not taste | **AP/OA** (AE-08) | **B**, a different mechanism for the same intent | L |
| 24 | **Aggregate risk-at-stop ≤ 5%** | S: "keep your total open risk under 5% to 6%". R: 5%. → governor D4, measured at the mark since M90 | `ab1ba97` 26 Jul; mark `a9aee6e` 14 Aug | R; M66 (entry prices understated a winning book) | **OD** (kept as the "conservative baseline", AE-16; kept again 12 Aug, AE-20); M90 **AP/OA** (14 Aug "do M66") | **A** | **H**: on 11 Sep it refused all 449 risk decisions, on 4 symbols, at 7.35–7.62% (`risk_decisions.csv`, measured 14 Sep); whether winners consume the budget is for Stage 5 |
| 25 | **Maximum 10 positions** | R 10. → governor D3, refuses at `>=` | `ab1ba97` | R | **AP/OA** (AE-05 plan); kept 12 Aug (AE-20) | **A** | M |
| 26 | **Single name 15%, trimming** | P: concentration caps; 25% at `fa9ba47`. → 15%, governor trims | `78fa556` 31 Jul | 1% over a ~5% stop sizes about 20% | **OD** (AE-12 dialog) | **B** | L |
| 27 | **Sector 30%, trimming** | R 30%; `fa9ba47` 40%. → 30%, governor trims (wired in fact only from item 44, 25 Aug) | `53f45ec` 1 Aug; wired `7ba8c30` 25 Aug | R | **OD** (AE-14) | **B**; the rail was inert from 1 to 25 Aug (defect) | L |
| 28 | **Correlated cluster 30% at ρ ≥ 0.70** | P §6.5. → governor D9; window 60 days | `39ab1f3` 1 Aug; 60-day `3072bed` 8 Aug | third-party review (AE-08), batch | **AP/OA** (AE-12 batch; window AE-17 dialog) | **B**; reported unreachable at 10 positions (Claude, 7 Aug; a claim, not re-measured) → possibly **D** | L |
| 29 | **Gap budget: 6% shock ≤ 5% of equity** | not in P or S. → governor D10 | `78fa556` 31 Jul | measured gap-through rate | **OD** (AE-12 dialog) | **B**; overlaps 24 (both limit the loss from a gap) → **F** | L |
| 30 | **Portfolio ES ≤ 3%; VaR reported** | P §6.2, §18.1. → gated at 3% ES; VaR not gated (as P says) | `fa9ba47` | P | **AP/OA** (first build, AE-02) | **A** | L |
| 31 | **Earnings: half size within 5 days** | not in P or S (S names earnings as a swing "primary driver"). → scalar 0.5; **the calendar is built for the US on an ASX book** (§5.3 #15) | `a3fb909` 7 Aug | second third-party review (AE-17) | **AP/OA** (AE-17 "Do as suggested") | **B**, with an **E** defect (wrong calendar) | M |
| 32 | **No leverage; cash reserve** | OP: "a hard coded rule" (AE-03). → engine rule, OMS checks, sign-off re-check | `52b0e4a` 25 Jul | the operator's requirement | **OD** (AE-03) | **A** | L |
| 33 | **Per-order cap, 10% of spendable cash** | OP (AE-26). → OMS trims (`oms.py:493-519`) | `77b7238` 24 Aug; spendable `9de4e09` 28 Aug | the operator's request | **OD** | **B** | L |
| 34 | **Day-P&L rails: halve at −2%, pause buys at −4%** | R Moderate. → gate rails 15 and 17. **The −4% pause sits beyond the kill switch's −3% daily-loss trip**, so it can act only if the equity poll lags a fall of more than 3% | `ab1ba97` | R | **AP/OA** (AE-05 plan) | **A** from R; the −4% rail is **F** (overlapped by the kill switch and in practice unreachable) | L |
| 35 | **Price-drift check 3%** | R. → gate rail 16 | `ab1ba97` | R | **AP/OA** | **A** | L |
| 36 | **De-lever sweep, off** | R ran it (evidence of 36.8% aggregate against a 5% cap). → built, off; unsafe with protective legs (9 Sep) | `ab1ba97` | "off by default because it sells" | **AO** default; the 9 Sep leg-resize direction was **OD** (dialog) | **G**: why it stays off is not recorded as an operator decision | L while off |

## 7.5 Kill switch, execution and protection

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 37 | **Kill switch: daily loss, drawdown, reconciliation, manual** | P §18.2. → as specified, plus IBKR reconnect exhaustion and HALT-class order errors | `fa9ba47`; HALT class `8316a12` 3 Sep | P; "Unknown → serious → halt" | **AP/OA** (first build, AE-02); HALT class **OD** (AE-28) | **A** / **C** | M: 10148 tripped it four times on 9 Sep (M172) |
| 38 | **No staleness trip** | P §18.2 and the pasted brief: staleness halts. → removed | `234e8d5` 31 Jul | every staleness trip was a false positive | **AP/OA** (AE-12 batch; reported after, operator acted) | **C** + **E**. The module docstring still claims a staleness trip (`kill_switch.py:1-4`), which is **D** (documentation drift) | M |
| 39 | **Reset needs no confirmation** | P: "cannot be suppressed". → one click (`risk_console.py:675-677`); tripping asks | `fada322` 25 Aug (confirm on trip only) | not recorded for reset | **U** | **G** | L-M |
| 40 | **Only sign-off transmits** | P §20.I. → `OMS.sign_off` is the only caller of `place_order` (`oms.py:1067`) | `fa9ba47` | P | **AP/OA** (first build, AE-02) | **A** | L |
| 41 | **Duplicate-transmission guard** | incident 24 Aug (CE-003). → `_transmitted` set | `f2d132cc` session, M139 24 Aug | 4× positions, twice | **OD** (fix) | **C** | L |
| 42 | **Quantity booked at transmission; fills absorbed in a 5-minute poll** | P §20.I: new → pending → transmitted → filled. → booked at sign-off, whatever status returns (`oms.py:1134-1137`); fill event at transmit | `fa9ba47` (mock era); change attempted and reverted 3 Sep | "sign-off cannot be the booking site" | **OD** to keep (AE-28 "Drop Task 3") | **E** + **C** (the rejection-reversal patch) | **H**: CE-005's phantom position; a rejected order stays in the ledger (§5.3 #17) |
| 43 | **Brackets at entry, GTC, OCA** | S: bracket at entry, GTC, stop-market. R: brackets. → STP and LMT children, OCA type 1 set explicitly since 7 Sep | `c59ad1a` 1 Aug; OCA type `a0f8144` 7 Sep | IBKR's implicit type 3 reduced rather than cancelled | **AP/OA** | **A** (L1) + **C** | L |
| 44 | **Protective re-arm** | not in P. → re-arm at startup and every 300 s | `8b249e8` 1 Aug | six unprotected positions | **OD** (AE-14 dialog) | **C** | L |
| 45 | **An exit releases its protective legs before the kill-switch check** | S: "Never move a stop lower"; a position always protected. → `oms.py:731` cancels, then `:745` refuses while tripped; the re-arm cannot transmit while tripped. **CE-017, open** | `e0c780d` 7 Sep | fix the A2M orphan; a failed exit "self-heals" through the re-arm | **AP/OA on a wrong claim** (AE-29). The same hazard had been fixed in the manual path on 1 Sep (AE-27) | **C** by intent, now **D**: a fix whose recovery depends on a mechanism the kill switch disables | **H** (live safety; IAG.AX unprotected about an hour on 9 Sep) |
| 46 | **Manual close from the Positions table** | OP: "manual trade within the Automatic environment" (AE-27). → sells only, full close, refuses while tripped | `ed129d9` 2 Sep | the operator's request | **OD** | **B**. It carries its own leg-cancel code, a second implementation with a different "gone" test (§5.3 #5) → **F** | M |
| 47 | **Resting-order scan (orphan legs)** | incidents 24 Aug, 5 Sep A2M. → detect, quarantine; cancel flag off | `cedb55e` 24 Aug | orphaned GTC legs on flat TNE | **OD** (AE-26 dialogs); flag default off: **OD** option | **C** | M: it cannot remedy an orphan (outstanding item 2) |
| 48 | **Reconciliation halts on mismatch; in-flight tolerance** | P §20.I. → quantity compare; working buys tolerated (M160) | `ab1ba97`; `f051c2f` 31 Aug | a partial fill read as divergence | **AP/OA** (AE-05 plan, Phase 3; M160 approved 31 Aug) | **A** + **C** | L |
| 49 | **Position and resting-order quarantines** | not in P. → two stores, both refuse entries | `24f9e33` 8 Aug; `e7f2d31` 24 Aug | the split test; orphans | **OD** (dialogs 8 Aug, 24 Aug) | **C**; two stores for similar jobs, kept apart deliberately so one cannot suppress a halt → not F | L |
| 50 | **Corporate actions (M39), shadow mode; inert on IBKR** | P §17: adjustment in validation. → shadow; IBKR has no announcements, so detection is unsupported | `dd1c4d5` 12 Aug; closed by decision 10 Sep | MNST loss; ASX splits rare | **OD** (AE-19; 19 Aug "Go with option 1"; 10 Sep closed) | **B**, inert | M: a split on a held ASX name is not seen before its ex-date |
| 51 | **ASX session model: opening-auction refusal, phases** | R: eligible session phases. → gate rails 7, 8, 11; auctions modelled | phases `ab1ba97`; auction `0266844` 9 Sep | market orders into the auction | **OD** (21 Aug dialog "Full auction model") | **B** | L. The phase fractions are inherited from US volume patterns (21 Aug dialog, not acted on) → **G** |
| 52 | **Buys need a print this session (never-ticked refusal)** | not in P. → gate rail 10 | `daf0e42` 31 Aug | absent is not the same as stale | **OD** (dialog "Both — gate and signal") | **C** | L |

## 7.6 AI, news and evidence

| # | Component / behaviour | Original intent → current | Introduced | Why (as recorded) | Authority | Class | Risk |
|---|---|---|---|---|---|---|---|
| 53 | **AI analysis screens** (Advisor, macro read, 7-regime matrix, report narrator) | OP: macro in the AI analysis (AE-05 item 3); "the AI analysis using all available information" (21 Aug); the matrix "outside of the authority of autonomy" (AE-30). → display, log and reports only | `ab1ba97` onward; M170 8 Sep | the operator's requests | **OD** | **A**/**B** | L |
| 54 | **News corroboration** | OP: "at least 2 independent sources" (AE-23). → setting, default 1 | `3b56937` 20 Aug; loosened 21 Aug | nothing was reaching the model | **OD** | **B** | L: a prompt-injection defence is weakened (item 11, open) |
| 55 | **LLM routing and privacy split** | P §16; OP "Make all the possible permissions a selectable option" (AE-04). → both slots local in the deployed config | `0e4e662` 25 Jul | P | **OD** | **A** | L |
| 56 | **Output guard and trade rationale not wired** | P §14.1, §20.J: the recommendation is validated against risk limits before display. → `get_trade_rationale` has no caller | `fa9ba47` | not recorded | **AO** (first build; CE-027) | **E**. No longer moot once the AI forms the recommendation (§8.5 Q1) | L now; **M** under Q1 |
| 57 | **Promotion scorecard** | OP: tested rules (AE-01); P §21. → five criteria; not filtered by market (§5.3 #19) | `ab1ba97` | "make 'fine tuned' falsifiable" | **AP/OA** (AE-05 plan, Phase 6) | **B**, with an **E** defect (no market filter) | M |
| 58 | **Ledger audit and repair scripts** | brief §11. → `audit_closed_trades` has no caller in the app; repairs by script (M175) | `f5c55e0` 7 Sep; `0db96ce` 11 Sep | the ledger disagreed with itself | **OD** (M175 runbook) | **C**; Stage 8 inventories the repaired records | M |
| 59 | **Report heading "Autonomy decisions blocked"** | — → counts every non-auto-signed row (§5.3 #20) | `ab1ba97` | — | **AO** | **D** (a misleading figure) | L |

---

## 7.7 What the map shows

1. **Most of the drift is not unauthorised in the narrow sense.** Of the 59
   items:
   * 26 are operator-directed;
   * 22 are agent-proposed and operator-approved;
   * 10 are agent-only;
   * 1 is unknown.

   (Counted from the Authority column, 14 Sep. Items 3 and 18 are counted as
   agent-only, their primary reading.)

   Most agent-proposed items were approved as part of a milestone plan or a
   list. The approval covered the plan, not the item's parameters. One (item 45) was approved on an
   agent claim that was wrong.
2. **The drift that matters most is agent-only, and it happened at the
   beginning.** The first build (items 5, 10, 15, 56) and the autonomy build
   (item 3) set the shape: no allocator, no validation, a swing rule written
   by the agent, and no AI in the decision. The operator never directed any of
   these, and nothing later revisited them. Everything the operator directed
   afterwards (markets, risk limits, protection, AI screens) was built around
   them.
3. **Item 3 is the finding that matters most against Checkpoint A.** On 26 July the
   operator approved a plan in which the AI could veto or shrink entries.
   Claude built the autonomy without it and said so afterwards. That choice,
   not any operator decision, is why "no AI takes part in forming any trade
   recommendation" (§4.001). When the operator asked again on 21 August, the
   options offered were all advisory, and the result was a panel. **The degree of AI
   involvement is still the operator's decision** (§8.4, question Q1).
4. **Safety controls were mostly added after real failures**: items 41, 42's
   patch, 43, 44, 47–49 and 52, each with an incident behind it. The
   exception, item 45, is the one that is now the live defect. It was a fix
   for an incident (A2M's orphaned legs) whose recovery assumption was never
   checked against the kill switch, although the same trap had been found and
   closed in the manual path six days earlier.
5. **Several limits came from third-party reviews** that the operator pasted
   (28 Jul, 7 Aug): the time stop (20), the correlation cluster (28) and the
   earnings halving (31). Claude modelled the reviews into the stack and the
   operator approved the stack. Item 20 is the case where the operator later
   named the result as drift from their own intent (AE-17).

6. **The operator's own diagnosis (Q3, 14 Sep):** "The original vision has
   been lost amongst multiple development branches arising during the build.
   These branches have been formed, sometimes from misinformation, or not
   anchoring back to the fundamentals." The map bears this out from the first
   day. The 24 July survey presented the operator's autonomous design as
   forbidden, relying on a rule Claude had added to the paper, and the first
   build did not implement the swing methodology it had been asked to port
   (CE-026). The 26 July build dropped an approved AI role (CE-021).

**Error-log cross-reference (Stage 4a).** Item 3 is recorded as CE-021, item
15 as CE-026, items 5, 10 and 56 as CE-027 (the operator's Q3 answer), item
45 as CE-017 (a later note adds the authority trail), item 38's stale
docstring as CE-022, and item 36's unrecorded default under "To establish".
