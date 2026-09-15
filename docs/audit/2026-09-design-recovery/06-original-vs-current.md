# QAT Design Recovery & Design Intent Audit, R6: Original vs Current Comparison

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §5–§6 (the plan's retired "Stage 4"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 14 September 2026. Read-only.

This section sets the governing baseline (§4.00, §4.001) against the current
system (§5), question by question from the brief. §7 is the item-level map
behind it, and §8 takes the strategy line by line.

## 6.0 The §4.13 unknowns, re-examined

§4.13 listed six questions as UNKNOWN because "the session that made it no
longer exists". That premise was wrong (CE-020): the transcripts cover every
day from 24 July. Re-examined against them:

| §4.13 # | Question | Now | Evidence |
|---|---|---|---|
| 1 | Who authorised autonomy (`ab1ba97`, 26 Jul)? | **The operator.** "develop the autonomy but make it an option in the settings tab to either auto trade or the app making recommendations" | AE-05 |
| 2 | Did the operator accept the paper's human-approval rule? | **As the starting state, not as permanent.** The operator pasted the master prompt with one edit: "…while a human approves every live order, **with a future function to allow automated orders tied to tested rules and selectable methodology**" | AE-01 |
| 3 | How was the first commit produced? | In session `64d334fe` (24–25 Jul). The operator pasted the paper's §20 master prompt (amended as above) with the paper attached, and chose "Fresh build, but mine ShareTrader for reusable logic" and "a detailed implementation plan first". Each milestone M1–M9 was then plan, approval ("yes"), build. The swing rule, the missing decision matrix and the unwired validation were never discussed | AE-01, AE-02 |
| 4 | Was swing meant to trade alone? | **First, not alone.** "The end game is to develop this across all 15 Strategies, with Swing being the first to be fully developed"; "Swing method will be principal strategy" | AE-05, AE-08 |
| 5 | Did the operator intend the AI to influence entries in QAT? | **Yes, it was approved.** The 26 July plan included the AI veto/shrink on entries, and the operator approved it. Claude then built autonomy without it and reported that afterwards. On 21 August the operator asked for an AI-formed buy/sell/hold recommendation "whilst following the rules of the current strategy". It was built as an advisory panel. How far the AI should go is still open | AE-05, AE-25; §8.4 Q1 |
| 6 | What did "learn from its decision making" mean? | **Evidence and backtesting.** "backtesting is key to validating decisions made and to be made so an important piece to the learning element I ultimately want to rely upon". Measured Kelly inputs (M35) are the only live form of learning; they switch on at 20 closed trades | AE-13; map #22 |

## 6.1 Question by question

| Brief §3 question | Original intent (baseline) | Current (§5) | Verdict |
|---|---|---|---|
| What was QAT meant to do? | Make recommended trades **using AI**, around **different strategies**; decisions human or AI-autonomous (OP §4.00) | Trades one deterministic strategy autonomously on paper; AI output reaches screens and reports only | **Drifted on two of three terms**: AI (map #3) and multiple strategies (#4 by the operator's sequencing, #5 no allocator). Autonomy is intact (#1) |
| What was it NOT meant to do? | No live autonomy until the operator has "the fullest confidence" (AE-13); no leverage (AE-03); no unsupervised strategy change (C2 [286]); no AI on protective exits (R; AE-05 plan) | Live cannot start at all (#7); the no-leverage rule is present (#32); strategies change only by configuration; no AI anywhere near an order | **Intact.** Stricter than intended on live |
| The original trading strategy | Swing first (AE-05, AE-08) within the paper's framework; the operator's methodology for detail (S) | Swing, but the first commit's rule, not S (§8) | **Recognisable, not the operator's method** (§8.3) |
| The role of AI | Takes part in forming the recommendation (§4.001); the approved plan had an entry veto (AE-05) | None in any decision (§5.3 #21) | **Largest gap** (#3); its degree is Q1 |
| The role of deterministic logic | Code computes signals, sizes and stops; AI adds synthesis on top (R, P §18) | Everything is deterministic | **Intact**, and nothing is layered on top |
| The role of the risk engine | Mandatory checkpoint; Kelly blended with vol targeting, ATR stops, VaR/ES and concentration, regime scalar (P §18) | Mandatory checkpoint; Kelly-min rather than blend, on placeholders; plus a governor the paper never had (L1 limits); cost rail; earnings scalar | **Intact in role, grown in content** (#21–#36) |
| The role of the OMS | Lifecycle new → pending → transmitted → filled; guardrails; reconciliation halts (P §20.I) | The same lifecycle, but quantity booked at transmission (#42); leg release before the kill-switch check (#45, CE-017) | **Intact in role; two defects in behaviour** |
| The role of the broker interface | IBKR behind an adapter with a mock (P §15, §20.B) | IBKR execution only; prices from yfinance (#9) | **Intact**, with prices re-sourced by the operator's choice |
| Who decides | Human or the system (§4.00); AI takes part (§4.001) | The strategy rule decides; the rails trim or refuse; no AI | **Drifted** on the AI term |
| Who transmits | Human, or the system in autonomous mode, subject to rails and strategy (§4.001) | The autonomy gate signs off on paper; the Blotter for humans | **Intact** |
| Safety principles | Paper first; no leverage; mechanical protective exits; kill switch; reconciliation; an audit trail (§4.10) | All present, plus many added after incidents (§7.7 point 4). Two principles are weakened: a position can lose its broker stop while the switch is tripped (#45), and the kill switch no longer trips on staleness (#38) | **Intact, with one live exception** (CE-017) |
| Path from data to order | Ingestion → validation → features → regime → **decision matrix** → strategy → risk → AI rationale → sign-off → OMS → broker (P §17–§20) | Ingestion → (no validation) → per-engine features → regime → per-strategy mass gate → swing → bridge → risk engine and governor → OMS → autonomy gate → broker (§5.1) | **Drifted**: validation, the matrix and the AI step are absent (#10, #5, #3) |
| Human approval | Available as a mode (§4.00) | Recommend mode and Blotter | **Intact** |
| What is autonomous | Acting on the recommendation within the rails and strategy (§4.001) | Entries and exits for swing on paper; protective re-arm | **Intact** |
| What stays advisory | AI analysis (macro and matrix explicitly, AE-30) | All AI output | **Intact**, and wider than intended if Q1 is (a) or (b) |

## 6.2 In short

**What holds:**
* the autonomy the operator wanted;
* the human alternative;
* the paper-first and no-leverage rails;
* a deterministic risk checkpoint in front of every order;
* reconciliation and a kill switch.

**What does not:**
* the AI takes no part in any trade decision;
* only one strategy is built out, with no way to choose between strategies
  if more are switched on;
* the swing strategy is the first build's own rule, not the operator's
  method.

**The largest difference came from Claude, not the operator.** The first
build and the autonomy build made these choices, and later work built on
them without revisiting them (§7.7).
