# QAT Design Recovery & Design Intent Audit, report section 4: Original Design Intent

**Stage 2 of the audit plan. DRAFT for Checkpoint A** (the operator reviews
Stages 2 and 3 before any drift is classified).
**Prepared:** 12 September 2026, evening. Read-only.
**Sources read, all under the operator's permission (plan Stage 0, item 9):**

| Ref | Source | Date | Author | What was read |
|---|---|---|---|---|
| **C1** | claude.ai chat "No-code stock trading bot with Make and Claude" (archive `claude-ai-export\conversations.json`) | 13 Jul | operator + Claude | in full |
| **C2** | claude.ai chat "AI-powered stock trading with Claude and Alpaca", 319 messages | 13–26 Jul | operator + Claude | **all 160 operator messages in full**; Claude's replies at the decision points only (messages 28, 90, 92, 94, 126, 176, 178, 186, 188, 271, 285, 287) |
| **C3** | claude.ai chat "Code review for stability and best practices" | 23 Jul | operator + Claude | in full |
| **C4** | claude.ai chat "Comprehensive investment strategies advisory paper…" | 24 Jul | operator + Claude | in full |
| **P** | `C:\ShareTrader\Investment_Strategy_Advisory_Paper.docx` ("the paper"), produced in C4 | 24 Jul | **Claude**, on the operator's brief | §1, §2.5, §4.10, §6, §9–§11, §14–§21 in full, including tables |
| **M** | `C:\ShareTrader\ShareTrader MkI.txt` | 15 Jul | an AI assistant's plan, kept by the operator | in full |
| **S** | `C:\ShareTrader\Swing Trader methodology.md` | 21 Jul | **the operator's own research** (C2 message 183: "I have been gathering research on a Short-Term trading methodology") | in full |
| **R** | `C:\ShareTrader\claude_market_dashboard.py` ("the reference app"), 4,814 lines, last modified 26 Jul 22:20 | 13–26 Jul | Claude, at the operator's direction in C2 | module-level settings and design comments (lines 92–304) only |
| **F** | repository commit `fa9ba47`, first commit | 25 Jul 07:13 | agent | README and file list |

Chat times are UTC as exported (AEST = UTC + 10).

**Not read, so any conclusion that would need them is marked UNKNOWN:** the
bulk of Claude's replies in C2; the reference app's logic beyond its settings
block; Claude Code sessions of 25 July – 2 September (deleted by retention);
and any conversation that produced the first commit `fa9ba47`.

---

## 4.00 ✅ Checkpoint A: the operator's statement of original intent (14 September 2026)

Verbatim:

> *"The original intent was to build a Share Trading App capable of making
> recommended trades using AI designed around different trading strategies.
> Decision making capability was to be either Human or AI autonomous whilst
> philosophy and strategies were informed by the attached."* (The attachment
> is the paper, `C:\ShareTrader\Investment_Strategy_Advisory_Paper.docx`.)

**How the audit applies it from here on** (the governing baseline for
sections 6–24):

| Element | Governing source | Consequence for §4.0's layers |
|---|---|---|
| Purpose: an app that makes **recommended trades using AI**, around **different trading strategies** | the operator's statement | the multi-strategy design is intent. Single-strategy operation is measured against it |
| Decision authority: **human, or AI autonomous**, selectable | the operator's statement | autonomy is **original intent**. The paper's "human approves every order / no auto-trade toggle" (L2) is **superseded** on this point |
| Philosophy and strategies | **the paper** (P) | P's philosophy (§2), strategy universe (§4), risk framework (§6, §18), regime adaptation (§9–§11) and decision matrix (§10) are the reference |
| Anything the statement and the paper do not settle | L1 evidence (chats, methodology, reference app), with attribution | as recorded in §4.1–§4.15 |

Sections 4.0–4.16 below stay as written: the evidence and the record of how
the layers differed. Where they call a question "a Checkpoint A decision",
this statement answers it, subject to the clarification in §4.001.

