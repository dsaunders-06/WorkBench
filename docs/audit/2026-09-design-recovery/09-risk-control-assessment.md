# QAT Design Recovery & Design Intent Audit, R9: Risk-Control Assessment

**Brief §7 ("Audit the risk-control stack"). DRAFT for Checkpoint B.**
**Prepared:** 14 September 2026. Read-only: nothing in the system was changed.
**Records:** everything up to 12 September. Trading has been suspended since
14 September, so no newer evidence exists.

**Sources**
* The code, as traced by the Stage 3 investigators (`stage3/`, chiefly
  investigator 2, stages A–G, and investigator 3, section A) and re-read
  where cited.
* `risk_decisions.csv`: 4,958 rows, 24 Aug–11 Sep, all ASX. One row per risk
  evaluation. A candidate is re-evaluated on every tick while its signal
  stands.
* `decision_journal.csv`: 477 rows. It writes a verdict only when the verdict
  for a symbol **changes** (`decision_journal.py:88-109`), so it counts
  changes, not evaluations.
* `qat.log` and its rotated files, which cover 24 Aug–12 Sep.
* The IBKR activity statement for 24 Aug–11 Sep (evidence archive).
* Five read-only tools, in `s07-s13-risk-and-interactions/tools/`:
  `rails_by_day.py`, `risk_per_trade.py`, `aggregate_series.py`,
  `gate_and_halts.py`, `evidence_chain.py`. Every figure below comes from one
  of them, run on 14 Sep.

**Units.** "Rows" are evaluations; "symbols" are distinct candidates;
"symbol-days" are distinct candidate-days (CE-024). They are never
interchangeable.

The brief says not to recommend weakening a safety control because it reduces
trading, and to identify the causal chain instead. This section makes no
recommendations. The causal chains are in R16.

---

## 9.1 The stack, in the order a buy meets it

The first refusal ends the evaluation, so **position in this order decides
which control gets the credit**.

| # | Where | Control | Effect | Setting (deployed) |
|---|---|---|---|---|
| 1 | bridge | pending / held / live-buy duplicate guards | silent drop | — |
| 2 | bridge | weekly entry budget | drop, INFO log | 10 a week |
| 3 | OMS | allow lists, position and resting-order quarantines, pending corporate action, kill switch | refuse | — |
| 4 | engine | kill switch | refuse | — |
| 5 | engine | sizer: `min(half-Kelly × equity ÷ price, 1% × equity ÷ (2.5 × ATR))` | size; refuse at zero | Kelly on placeholders W 0.55, R 1.5 until 20 closed trades |
| 6 | engine | per-trade stop budget (1% ÷ stop distance) | trim | 1% |
| 7 | engine | regime scalar × earnings scalar | trim | 0.3–1.0; earnings 0.5 within 5 days |
| 8 | engine | no leverage (cash less reserve) | trim or refuse | reserve 1,000 |
| 9 | engine → governor | position count | refuse | 10, at `>=` |
| 10 | governor | aggregate risk-at-stop | refuse at no headroom, else trim | 5% of equity |
| 11 | governor | single name, sector, correlated cluster, gap budget | trim (refuse below 1 share) | 15%, 30%, 30% at ρ ≥ 0.70, 5% at a 6% gap |
| 12 | engine | portfolio checker: ES 97.5, single name, sector | refuse | ES 3% |
| 13 | engine | cost-to-risk | refuse | 10% |
| 14 | OMS | whole shares; 10% of spendable cash per order; broker ceiling | trim | 10%; ceiling off |
| 15 | autonomy gate | 18 rails, among them session phase and opening auction, never-ticked symbol, strategy list, promotion evidence (off on paper), day P&L halve at −2% / pause at −4%, 3% price drift | block, halve, or leave pending | as listed |
| 16 | sign-off | kill switch, duplicate-transmission guard, protective re-read, cash re-check | refuse | — |
| alongside | kill switch | daily loss 3%, drawdown 20%, reconciliation mismatch, manual, IBKR reconnect exhausted, unrecognised IBKR order error | halt every sign-off | — |

