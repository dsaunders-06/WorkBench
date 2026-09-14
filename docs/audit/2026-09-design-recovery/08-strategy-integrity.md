# QAT Design Recovery & Design Intent Audit, report section 8: Strategy Integrity Assessment

**Stage 4 of the audit plan. DRAFT for Checkpoint B.**
**Prepared:** 14 September 2026. Read-only.

The brief's most important question is: **"Is QAT still trading the strategy
I originally designed?"**

## 8.0 The two references, and why both are needed

* **P, the paper (§4.10 and the tables it points to).** Checkpoint A made it
  the governing source for "philosophy and strategies" (report §4.00). Its
  swing text is generic: "trade defined patterns (pullbacks to support in an
  uptrend, breakouts from consolidation) with a clear invalidation level";
  risk 0.5–1% of equity; reward-to-risk ≥ 2:1; holding "days–weeks"; best
  regime "sideways-to-mild-trend".
* **S, the operator's methodology** (`C:\ShareTrader\Swing Trader methodology.md`,
  21 Jul, read in full 14 Sep), together with the operator's own statements
  about swing: "hold period of say 2 weeks" (AE-08); "the original Swing
  Strategy was meant to span a 10 trading day cycle" (AE-17). S is specific
  where P is generic.

P does not contradict S. It is less detailed. A difference from S is
therefore not automatically drift from the governing baseline. Whether S is
*the* specification is the operator's question (Q2, §8.4). The table assesses
both.

> ✅ **Answered 14 Sep (§8.5): S is the specification for swing.** Every
> "vs S" difference below is drift from the operator's design.

**Assessment codes** (brief §6):
1. preserves the original strategy;
2. restricts it;
3. changes it;
4. prevents it accumulating evidence;
5. necessary for safety;
6. accidental or unclear.

**History of the rule itself.** `swing.py` has had four commits:
* `fa9ba47` (25 Jul): the entry rule, stop and target, unchanged since;
* `ab1ba97` (26 Jul): the trend-break exit;
* `44564c8` (30 Jul): regimes widened;
* `8dda319` (15 Aug): a read-only helper.

**So the differences from S are not drift over time. They were there from
the first commit.**

## 8.1 Line by line