## 4.001 ✅ The AI's role in autonomous mode (operator, 14 September 2026)

Asked what "AI autonomous" means for the AI's role, the operator answered,
verbatim:

> *"Acting on its recommendation and complete the trade decision, subject to
> the embedded safety rails and in accordance with the selected strategy."*

**How the audit applies it:**

* In autonomous mode the system **acts on its own recommendation and
  completes the trade** without a human.
* It is bounded by two things: **the embedded safety rails** (the risk,
  portfolio, protection and kill-switch controls) and **the selected
  strategy**.
* Read with the purpose in §4.00, *"making recommended trades **using
  AI**"*: **the AI takes part in forming the recommendation** that the system
  then acts on.

**Effect on the baseline for sections 6–24:**

| Question | Baseline answer |
|---|---|
| Who may complete a trade? | a human (human mode) or the system itself (autonomous mode) |
| What bounds an autonomous trade? | the safety rails and the selected strategy. Neither the AI nor anything else may bypass them |
| Is the AI part of the recommendation? | **yes**, per "using AI". The measure is whether the current system uses AI in forming its trade recommendations |
| May the AI override a rail or the strategy? | **no**: "subject to the embedded safety rails and in accordance with the selected strategy" |

**Residual interpretation, recorded rather than assumed.** How large the
AI's part in the recommendation should be (originating it, confirming it,
or adjusting it within the strategy) is not specified. The reference app
gave it a confirm/veto role on entries (§4.4). Stage 4 compares the current
system against *"AI takes part in forming the recommendation"* and does not
pick a particular degree.

**The current system against this baseline, from §5 (facts; assessed in
Stage 4):** autonomous completion within rails and strategy **exists**
(§5.1, the gate and sign-off). **No AI output takes any part in forming a
trade recommendation.** Recommendations come from deterministic strategy
rules alone, and AI output reaches only panels, the log and reports (§5.3
item 21).

## 4.0 The finding that governs the rest of this section

**"The original design" is not one thing. The evidence shows three layers,
written by different authors, and they disagree on the most important
question: who may put an order in the market.**