Code references: investigator 2, ordered list 1 (steps 1–30), and
investigator 3, section A. The kill switch has no staleness trip (R5 §5.3 #3).

## 9.2 What each control did (24 Aug – 12 Sep)

### Refusals recorded by the risk engine

| Rail | Rows | Symbols | Symbol-days | Days |
|---|---|---|---|---|
| Position count (10) | 4,265 | 27 | 41 | 10 |
| Aggregate risk-at-stop (5%) | 453 | 6 | 6 | 2 (4 and 11 Sep) |
| Cost-to-risk | 1 | 1 | 1 | 1 (3 Sep) |
| Approved (buys) | 68 | 18 | 19 | 8 |
| Exits refused by the kill switch | 158 | 2 | 2 | 2 (4 and 9 Sep) |
| Exits approved | 13 | 3 | 3 | 2 |

By day:
* the position count refused on every refusing day from 25 Aug to 9 Sep, and
  was the only refusing rail on all of them except 3 Sep (plus 1 cost-to-risk
  refusal) and 4 Sep (plus 4 aggregate-cap refusals);
* the aggregate cap was the only refusing rail on 11 Sep (449 rows,
  4 symbols).

**The record names the first refusing rail, not every rail that would have
refused.** On 9 Sep two BHP decisions were refused by the count while the
aggregate was also over its cap (`aggregate_series.py` puts the book at
8.03–8.19% from 11:27 to 13:09). Only the count is recorded.

### Sizing: how much risk each entry actually took

The OMS proposed 20 buys, 19 symbol-days, and signed off all 20. BHP on 3 Sep
was signed but staged by TWS and never sent (CE-005).

* **No entry took its 1% budget.** Risk at the proposed quantity, as a share of
  equity: minimum **0.13%**, median **0.45%**, maximum **0.70%**.
* **Half-Kelly on placeholders bound 13 of 20.** At W 0.55 and R 1.5 it sizes
  12.5% of equity in notional. That takes less risk than 1% whenever the stop
  is under 8% of the price, which swing's 2.5 × ATR stop was on all 13. The 1%
  budget bound the other 7.
* **Regime scalar:** 0.7 on 9 entries, 0.9 on 6, 1.0 on 5.
* **The 10%-of-spendable-cash cap cut 18 of 20** after the engine had approved
  them: median to 77% of the approved size, minimum 35%. WOW 3,164 → 1,098,
  JHX 3,036 → 1,097, COH 816 → 363. The cut shows only in the log and the
  journal. The audit row keeps the engine's figure (`oms.py:493-519`).
* **Governor trims: 4 (PNI, ANZ, SEK, TAH), all by the aggregate cap.** For
  each, the headroom recomputed from the recorded inputs equals the approved
  share count. Single-name, sector and gap had room every time.
* **Cash reserve / no leverage:** never trimmed, never refused.

### The controls that never acted

| Control | Evidence it never acted | Why (fact) |
|---|---|---|
| Single-name 15% | 0 refusals, 0 trims | Held names are never added to (bridge duplicate guards), so the name cap only limits the candidate's own notional. That is already held to ≤ 12.5% by placeholder Kelly and ≤ 10% of cash by the OMS cap. **It cannot bind while either holds** (derived) |
| Sector 30% | 0, 0 | Largest same-sector exposure before an approved buy: 6.6% of equity |
| Correlated cluster | 0, 0 | The cluster was **empty on all 68 approved buys**: no holding correlated at 0.70 or more with any candidate. That agrees with Claude's 7 Aug claim that it cannot bind at 10 positions (AE-17), now measured |
| Gap budget | 0, 0 | On the four governor trims its limit was 5,647–307,759 shares, never the smallest of the governor's limits |
| Portfolio ES 3% | 0 refusals | — |
| Earnings half-size | **applied on 745 evaluations, none approved** (DMP, KAR, RHC, 27–28 Aug, all refused by the count) | Of the 19 approved entries, 12 had no earnings date (the calendar did not answer, so the rail abstains, `engine.py:158-159`); 7 were 48–117 days away; WOW was one day past a print |
| Daily loss 3%, drawdown 20% | 0 kill-switch trips | — |
| Gate day-P&L rails (−2% halve, −4% pause) | 0 blocks | The −4% pause sits behind the −3% kill switch (R7 #34) |
| Weekly entry budget | 0 refusals logged | — |
| Time stop (30 trading days) | 0 fired | The oldest open positions (opened 25 Aug) had about 14 weekdays at the last trading session, 11 Sep |

### The autonomy gate

| Gate outcome | Log lines | Orders | Symbols | Days |
|---|---|---|---|---|
| Session phase "Midday Lull" | 340 | 7 | 7 | 3 |
| Session phase "Opening Volatility" | 9 | 2 | 2 | 2 |
| Kill switch active | 249 | 8 | 4 (BHP, A2M, IAG, SEK) | 3 |
| Order already transmitted (re-evaluation, not a refusal) | 249 | 23 | 12 | 4 |
| Evaluation failed, left pending | 8 | 8 | 8 | 1 (1 Sep: "ConnectionError: Not connected") |

* **The session gate delayed 9 entries and refused none.** Every order it
  blocked was signed off once the phase opened.
* **The price-drift check was skipped on 298 evaluations** because there was no
  broker quote: 283 on 3 Sep, and the rest on 26 Aug, 31 Aug, 1 Sep and 4 Sep.
  No drift refusal appears anywhere in the log (24 Aug–12 Sep). Since 4 Sep
  (`15ffd38`) it falls back to the app's own feed when the broker has no quote.

### The kill switch

19 trips from 24 Aug to 9 Sep:

| Cause | Trips |
|---|---|
| Unrecognised IBKR order error (10349, 10148) | 7 |
| Reconciliation mismatch | 6 |
| IBKR reconnect exhausted | 4 |
| Manual | 2 |
| Daily loss, drawdown | 0 |

Every reset was the operator's, from the risk console. The 24 Aug trip has no
reset: before 25 Aug the switch lived in memory, and a restart cleared it
silently (`kill_switch.py:31-37`). Durations are not given because they are
wall-clock and include hours with the app closed.

### Not measurable from the records

* **Silent drops before the risk engine** (duplicate guards, too little
  history, bad ATR). No record is written (investigator 2, stage A).
* **Per-symbol staleness exclusions.** The log carries the rail's startup line
  and the never-printed ("absent") counts, not exclusion events. The effect
  on throughput is **NOT DETERMINED**.

## 9.3 The brief's seven questions

**1. Which controls are independent?** Each of these measures a quantity no
other control measures:
* the position count;
* aggregate risk-at-stop;
* the gap budget (notional under a shock, not distance to the stop);
* cost-to-risk;
* portfolio ES;
* the session phases and opening auction;
* the price-drift check;
* the day-P&L rails;
* the never-ticked-symbol rail;
* the regime and earnings scalars;
* promotion evidence (off on paper).

**2. Which overlap?** The same quantity is checked more than once:
* **Kill switch:** four times (OMS, engine, gate, sign-off).
* **Per-trade risk:** the sizer's ATR cap and the engine's stop budget. They
  are identical for swing, whose stop is 2.5 × ATR.
* **Cash:** the no-leverage rule, the per-order cash cap, two "cash unknown"
  refusals, and the sign-off re-check.
* **Single name and sector:** the governor trims and the checker refuses. The
  governor's trim leaves the checker nothing to catch (investigator 2).
* **Duplicate buys:** the bridge's three guards, the governor's `already_held`,
  and the OMS's transmitted set.
* **Loss limits:** the gate's −4% pause and the kill switch's −3% trip
  (R7 #34, class F).
* **Gap budget and aggregate cap:** both bound the loss from an adverse move
  (R7 #29, class F).
* **Single-name cap:** dominated by placeholder Kelly and the cash cap, as
  above.

**3. Which can independently refuse the same trade?** Any rail in 9.1 can refuse
a candidate another rail would also refuse. The code stops at the first, and
the records name only that one. So **the refusal counts show which rail
refused first, not which rails bind.** Measured case: 9 Sep (two BHP
decisions, count and aggregate both over). How often this happens cannot be
counted from the records, because later rails are never evaluated.

**4. Which interact to produce unexpectedly restrictive behaviour?** Three are
evidenced (detail in R16):
* **(a)** The aggregate cap and the governor's full-value rule (a position with
  no known stop, or priced at or below its stop, counts at its whole value).
  One position so counted refused every entry on 11 Sep. Without it the book
  stood at 3.16%.
* **(b)** On 26 Aug two entries 173 ms apart each saw nine positions, taking the
  book to eleven. The count then held it at the cap and refused 1,036
  evaluations on 27 Aug. Fixed 27 Aug (`72191a9`, item 58).
* **(c)** Placeholder Kelly and the per-order cash cap keep each entry's risk
  near 0.45%. Ten such positions use about 4.5% of the 5% aggregate budget, so
  **in normal operation the position count binds before the aggregate cap
  can**. The aggregate cap has bound only when (a) inflated it.

**5. Which materially change strategy throughput?**
* **Whether a trade happens:** the position count (every refusing day from
  25 Aug to 9 Sep) and the aggregate cap (11 Sep, and briefly 4 Sep).
* **How big it is:** placeholder Kelly (13 of 20), the cash cap (18 of 20, to a
  median 77% of approved size), and the regime scalar (0.7 on 9 of 20).
* **When it happens:** the session gate delayed 9 entries.
* No other control changed a trade in this period.

**6. Which were introduced after actual failures?** From R7's "Why" column and
the incidents:

| Control | The failure behind it |
|---|---|
| Transmitted orders count as pending exposure (item 58, 27 Aug) | 26 Aug, eleven positions against ten |
| Duplicate-transmission guard (M139) | CE-003, 24 Aug |
| HALT class for unrecognised IBKR errors | 3 Sep (AE-28) |
| Never-ticked-symbol rail (31 Aug) | "absent is not the same as stale" |
| Staleness trip *removed* from the kill switch (31 Jul) | every staleness trip was a false positive |
| No-leverage cash rule | a margin loan in the reference app, before QAT existed, 21 Jul (C2 [173]) |
| Resting-order scan and its quarantine | orphaned bracket legs, 24 Aug |
| Position quarantine | the 8 Aug split test (R7 #49) |
| Protective re-arm | six unprotected positions, 31 Jul |
| Opening-auction refusal | market orders into the auction |

**7. Which were introduced without an observed failure?**
* **From the reference app's settings:** per-trade 1%, the aggregate 5%, the
  count of 10, sector 30%, the day-P&L rails, the price-drift check.
* **From the paper:** the 2.5 × ATR stop, ES 3%, daily loss 3%, drawdown 20%.
* **From reasoning or measurement, not an incident:** single-name 15%, the gap
  budget, cost-to-risk.
* **From third-party reviews:** the correlated cluster, earnings half-size, the
  30-day time stop.
* **On the operator's request:** the 10%-of-cash cap. It was requested at
  12:52 on 24 Aug (AE-26), before that day's first order (13:05) and before
  the duplicate transmission (14:04), so it was **not** a response to CE-003.

## 9.4 Facts for other sections

* **R10 (brief §8):**
  - JHX's resting stop did not fill with the price below it (tracker
    section 2; held until after the audit by the operator's decision).
  - A2M on 4 Sep: a sell the broker cancelled was booked at transmission, and
    the app dropped the position's stop from its own records.
* **R13 (brief §11):**
  - The two audit files count different things: every evaluation, against
    changes of verdict. Neither counts candidates.
  - The OMS's cash-cap cut is not in the audit row.
* **R14 (brief §14):** item 58's failure → control → cost chain, above.