| Element | P (paper) | S / operator | QAT today (evidence) | Assessment | Authority (map #) |
|---|---|---|---|---|---|
| **Entry conditions** | a defined pattern with a clear invalidation level | three entries: EMA20 pullback with rejection tail; bull flag; double bottom | one: the EMA20 pullback-and-reclaim (`swing.py:151-178`). No bull flag, no double bottom | vs P **1**; vs S **3** (two of three entries absent) | AO (15) |
| **Trend definition** | "in an uptrend" | EMA20/50 ribbon on daily charts; "the weekly chart must not be crashing" | EMA20 > EMA50 on daily bars; **no weekly check**; no minimum gap (R had ≥ 1%) | vs P **1**; vs S **3** (weekly filter absent) | AO (15) |
| **Pullback definition** | "pullbacks to support" | the day's candle touches the EMA20 and shows a bullish rejection tail | yesterday's close ≤ EMA20 (`swing.py:154-156`). A close *below* the line counts; a touch with a close above does not | vs P **1**; vs S **3** | AO (15) |
| **Reclaim condition** | — | wait for the daily candle to close; buy at the next open | the *running* price > EMA20 (`swing.py:157-159`), on a daily frame that includes today's forming, 20-minute-delayed bar (`strategies/engine.py:391`; `bars.py:290`). Evaluated every tick | vs S **3**; also **6**: the forming-bar evaluation was never put to the operator | AO (18) |
| **Volume confirmation** | — | breakouts need high volume | none. Swing reads no volume (inv-1 C); bar volume double-counts yfinance repeats (`bars.py:244`) | vs S **3** (the rule applies to the two entries QAT does not have) | AO (15) |
| **Regime eligibility** | Table 9.1: swing leads in **Sideways** | not stated. The operator's 12 Aug strategy asks "whether Sideways should actually qualify a trend-following strategy" (AE-20) | Sideways, Bull, Low-Vol, Recovery (`swing.py:38-65`) | vs P **3**, authorised; also raises size (scalar 1.0 against 0.7) | OD (16) |
| **Regime probability threshold** | decision matrix (§10) | — | ≥ 0.5 of probability mass in suitable regimes (`strategies/engine.py:258-290`) | **1**. Its commit reports that it hardly changes eligibility (57.3% → 58.1%, `9b9fa50`). That is a claim, not re-measured by the audit | AP/OA (13) |
| **Regime inputs** | concepts (VIX, curve, credit, breadth) | — | US series for an ASX book (§5.3 #9) | **6** for an ASX book: the label that sets eligibility and size reads another market | OD to defer (11) |
| **Session gate** | — | buy at the next **open** | no signals outside the session; autonomous buys blocked in the opening auction and outside Morning Trend, Afternoon and Closing (gate rails 7, 8, 11) | vs S **3**: the next-open entry S prescribes is excluded by design (the phase list comes from R); **5** for the auction | AP/OA, OD (51) |
| **Data staleness** | halt on staleness | — | a stale symbol is excluded from evaluation, exits included (§5.3 #8); buys need a print this session | **5**; restricts (**2**) when a symbol's exits are also skipped | AP/OA, OD (38, 52) |
| **Position sizing** | 0.5–1% risk, fractional Kelly blended with vol targeting | fixed-fractional 1–2%, fees deducted | `min(Kelly on 0.55/1.5, 1% ÷ 2.5 ATR)`, then trims: regime scalar, earnings 0.5, no-leverage, governor (15% name, 30% sector, cluster, gap), 10%-of-spendable per-order cap (`oms.py:493-519`) | **1** in principle. Several trims can bind before the 1% budget, so the risk actually taken per trade can be well under 1% (**2**). By how much is measured in Stage 5 | mixed (21–33) |
| **Stop calculation** | ATR-based, 2–3 × (2.5 × default, §20.H) | "just below the key support line" or "underneath the 20-day EMA"; chart-based | 2.5 × ATR(14) below the running price (`swing.py:164`); a bracket at the broker | vs P **1**; vs S **3** (volatility-based, not chart-based) | AO (15) |
| **Target calculation** | reward-to-risk ≥ 2:1 | at least 1:2, **validated against historical resistance**; skip the trade if resistance blocks it | a fixed 2R limit order; no resistance check | vs P **1**; vs S **3** | AO (15) |
| **Trade management** | — | 50% off at 1R, stop to breakeven, 2–3 × ATR trail after 1R (or trail on the EMA20 close) | none. Static bracket (AE-05 item 4 lists it as skipped) | vs S **3** | AO (19) |
| **Exit logic** | clear invalidation level | a close below the EMA20 ends the swing; sell at resistance | (a) the resting stop; (b) the 2R target; (c) EMA20 < EMA50 on the running bar (`swing.py:131-146`); (d) the 30-day time stop; (e) manual close | vs S **3** (a slower, different invalidation) | AP/OA (17) |
| **Holding period / minimum hold** | days–weeks | "a few days to several weeks"; operator: "say 2 weeks" | signal exits blocked for 10 trading days unless 0.5R down (`signal_bridge.py:1352-1398`); protective exits never blocked | **1** against the operator's 2-week hold. It delays S's trend-break exit inside the window | OD (28 Jul dialog, AE-08) |
| **Time stop** | days–weeks | operator: a 10-trading-day cycle (AE-17) | 30 trading days (`signal_bridge.py:1284-1310`), from a third-party review | **3** against the stated cycle. The operator was told how it arose (AE-17). *Corrected 14 Sep (§8.5):* the operator declined a longer stop but never chose 30 over 10; the specification's test condition is 10 working days | AP/OA (20) |
| **Earnings treatment** | — | earnings are a swing "primary driver" | half size within 5 trading days; **calendar built for the US** on an ASX book (`runtime.py:402`, `earnings.py:107`) | **2**, and **6** (the calendar) | AP/OA (31) |
| **Gap treatment** | swing is weakest in "violent gap-driven markets" | prefers stop-market ("guarantees you get out") and warns against stop-limit through gaps | stop-market legs; a gap budget of 5% of equity at a 6% shock (governor D10) | **5**; restricts (**2**) only near the budget | OD (29) |
| **Portfolio constraints** | ES ≤ 3%; concentration caps | "keep your total open risk under 5% to 6%" | 10 positions; aggregate risk-at-stop ≤ 5% at the mark; ES 3% | **1** (S's rule, R's numbers). But the cap is binding on every entry. On 11 Sep it refused all 449 decisions, on 4 symbols, at 7.35–7.62% (`risk_decisions.csv`), so **4** | OD, AP/OA (24, 25, 30) |
| **Correlation constraints** | size correlated positions jointly | — | cluster ≤ 30% at ρ ≥ 0.70, 60-day window | **1** in intent. Claude reported on 7 Aug that it cannot bind at 10 positions (AE-17); that is a claim, not re-measured by the audit | AP/OA (28) |
| **Sector constraints** | single-sector caps | — | 30%, trimming (R's figure) | **2**, mild | OD (27) |
| **Cost constraints** | costs net against edge | deduct fees from the risk budget | cost-to-risk ≤ 10%; commission modelled on paper (ASX Fixed, 8.8 bp, $6.60 floor) | **1** (a different mechanism for S's intent) | AP/OA (23) |
| **Order type** | — | limit entry; stop-market GTC bracket at entry | market parent, GTC; STP and LMT children, OCA type 1 (`ib_translate.py:194-280`) | **3** (market, not limit, entry); **5** for the bracket | AP/OA (43) |
| **Autonomous eligibility** | (superseded: human sign-off) | operator: autonomy "tied to tested rules and selectable methodology" (AE-01) | swing is on `autonomous_strategies`; the gate's 18 rails; no evidence test on paper | **1** for autonomy itself; the "tested rules" tie is absent on paper, by accepted choice (AE-06) | OD, AP/OA (1, 2) |
| **Promotion requirements** | governance gates before live (Table 21.1) | — | 30 trades, avg R ≥ 0.20, win ≥ 40%, worst ≤ 3 × avg win; not market-filtered (§5.3 #19); enforced on live only | **1** as a design. Unreachable while item 24 blocks entries (**4**, via the cap); Stage 5 traces the chain | AP/OA (57) |

## 8.2 What stops swing accumulating evidence

These are facts for Stage 5, which traces the causal chain.
* On 11 September, the last session that evaluated entries, the aggregate cap
  refused every one of the day's 449 risk decisions. Those were repeated
  evaluations of 4 candidate symbols, not 449 separate opportunities, at
  7.35–7.62% against 5.00% (`risk_decisions.csv`, measured 14 Sep).
* The book is nine positions.
* Twelve ledger rows (8 positions) have closed since the Alpaca-era records
  were retired on 21 August.
* The sizer needs 20 closed trades per strategy and market before it uses
  measured inputs; the promotion gate needs 30.

At current throughput neither threshold is reached. Kelly stays on its
placeholders, and the promotion bar stays unscored. The brief's §13 example
chain (restriction → fewer entries → too few closed trades → Kelly stays at
default → no promotion evidence) is what this looks like. Report §4's early
indication 3 names the likely mechanism: risk measured at the mark against
fixed stops, so winners consume the budget. Stage 5 will test it.

## 8.3 The answer

**Against the paper (the governing baseline for strategies):** QAT trades
**one** strategy that fits the paper's generic swing description:
* a pullback in an uptrend;
* 1% risk;
* an ATR stop;
* at least 2:1 reward-to-risk;
* holds of days to weeks.

Its regimes were widened beyond the paper's Sideways, by the operator's
decision. It does **not** trade the paper's programme: fifteen
regime-switched strategies, a decision matrix between them, and swing as one
satellite (map items 4, 5).

**Against the operator's own swing (the methodology, and the operator's
statements):** **No, and it never has.** The rule in `swing.py` is the one
the agent wrote in the first commit, from the paper's generic text. The
operator's method was never implemented:
* the candle-close confirmation;
* the rejection tail;
* the weekly-chart filter;
* volume;
* the resistance check on the target;
* the other two entries;
* the trade management (half off at 1R, breakeven, trailing).

QAT also decides on the forming intraday bar, which the methodology says
never to do ("Never guess. Wait for the daily candlestick to fully close").
No operator direction removed any of these. The operator raised two related
points themselves on 7 August: the 30-day hold against a 10-day cycle, and a
sell decision that "needs strengthening" (AE-17).

**In one sentence:** QAT is recognisably a swing-pullback strategy, and it is
the one the paper describes in outline. It is not the method the operator
documented, and the gap dates from the first commit, not from later
agent changes.

**What changed since, and who changed it.** After the first commit, swing
itself changed three ways:
* exits were added (agent-proposed, approved in a plan);
* regimes were widened (operator);
* holding rules came from a third-party review and the operator (minimum
  hold 10 days, time stop 30).

The larger changes to *which swing trades happen* came from outside the
strategy: the aggregate cap, the position limit, the per-order cap and the
session phases (§8.1). Those are Stage 5's subject.

## 8.4 Questions for the operator

These cannot be settled from the evidence. Each changes how an item above is
classified.

* **Q1. How large should the AI's part in the recommendation be?**
  Checkpoint A says the AI takes part (§4.001) and left the degree open. The
  record shows the operator:
  * approved AI veto/shrink on entries (26 Jul, AE-05);
  * expected AI to use earnings in forming a recommendation (4 Aug, AE-15);
  * asked for an AI-formed buy/sell/hold "whilst following the rules of the
    current strategy" (21 Aug, AE-25);
  * kept the macro matrix and the LLM out of monetary authority (8 Sep,
    AE-30).

  None of these says whether the 21 August recommendation should drive
  autonomous trades. The options are:
  * (a) the AI may veto or shrink entries, as approved on 26 July;
  * (b) an AI-formed recommendation, within the strategy's rules and the
    rails, is what autonomy acts on;
  * (c) advisory only, as now.

  Map item 3 is **E** under (a) or (b), and becomes **A** under (c).
* **Q2. Is `Swing Trader methodology.md` the specification for QAT's swing,
  or research that the paper's generic §4.10 governs?** If it is the
  specification, §8.1's "vs S" differences are drift from the operator's
  design, all agent-only. If not, they are unimplemented options.
* **Q3. How should the first build's departures from the brief the operator
  pasted be recorded?** These are: no decision matrix (item 5), validation not
  wired (item 10) and the output guard not wired (item 56). The brief said
  "Ask when ambiguous", and none was raised. Should they be Claude errors in
  the log, or undiscussed agent choices?

## 8.5 ✅ The operator's answers (14 September 2026), and what they change

Verbatim:

> **Q1.** "The recommendations made by the AI should be no different whether
> in Autonomous mode or Manual mode. The difference is the fulfilment
> process. It's decision making however, should be informed around strategy
> and rules."
>
> **Q2.** "the spec for Swing Trading. The test conditions were initially set
> to 10 working days, the longer term view would be to extend this to 60
> days, once the machinery was proven."
>
> **Q3.** "The original vision has been lost amongst multiple development
> branches arising during the build. These branches have been formed,
> sometimes from misinformation, or not anchoring back to the fundamentals.
> As seen in this audit, conflicting decisions being made has been the
> consequence of this."

**How the audit applies them.** Each answer is given with the audit's
reading, so the operator can correct the reading at Checkpoint B.

**Q1: one recommendation, formed by the AI, fulfilled two ways.**
* *The reading:* the AI makes the recommendation, and its decision-making is
  informed by the selected strategy and the rules (the rails). The same
  recommendation is produced in both modes; the modes differ only in who
  fulfils it (a human or the autonomy gate). This is closest to option (b),
  and it agrees with the operator's 12 August strategy document: "the same
  underlying decision engine" for both modes (AE-20).
* *Against the current system:* neither mode acts on an AI recommendation.
  Both act on the swing rule's signal. The AI's buy/sell/hold (M136) is a
  separate panel on the AI Advisor screen, produced on request, and it is
  not attached to the order a human signs in the Blotter or to the order the
  gate signs. The paper's own workflow step, where the AI's rationale
  accompanies each order to sign-off (P §14.1), is not built (map item 56).
* *Effect:* map item 3 stays **E**, risk **H**, and it is now measured against
  a stated intent, not an inferred one. §4.001's residual question (how large
  the AI's part is) is answered: the AI forms the recommendation, within the
  strategy and the rails.

**Q2: the methodology is the swing specification; hold 10 working days, 60
days later.**
* *The reading:* `Swing Trader methodology.md` is the specification for
  QAT's swing strategy. The paper's §4.10 is the outline it sits within. The
  holding condition for testing is 10 working days, to be extended to 60 once
  the machinery is proven. That agrees with 10 September, when the operator
  said the 60-day horizon was not to be relied on yet (AE-31).
* *Effect on §8.1:* every "vs S" difference is **drift from the operator's
  design**, class **E**, and the rule itself is agent-only (map item 15). The
  "vs P" column records what the outline allows; it no longer excuses a
  difference. The following are E against the specification:
  - the entry (one of three setups, no rejection tail, no wait for the close,
    no next-open buy);
  - the trend filter (no weekly chart);
  - volume confirmation;
  - the stop (volatility-based, not chart-based);
  - the target (no resistance check);
  - the entry order type (market, not limit);
  - trade management (no half at 1R, no breakeven, no trail);
  - the exit (EMA20 < EMA50, where the specification ends the swing on a
    close below the EMA20);
  - the forming-bar evaluation.
* *The time stop (map item 20).* The 30-trading-day time stop is **E against
  the specification's 10-working-day test condition**. §8.1 and the register
  (AE-17) said the operator "kept" 30. That is corrected: on 8 August the
  operator declined a proposal to lengthen it to 45, and no record shows the
  operator choosing 30 over 10. The 10-day minimum hold (map row
  "Holding period") matches the test condition. The time stop does not.
* *Where the strategy came from.* On 24 July the operator chose "Fresh build,
  but mine ShareTrader for reusable logic". The option's own description
  said "port over useful logic (e.g. the swing trader methodology …)"
  (AE-02). The build's survey agent was instructed to read `Swing Trader
  methodology.md`. Its report describes the reference app's rule and never the
  methodology file's content. The methodology was requested and not
  implemented (CE-026).

**Q3: the first build's departures are part of how the vision was lost.**
* *The reading:* the operator does not treat these as legitimate choices. They
  are branches formed "from misinformation, or not anchoring back to the
  fundamentals". The audit therefore records the first build's departures
  from the pasted brief as Claude errors (CE-027): no decision matrix, the
  validation pipeline and the output guard not wired.
* *The operator's diagnosis is also a finding for the synthesis (Stage 10):*
  the vision was lost across "multiple development branches", some formed
  from misinformation, with "conflicting decisions" as the consequence. The
  evidence in this audit supports it, from the first day:
  - the survey of 24 July presented the operator's autonomous design and
    AI-involvement sliders as "precisely the pattern your spec … explicitly
    forbid", relying on the human-sign-off rule Claude itself had added to
    the paper (§4.0);
  - the 26 July build dropped an approved AI role (CE-021);
  - a third-party review's example value became swing's time stop (item 20);
  - an ordering was approved on a wrong recovery claim (CE-017).

**The answer to §8.3, restated.** QAT is **not** trading the swing strategy
the operator designed. The operator's specification was requested on 24 July
and not implemented. What runs is a generic pullback rule from the first
build, inside rails that later work added around it.