| Layer | Author | Position on autonomy |
|---|---|---|
| **L1: operator-directed intent** (C1–C3, S, and R as built at the operator's direction) | the operator, through instructions to Claude | 13 Jul: AI decides. **13 Jul [27]: rejected** ("it makes the buying decision for me… I decide"). 15 Jul [91–93]: wants a "truly AI driven Share trading tool". **17 Jul [125]: autonomous, "no human intervention"**, as an experiment on paper. **23 Jul [286]: "any shift in strategy must always require human consent before applying."** |
| **L2: the paper and master prompt** (P) | **Claude**, answering the operator's brief of 24 Jul (C4) | "a human approves every live order"; "only a human sign-off action may release an order to the OMS. **There is no auto-trade toggle.**" (P §20.A) |
| **L3: the first implementation** (F) | an agent, building from L2 | README: "no component of this system places, modifies or cancels an order without an explicit human sign-off" |

**The operator's brief for the paper (C4 message 1) does not ask for human
approval of every order.** The constraint came from Claude, and Claude said
so on delivery: *"the technology design deliberately defaults to paper
trading and keeps a human sign-off on every order… That's baked into the spec
and the build prompt on purpose"* (C4 message 3). It was written a week after
the operator had directed autonomy in the reference app (C2 [125], 17 Jul),
which was then running autonomously (C2 [173], 21 Jul: "the first run of
autonomous trading").

**Consequence for the audit.** Measuring QAT against the paper alone would
classify its autonomy as drift from the original design. Measuring it against
the operator's direction would classify the *paper's* rule as the drift,
introduced by an agent. **Which layer governs is the operator's decision at
Checkpoint A.** This section records each layer separately and attributes
every point.

*Correction to the audit plan's early indication 1 (plan §4):* it said
autonomy "contradicts the founding spec". True of L2. But L2's rule was
agent-authored against an earlier operator direction, and the operator
reaffirmed autonomy on 12 September.

---

## 4.1 What QAT was intended to do

* **L1:** a tool that helps the operator trade shares profitably on paper,
  then possibly for real. It watches US and Australian markets in their own
  hours (C2 [73], [107]), gives "reliable and meaningful analysis and
  recommendations" with genuine AI value (C2 [93]), trades autonomously as an
  experiment (C2 [125]), and reports on its own performance daily and weekly
  (C2 [163], [177]).
* **L2:** "an AI-assisted, multi-strategy share-trading advisory and
  paper-trading system that detects the market regime, generates and
  backtests strategy signals, enforces strict risk limits, integrates with
  Interactive Brokers, and uses an LLM as an analyst that proposes and
  explains" (P §20.A). Operating model: **a core-satellite, regime-switched,
  multi-strategy programme**. A diversified multi-factor core (value,
  momentum, quality, low-volatility) runs with a trend sleeve, plus tactical
  satellites (CAN SLIM, **swing**/breakout, mean reversion, pairs) "sized down
  and switched on only when the detected regime favours them" (P §1).
* **L3:** the same mission statement word for word (F README, first
  paragraph).

## 4.2 What it was explicitly NOT intended to do

* **L2:** no autonomous live trading. No auto-trade toggle. No AI placing,
  modifying or cancelling orders. No AI relaxing a risk limit. No acting on
  instructions embedded in fetched data (P §14.2, §20 "Final safety
  reminder").
* **L1:** no unsupervised change of *strategy*: "any shift in strategy must
  always require human consent before applying" (C2 [286]). No borrowing: the
  cash floor was introduced after the first autonomous run took a USD 70,000
  margin loan (C2 [173]). The operator did **not** state that trades
  themselves need approval once autonomy was chosen. From 17 July the
  direction was the opposite.
* **Live trading:** L1 treats it as a later step. The chats show no
  instruction about it; M ends "Live Trading (only after thorough testing)".
  L2 gates it behind a config flag and in-app confirmation, and puts
  governance gates (Table 21.1, "≥ 3–6 months paper trading matching backtest")
  before any live capital.

## 4.3 The original trading strategy

**Two different answers, and they are not the same strategy.**

* **L2 (paper):** fifteen strategies, rotated by regime (P §9.2, §10). Swing
  trading is one *tactical satellite*, "best regimes: sideways-to-mild-trend",
  suited only to Sideways in the regime map (Table 9.1). Its mechanics are
  generic: "pullbacks to support in an uptrend, breakouts from consolidation";
  risk 0.5–1% per trade; reward-to-risk ≥ 2:1 (P §4.10). Multi-Factor is "the
  core" and "always active" (P §20.F).
* **L1 (the operator's own methodology, S, 21 Jul):** a swing strategy on
  liquid large caps (ASX 200 / S&P 500), daily charts:
  * **Trend:** EMA20 / EMA50 ribbon.
  * **Entries:** a pullback to the 20-day EMA with a bullish rejection candle,
    bought at the next open; a bull-flag breakout; a double-bottom breakout.
    Volume must confirm breakouts. **The weekly chart must not contradict the
    daily.** Wait for the candle to close.
  * **Sizing:** fixed fractional, 1–2% of capital, **brokerage fees deducted
    from the risk budget**; **total open risk under 5–6%**.
  * **Stop:** GTC, just below support or the 20-day EMA, placed as a bracket
    at entry. Stop-market preferred. **Never move a stop lower.**
  * **Target:** at least 1:2, **validated against historical resistance**;
    skip the trade if resistance blocks it.
  * **Trade management:** **sell 50% at 1R and move the stop to breakeven**;
    trail the remainder with a **2–3 × ATR(14) trailing stop**, activated
    only after 1R, or trail on the 20-day EMA.
* **L1 as built (R, "Moderate" defaults):** a daily EMA20/50 trend plus a
  pullback within 3 days, ATR(14) stop at **1.5 ×**, 2R target, 2% pullback
  band, 1% minimum trend gap (R lines 178–205). Plus a **mechanical 3% daily
  stop-loss** checked at each close (R line 166, C2 [177]) and a **Friday AI
  review** of each held position for peaks or declines, with sells decided
  autonomously (R lines 276–283, C2 [175–178]).
* **The operator also moved from day trading to swing/week trading**
  (C2 [175], 21 Jul), and QAT's live strategy is swing.

The first implementation's swing module (F) and its later history are Stage 3
and Stage 4 questions. **Whether swing was meant to trade alone, as it does
today, or as one satellite of a fifteen-strategy programme is a direct L1/L2
conflict.** The operator has only ever deployed swing. The paper never
envisaged swing alone.

## 4.4 The intended role of the AI / LLM

* **L1, as it evolved in C2:**
  * 13 Jul: the LLM decides BUY/SELL/HOLD (C1, C2 [1]).
  * 15 Jul: the operator accepted that the decision became deterministic,
    with the LLM narrating (C2 [89–90]). The operator then called that an "AI
    lame duck" (C2 [91]).
  * The agreed direction (C2 [92–94]) moved AI to *synthesis*: news, earnings
    proximity, peer relative strength, "a genuine second opinion that's
    allowed to disagree with the technical signal".
  * By 23 Jul the reference app gave the AI **real authority over new
    entries**: the "AI Involvement" slider, default *Moderate* = "disagree
    always blocks, tempers halves the size" (R lines 222–233). It gave the AI
    **no authority over protective exits**, "after watching the AI veto
    legitimate protective exits" (R line 224; the local model declined every
    SELL, C2 [176]).
  * Macro analysis: the AI may *propose* a risk-profile change, and only with
    two or more corroborating sources; a human must click to apply (C2
    [284–287], R lines 253–265).
* **L2:** "an analyst, not a trader". It may summarise, draft rationales, rank
  candidate signals, flag conflicts and surface concerns. It must not place,
  modify or cancel orders, relax a limit, access credentials, or be treated as
  a forecast (P §14.2, Table 14.1). The paper's "rank candidate signals" is the
  nearest it comes to decision influence. It gives the AI no blocking role.
* **Conflict:** L1 (the reference app) let the AI veto or shrink entries by
  default. L2 gives it no role in the decision. Which governs is for
  Checkpoint A.

## 4.5 The intended role of deterministic quantitative logic

**Consistent across layers.** Code computes signals, sizes and stops. The
reference app's rule: "use code for what code can reliably measure, AI for
genuine synthesis on top of it" (R lines 261–264). Protective exits are
"purely mechanical… no AI judgement involved" (R lines 162–165). L2: the risk
engine is "a deterministic pipeline" (P §18) and strategies "must not size
positions or place orders" (P §20.F).

## 4.6 The intended role of the risk engine

**Consistent in spirit, different in detail.**

* **L2:** "the mandatory checkpoint between a strategy signal and the broker.
  Nothing reaches the OMS without passing it" (P §18). Pipeline: sizing
  (fractional Kelly blended with volatility targeting, capped at 1–2%) → ATR
  stop (default 2.5 ×) → portfolio VaR/ES and correlation/concentration →
  regime scalar → gate. Limits: portfolio ES ≤ 3% NAV; daily loss ≤ 3%;
  drawdown ≤ 20% (P Table 18.1, §20.H).
* **L1 (R, "Moderate" defaults):** risk 1.0% per trade, position cap 20%,
  **aggregate risk-at-stop 5%**, sector cap 30%, **max 10 positions**; cash
  floor; daily P&L rails (halve new buys below −2%, pause below −4%);
  **drawdown circuit breaker 10%** from the running peak; price-sanity check
  3% (R lines 213–249, 290–292). The cash floor and stop-loss are
  "manual-only… non-negotiable rails, not appetite settings" (R lines 245–248,
  C2 [270]).
* **Where today's QAT limits come from (for Stage 4):** 1%, 5% aggregate,
  30% sector, 10 positions, −2%/−4% day rails and a 3% price drift match
  **L1**. 2.5 × ATR, 3% ES, 3% daily loss and 20% drawdown match **L2**.

## 4.7 The intended role of the OMS

* **L2:** order lifecycle new → pending sign-off → transmitted →
  filled/cancelled. "An order can only move past pending sign-off via an
  explicit human action." Guardrails: max size, rate limit, symbol
  allow-list, kill switch. Continuous reconciliation, halting on any mismatch
  (P §20.I).
* **L1:** orders placed by the app without a click once autonomy was on,
  behind rails: cash re-check per order (C3), price sanity, and brackets with
  resting broker-side stops (C2 [271] lists "resting broker-side stops" as
  built by 22 Jul).
* **L1 and L2 agree** on reconciliation, guardrails and audit logging. They
  differ only on who performs the sign-off.

## 4.8 The intended role of the broker interface

**Consistent.** IBKR through `ib_async` against a local IB Gateway/TWS, paper
port by default, live behind a flag plus confirmation, all behind an adapter
with a mock (P §15, §20.B/I). The operator chose IBKR for Australian paper
trading (C2 [107], [258]) after trying Moomoo, which offers no API paper
trading for ASX (C2 [238]). Alpaca served the US side in the reference app.

## 4.9 Who had authority to decide, and who to transmit

| Decision | L1 (operator direction) | L2 (paper) |
|---|---|---|
| Which trades to take | deterministic signal; AI may veto/halve entries (default on) | deterministic signal; AI advisory only |
| Whether to transmit | the app, autonomously (paper experiment) | a human, every order |
| Protective exits | mechanical only, never AI | risk engine / OMS; human sign-off still applies |
| Change of strategy or risk profile | **human consent, always** (C2 [286]) | human (all changes logged, P §21) |
| Risk limits | the operator sets them; cash floor and stop-loss manual-only | configurable; "must be set to the individual investor's tolerance" |

## 4.10 Original safety principles

**Common to L1 and L2:** paper first; a hard cash floor / no leverage (L1
after the 21 Jul margin loan; L2 via limits); mechanical protective exits; a
kill switch or circuit breaker; reconciliation with the broker; an audit log
of every decision; secrets never in code; AI never touches protective exits.
**L2 adds:** human sign-off on every order, VaR/ES limits, and
"human-in-the-loop and kill-switch controls are permanent features, not
training wheels" (P §21). **L1 adds:** strategy shifts need human consent;
sanity checks against stale prices; and "check per order, not once per cycle"
(C3, the diversity-cap bug).

## 4.11 Intended path from market data to order transmission

* **L2 (P §17, §18, §14, §20.C):** ingestion (IBKR ticks, historical bars,
  FRED) → validation (dedupe, gaps, spikes, timezone, **corporate-action
  adjustment**) → features, computed once centrally → event bus → regime
  engine (HMM + rules + optional ML → label, probabilities, exposure scalar) →
  **decision matrix activates strategies by regime** → strategy signals →
  risk engine (size, stop, VaR/ES, correlation, regime scalar, gate) → AI
  advisory (rationale, validated against limits) → **human sign-off** → OMS
  guardrails → broker → reconciliation → audit log.
* **L1 (R, as built):** yfinance data (daily bars for swing; 1-minute for
  display) → deterministic swing signal at the close → AI confirmation on
  entries (per the AI Involvement slider) → sizing and portfolio caps → price
  sanity and cash re-check → autonomous order with bracket → daily mechanical
  stop-loss sweep → Friday AI review of held positions → daily and weekly
  reports.

## 4.12 Human approval, autonomy and advice

* **Autonomous:** L1: entries, protective exits and weekly review sells, on
  paper. L2: nothing.
* **Advisory:** L1: deep research, macro-regime notes, risk-profile proposals.
  L2: all AI output.
* **Human approval:** L1: strategy and risk-profile changes, and the
  manual-only rails. L2: every order, and every change to a limit or mode.

## 4.13 Unknowns (UNKNOWN: INSUFFICIENT EVIDENCE)

1. **Who authorised the 26 July introduction of autonomy into QAT**
   (`ab1ba97`). Its commit cites "the original ShareTrader reference
   implementation", which is consistent with L1 [125], but the session that
   made it no longer exists. (The operator's decision of 12 September is
   separate authority for keeping it.)
2. **Whether the operator reviewed and accepted the paper's
   human-approval rule** after receiving the paper on 24 July. No message in
   C2–C4 addresses it.
3. **How QAT's first commit was produced from the paper**: which session,
   and with what instructions. The first commit arrived with M1–M9 built
   (25 Jul 07:13). C2 [191] (21 Jul) asks whether Claude can build "a Windows
   based Share Trading App using an existing Claude chat history and claude
   skill", but no record of that build survives.
4. **Whether swing was meant to trade alone.** L2 says no. The operator's
   deployments say yes. No explicit statement was found.
5. **Whether the operator intended AI to influence entries in QAT** as it did
   in the reference app. There is no statement either way after 24 July.
6. **The "learning" intent.** C2 [125] asks the app to "learn from its
   decision making and adjust its strategy on the go". The reply (C2 [126])
   and R (lines 152–154) reframe this as fixed rules scaling size with
   performance. Whether the operator accepted that reframing is not recorded.

## 4.14 The paper against the first implementation (L2 → L3)

`fa9ba47`, 25 Jul 07:13: 90 source modules (4,732 lines), 61 test files. Its
README mission is §20.A of the paper word for word. What it built against
the master prompt:

| Master prompt requirement | In `fa9ba47`? | Evidence |
|---|---|---|
| Three layers, event bus, engines behind interfaces with mocks | **Yes** | file list; `domain/bus.py`, `data/broker/mock_broker.py` |
| 15 strategies behind one interface | **Yes** | `domain/strategies/` (15 modules) |
| **Decision matrix** activating strategies by regime (P §10, §20.F) | **No.** Each strategy is gated on whether the single current regime label is in its `suitable_regimes()` | `strategies/engine.py:108` @`fa9ba47`; no "decision matrix" or scoring code anywhere |
| Multi-Factor always active | **Yes** | `strategies/multi_factor.py:3` @`fa9ba47` |
| Regime engine: HMM + rules + **optional ML ensemble**, fusion, hysteresis, 7 labels | **HMM (4 states) + rules + fusion + hysteresis; no ML ensemble** | `regime_engine/` @`fa9ba47`; no ensemble code |
| Regime features: log returns, realised vol, VIX, curve slope, credit spread, breadth | **Yes**, the same six as today | `feature_matrix.py` @`fa9ba47` |
| Exposure scalars per regime | **Yes**, the same table as today (bull 1.0 … recession 0.3) | `fusion.py` @`fa9ba47` |
| Sizing: fractional Kelly + volatility target, **W and R from the strategy's rolling stats** | **Kelly + vol target, but W and R fixed at placeholder defaults (0.55, 1.5)**. The code itself says a rolling tracker is "not built anywhere in this codebase yet" | `oms/signal_bridge.py` docstring and `__init__` @`fa9ba47` |
| ATR stop 2.5 × | **Yes** | `strategies/swing.py` @`fa9ba47` |
| Portfolio VaR (95/99) and ES (97.5) with limits | **Yes** | `risk_engine/portfolio_risk.py:1-2` @`fa9ba47` |
| Kill switch (daily loss, drawdown, staleness, reconciliation, manual) | **Yes** | `risk_engine/kill_switch.py`; tests |
| OMS: pending sign-off; only a human sign-off transmits; guardrails (max size, allow-list, kill switch) | **Yes**. `max_order_notional = 50,000` hard-coded; symbol allow-list | `oms/oms.py:4-8, 33-34, 78-80` @`fa9ba47` |
| Corporate-action adjustment in validation | **A function exists** (`adjust_for_corporate_actions`). Whether anything called it is a Stage 3 question | `data/validation.py:105` @`fa9ba47` |
| AI advisory: router, guards, schema, prompts; no broker access | **Yes** | `domain/ai_advisory/` @`fa9ba47` |
| Safety tests (i)–(v) | **Yes**: `tests/safety/` (no order without sign-off, default paper, AI breach blocked); injection test in `test_prompts.py` | test names @`fa9ba47` |
| TimescaleDB / Parquet storage | **Stubs** (`data/store/db.py` 17 lines, `parquet.py` 42 lines) | file sizes @`fa9ba47` |
| Real market data | **No.** The README at `fa9ba47` says the screens run "on synthetic/mock data by default" | `git show fa9ba47:README.md` |

**So the first implementation already departed from the paper** in four
places before any live use: no decision matrix, no ML ensemble, placeholder
Kelly inputs, and synthetic data. The first three were disclosed in its own
code. From the first commit, the "multi-strategy regime-switched programme"
existed as fifteen independently gated strategies with no allocator between
them.

## 4.15 The swing strategy across the layers

| Element | L1: operator methodology (S) | L1: reference app as built (R `evaluate_swing_strategy`, lines 1000–1092) | L3: QAT first commit (`fa9ba47`) | QAT today |
|---|---|---|---|---|
| Timeframe | daily | daily, evaluated once at the close | daily bars | same as `fa9ba47` |
| Trend | EMA20/50 ribbon | EMA20 > EMA50; **entry needs a gap ≥ 1%** (Moderate) | EMA20 > EMA50, **no minimum gap** | same entry rule as `fa9ba47` (`swing.py:151-159`) |
| Pullback | touches the 20-day EMA with a **bullish rejection tail**; buy at the **next open** | **any daily low in the last 3 days** within 2% above EMA20 | **yesterday's close ≤ EMA20** | same |
| Confirmation | the daily candle closes; volume on breakouts; **weekly chart not falling** | close > previous close **and** close > EMA20 | close > EMA20 | same |
| Other entries | bull flag, double bottom | none | none | none |
| Stop | just below support / EMA20, GTC bracket | 1.5 × ATR(14) (Moderate) | 2.5 × ATR(14) (paper default) | 2.5 × ATR(14) |
| Target | ≥ 2R, **checked against resistance** | 2R | 2R | 2R |
| Trade management | **50% off at 1R, stop to breakeven, 2–3 × ATR trailing stop after 1R** | none; 3% daily stop-loss sweep; Friday AI review | none | none |
| Trend-break exit | a close below the 20-day EMA (trail method B) | EMA20 < EMA50 (bare cross) | none | EMA20 < EMA50 (bare cross, added 26 Jul, `swing.py:131-149`) |
| Regimes | not stated | none (macro warns only) | Sideways only (paper) | Sideways, Bull, Low-Vol, Recovery (widened 30 Jul, recorded in the code as an operator decision, `swing.py:38-65`) |

**QAT's swing entry is the first commit's rule, unchanged.** That rule is
the agent's own instantiation of the paper's generic §4.10 text. It is
neither the operator's methodology nor the reference app's rule, which ran
autonomously until 26 July. Whether that substitution was intended is
UNKNOWN (the building session no longer exists).

## 4.16 Stage 2 status

Complete for Checkpoint A, with the unknowns in §4.13. Not read, and not
needed for Checkpoint A: the reference app beyond its settings and swing
function; the bulk of Claude's replies in C2.
