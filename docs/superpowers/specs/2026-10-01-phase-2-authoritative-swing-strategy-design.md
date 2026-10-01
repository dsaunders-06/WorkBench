# Phase 2 — Authoritative Swing Strategy Design

**Status:** Approved design, 1 October 2026

**Recovery phase:** Phase 2 — Authoritative strategy

**Branch:** `recovery/phase-2-authoritative-strategy`

**Baseline:** `87ba9f4782e7f0d0aaf32505704400c8298a7a4f` (merged Phase 1)

**Authority:** the operator-approved decisions recorded here, interpreted in the
context of `C:\ShareTrader\Swing Trader methodology.md` and the QAT Recovery &
Migration Brief. Historical code and earlier AI-authored material are evidence,
not authority where they conflict with this specification.

## 1. Purpose and boundary

Phase 2 replaces QAT's drifted swing rule with an explicit, deterministic,
machine-testable strategy contract and evaluates it independently of AI.

The phase must:

1. implement the operator's three swing entries: EMA20 pullback, bull flag, and
   double bottom;
2. make every qualification, rejection, abstention, order instruction, and
   position transition reproducible and auditable;
3. reuse one authoritative rules engine in research and later recommendation
   paths;
4. produce statistically meaningful evidence without treating the existing
   survivorship-biased universe as proof of edge; and
5. preserve the Phase 1 lifecycle and protection invariants.

Phase 2 has no route to IBKR, live orders, paper orders, AI recommendations, or
autonomous action. It does not replace or relax the OMS boundary. Production
behavior remains unchanged until a later, separately approved integration
phase.

## 2. Governing invariants

The implementation and evidence must preserve these invariants:

- Only finalized daily and weekly bars may affect a decision.
- No future bar, partial week, future index constituent, or corrected value
  from a later dataset version may leak into a decision.
- Missing or unverifiable required data produces `ABSTAIN`, never an inferred
  value or permissive default.
- A setup confirmed at a daily close can create only a one-session limit
  instruction for the following ASX session.
- An unfilled or invalidated entry is never chased.
- A structural protective stop can tighten but never loosen.
- No executable position, cost basis, or realized trade exists without a
  simulated or broker-confirmed fill event.
- Protection remains active until a replacement risk-reducing exit is
  authorized and confirmed.
- Replaying the same ordered inputs is idempotent and produces byte-equivalent
  decision content apart from explicitly excluded packaging metadata.
- AI output, confidence, Kelly estimates, and subjective conviction cannot
  alter a Phase 2 decision.

## 3. Architecture decision

Phase 2 adopts a **shared deterministic strategy engine**.

The engine is a pure domain component. It accepts validated market history,
portfolio equity, a versioned cost model, and the prior strategy-position state.
It returns typed evidence and proposed state transitions. It has no broker,
network, database, wall-clock, UI, scheduler, or AI dependency.

The engine contains:

- common indicator calculations;
- the completed-week trend filter;
- the three pattern detectors;
- volume and resistance validation;
- setup overlap resolution;
- entry, sizing, and lifecycle rules; and
- a typed decision/evidence model.

Historical replay supplies data and simulated executions through adapters.
Later phases may place an adapter between the same engine and the live
recommendation architecture. No adapter may recalculate or reinterpret a
strategy rule.

### 3.1 Deferred production-stack parity replay

Simulating the entire production application remains an explicit follow-on
option. After the shared engine passes correctness, reproducibility, and
evidence gates, a **production-stack parity replay** may exercise it through the
real scheduler, persistence, risk, OMS, and simulated-broker stack. That work is
not part of the initial Phase 2 implementation and requires a separate design
decision. The shared engine remains the rule authority in either architecture.

## 4. Canonical market calculations

All calculations use completed ASX sessions in chronological order.

### 4.1 EMA

`EMA(n)` uses the standard exponential multiplier `2 / (n + 1)`, seeded with
the simple mean of the first `n` valid closes. A value is unavailable until the
seed exists. EMA comparisons do not use rounded display values.

### 4.2 ATR

For daily session `t`:

```
TR[t] = max(
    high[t] - low[t],
    abs(high[t] - close[t-1]),
    abs(low[t] - close[t-1]),
)
```

`ATR(14)` uses Wilder smoothing, seeded with the simple mean of the first 14
valid true ranges. It is unavailable until that history exists.

### 4.3 Exchange ticks

Every order price is normalized with the ASX tick schedule effective for the
instrument and session. A stop one tick below an invalidation is exactly one
valid tick at that price. Conservative maximum buy prices round down. Protective
sell-stop calculations round down so rounding cannot tighten risk beyond the
specified structural value.

### 4.4 Weekly bars

Daily sessions are aggregated to the official ASX trading week. Only weeks
whose final scheduled trading session has completed may enter weekly EMA
calculations. Holidays shorten a week; they do not make it partial. A week still
in progress is excluded.

## 5. Common setup gates

A long setup can qualify only when all common requirements are satisfied:

- the signal bar is a finalized daily bar;
- every required prior bar is finalized, ordered, and quality-valid;
- at least 50 completed weekly bars exist;
- the weekly filter passes;
- required indicators are available;
- the pattern-specific structural invalidation is below the proposed entry;
- the resistance test leaves a clear path beyond 2R;
- the cost-aware 1% sizing rule yields at least two whole shares; and
- no position or entry instruction already exists for the symbol in the
  combined portfolio.

### 5.1 Weekly filter

Reject a bullish daily setup only when both of these are true on the latest
completed weekly bar:

1. weekly close is below weekly EMA20; and
2. weekly EMA20 is below weekly EMA50.

If either condition is false, the filter passes. Fewer than 50 completed weeks
or unavailable weekly inputs produces `ABSTAIN`.

### 5.2 Breakout volume confirmation

Volume confirmation applies to bull-flag and double-bottom breakouts only.
Breakout-day finalized volume must be at least `1.5 ×` the arithmetic mean of
the preceding 20 completed daily sessions. The breakout day is excluded from
the mean.

Missing, zero, partial, synthetic, or unverified volume in the 21 required
sessions produces `ABSTAIN`. The authoritative input is finalized vendor daily
volume; QAT's live repeated cumulative tick accumulator is not an eligible
source.

The baseline multiplier is frozen at 1.5. Multipliers 1.25 and 2.0 may appear
only as declared sensitivity runs and cannot replace the baseline after holdout
results are known.

## 6. Entry patterns

Each detector emits either a fully measured candidate, a rule-by-rule rejection,
or an abstention with a data-quality reason.

### 6.1 EMA20 pullback with bullish rejection

The signal bar qualifies when all of these are true:

1. daily EMA20 is above daily EMA50;
2. current EMA20 is above EMA20 from five completed sessions earlier;
3. signal low is at or below EMA20;
4. signal close is above EMA20;
5. signal close is above signal open;
6. the real body is positive and the full candle range is positive;
7. lower wick, `min(open, close) - low`, is at least twice the real body,
   `abs(close - open)`;
8. close is in the upper third of the candle range; and
9. the weekly filter passes.

A flat or malformed candle produces no setup. The structural invalidation is
the lower of the signal-bar low and EMA20 on the signal bar. The initial stop is
one valid tick below that invalidation.

Volume confirmation is not required for this pattern.

### 6.2 Bull flag

A bull flag consists of a five-session pole, a 3-to-8-session flag immediately
after it, and the current finalized breakout session.

The pole qualifies when its move from first open to final close is at least the
greater of:

- 5% of the first open; or
- two ATR(14) values measured at the pole's final session.

The flag qualifies when:

- the least-squares slope of its closes against session order is at or below
  zero;
- its lowest low retraces no more than 50% of the pole move; and
- its mean finalized volume is below the pole's mean finalized volume.

The breakout qualifies when:

- its close is strictly above the highest high of the flag;
- the 1.5× volume rule passes;
- daily EMA20 is above EMA50 and is above its value five sessions earlier; and
- the weekly filter passes.

When multiple 3-to-8-session flag lengths qualify for the same breakout, use
the longest. The structural invalidation is the flag's lowest low. The initial
stop is one valid tick below it.

### 6.3 Double bottom

A confirmed local low is lower than each of the three completed daily lows on
both sides of it. Two confirmed local lows form a candidate pair when:

- they are 5 to 30 trading sessions apart;
- their prices differ by no more than 2% of their mean; and
- a valid neckline exists at the highest completed-bar high strictly between
  the lows.

The neckline must stand above the average bottom price by more than the greater
of:

- 3% of the average bottom price; or
- one ATR(14), measured on the second-bottom session.

The current finalized breakout session qualifies when:

- its close is strictly above the neckline;
- its close is above daily EMA20;
- EMA20 is above its value five completed sessions earlier;
- the 1.5× volume rule passes; and
- the weekly filter passes.

EMA20 need not be above EMA50 because this is the reversal pattern. Use the
pair with the most recent second bottom; break any remaining tie with the most
recent first bottom. The structural invalidation is the second-bottom low. The
initial stop is one valid tick below it.

## 7. Historical resistance and entry instruction

Resistance uses the three calendar years of split-normalized, completed daily
bars known at the signal close. A swing high is strictly greater than each of
the five highs before and five highs after it. A major resistance zone requires
at least two swing highs:

- separated by at least 20 completed sessions; and
- each within 1% of the zone's median swing-high price.

Zones are built deterministically in ascending price order and record every
member and session. The nearest qualifying zone whose lower edge is above the
candidate entry is the relevant zone. If sufficient valid history exists but
no zone exists above the entry, the path is clear. Insufficient, unadjusted,
malformed, synthetic, or unverifiable history produces `ABSTAIN`.

For an entry price `E` and initial stop `S`, `R = E - S` and the 2R price is
`E + 2R`. The resistance zone's lower edge must be strictly above the 2R price.
The highest acceptable entry imposed by resistance is rounded down to the
greatest valid tick for which that strict inequality remains true.

The completed signal close is the no-chase reference price. The one-session buy
limit is the lower of:

- the signal close; and
- the highest resistance-constrained acceptable entry, when a relevant zone
  exists.

After the signal close, submit the instruction for the next scheduled ASX
session only. It fills only when the opening price is above the structural
invalidation and at or below the limit. Modeled buy slippage is added to the
opening price and capped at the limit. An opening price above the limit, at or
below the invalidation, a missing valid open, or no eligible opening trade
cancels the setup. Later intraday movement cannot revive it. A new order
requires a new completed-bar qualification.

## 8. Pattern overlap

Each pattern is replayed independently for its own performance assessment.

The combined portfolio permits one entry instruction or position per symbol.
When multiple patterns qualify on the same close:

1. retain every pattern's full evidence;
2. create one confluence candidate;
3. use the lowest permitted entry limit from the qualifying patterns;
4. use the lowest structural stop from the qualifying patterns;
5. recalculate resistance, cost-aware sizing, and all common gates; and
6. reject the confluence candidate if the conservative combined terms fail.

Signals observed while a position is open are recorded but cannot add to,
replace, or reset the position.

## 9. Position sizing and capital allocation

The baseline account risk budget is 1% of current portfolio equity. No 2%
baseline, Kelly term, AI confidence, conviction scalar, or placeholder edge is
permitted.

Choose the largest whole-share quantity `q` satisfying:

```
q × (entry fill - initial stop)
+ modeled entry costs(q)
+ modeled stop-exit costs(q)
<= 0.01 × current portfolio equity
```

Costs include the configured IBKR commission floors, applicable exchange
charges, and modeled entry and stop-exit slippage. Quantity must be at least two
shares. The stop is fixed by chart structure; sizing may never move it.

The primary edge report measures every qualified trade in R independently of
capital competition. The portfolio replay is long-only, fully cash-funded, and
uses no borrowing, leverage, or margin. Existing positions reserve their
purchase cost.

When simultaneous entries require more cash than is available, scale all their
risk budgets by the same factor, recalculate and round quantities down to whole
shares, and remove allocations below two shares. Repeat until the batch is
cash-feasible. Do not rank symbols with a score absent from the methodology.

The source methodology's aggregate appetite controls are reported but not used
to change Phase 2 strategy-edge decisions. Their integration belongs to Phase
4, where existing concentration, aggregate-risk, and portfolio safety rails
will be evaluated separately.

## 10. Position lifecycle

### 10.1 State model

The strategy position has these explicit states:

1. `FLAT`
2. `ENTRY_PENDING`
3. `OPEN_FULL`
4. `RUNNER`
5. `EXIT_PENDING`
6. `CLOSED`
7. `CANCELLED`

Every transition has a stable event identity and is idempotent.

### 10.2 Initial risk and partial target

After the confirmed entry fill:

- define one price-risk unit per share as
  `R = actual entry fill - initial structural stop`;
- protect the entire filled quantity at the initial stop;
- allocate half the shares, rounded up, to the banked portion;
- allocate the remainder to the runner; and
- place the banked target at `actual entry fill + R`.

R is a price-risk unit. Commissions and other costs are reported separately in
net results and do not redefine R.

### 10.3 Target fill and runner

On a confirmed banked-target fill:

- move the runner's stop immediately to the actual entry fill price; and
- after each later completed daily close, calculate
  `highest completed daily high since entry - 2 × current ATR(14)`.

The runner stop is the maximum of its existing stop, breakeven, and the
tick-normalized ATR candidate. It can never move down.

### 10.4 Daily-close invalidation

Using completed daily candles only, invalidate the remaining position when
either condition occurs:

- one close is at least 0.5 ATR(14) below EMA20; or
- two consecutive completed closes are below EMA20.

The remaining quantity exits at the next tradable open. Existing protection
remains active until that replacement exit is authorized and filled.

### 10.5 Time stop

The entry session is completed holding session one. After the tenth completed
holding session, schedule the remaining quantity to exit at the next tradable
open. Ten sessions are a maximum test-phase hold, not a minimum hold. Protective
stops and strategy invalidation may exit earlier. The proposed 60-day horizon
is deferred until the machinery is proven.

### 10.6 Trigger coexistence

Protective stop, banked target, daily invalidation, trailing stop, and time stop
remain independently observable. When more than one trigger applies, record all
of them but submit only one exit for each share. The earliest actual execution
governs the state and P&L.

## 11. Historical execution model

The Phase 2 replay uses a conservative daily-bar fill model:

- Valid next-session entries fill at open plus buy slippage, capped at the
  limit.
- An entry open above the limit or at/below structural invalidation cancels the
  instruction.
- A protective sell stop crossed by a gap fills at open minus sell slippage.
- An intraday stop touch fills at the stop minus sell slippage.
- Close-based and time-based exits fill at the next tradable open minus sell
  slippage.
- A banked sell-limit target crossed by an opening gap fills at the better of
  its target or the opening price less sell slippage.
- When a daily range permits multiple event orders and the open does not prove
  their order, use the worst feasible sequence for the strategy.

The last rule means:

- if the original stop and target are both touched, the original stop wins for
  the entire remaining position;
- if the original stop is not touched but the target and newly activated
  breakeven stop can both be touched, bank the partial target and stop the
  runner at breakeven; and
- every such bar carries an ambiguity flag.

Reports must include an optimistic-order sensitivity result. It is diagnostic
only and cannot replace the conservative baseline.

## 12. Data and corporate-action contract

Every market record identifies symbol, official exchange session, timezone,
source, acquisition/version metadata, finalization status, and quality state.
The frozen dataset contains:

- raw OHLCV as traded;
- split-normalized analytical OHLCV;
- split and consolidation events;
- cash-dividend events;
- symbol changes, suspensions, index membership, and delisting outcomes; and
- an integrity manifest with hashes and coverage diagnostics.

Indicators and pattern geometry use split-normalized data. Fill and commission
calculations use prices and quantities as traded. Splits and consolidations
adjust open quantities, cost basis, stops, and pending orders without creating
P&L. Eligible cash dividends are credited separately. Dividend-back-adjusted
prices are not used for signals or fills.

Promotion data must provide realizable delisting proceeds or another explicit,
auditable terminal outcome. A silent disappearance is a dataset integrity
failure.

Missing, partial, synthetic, conflicting, or unverifiable required data yields
`ABSTAIN`. A symbol-specific defect may be isolated while replay continues, but
the run must disclose it. A dataset-wide manifest, calendar, adjustment, or
ordering failure invalidates the entire run.

## 13. Decision evidence

Each evaluated symbol-session emits an immutable decision envelope containing:

- deterministic decision and parent-event identifiers;
- strategy and schema versions;
- dataset-manifest identity and code commit;
- symbol, exchange session, and evaluation timestamp;
- input-bar identities or hashes;
- pattern name or confluence membership;
- every measured value, threshold, and pass/fail result;
- rejection or abstention reason codes;
- resistance-zone members and chosen zone;
- proposed entry, stop, target, quantity, and modeled costs;
- prior state, proposed transition, and resulting state;
- every active exit trigger;
- fill assumptions and ambiguity flags; and
- regime label and probabilities for analysis only.

Identical semantic inputs must produce the same identifier and content.
Evidence is append-only. Corrected source data creates a new manifest and new
decisions rather than silently rewriting earlier evidence.

## 14. Regime treatment

The approved weekly filter is part of the authoritative strategy. QAT's existing
market-regime classification is not an entry gate in the primary Phase 2 test.

Every trade records the contemporaneous regime for segmented analysis. A
regime-gated variant may be reported as a declared sensitivity experiment, but
it cannot replace or alter the primary result. Strategy rotation remains Phase
7 work.

## 15. Universe and evidence tiers

### 15.1 Engineering evidence

The existing static ASX snapshot may be used immediately to validate machinery,
schemas, state transitions, and provisional comparisons. Every output must call
it survivorship-biased and non-promotional. It cannot prove an edge or satisfy a
promotion gate.

### 15.2 Promotion evidence

Promotion-grade evidence requires:

- point-in-time ASX 200 membership;
- entrants, exits, symbol changes, and delisted securities;
- split-normalized OHLCV and auditable corporate actions;
- at least ten years, or the longest complete period available with the
  shortfall stated explicitly; and
- a frozen, hashed dataset manifest.

Acquiring a commercial historical source is a later procurement decision. The
implementation must expose a source port and must not encode one vendor's
schema into the strategy engine.

## 16. Validation protocol

Promotion history is split chronologically without random shuffling:

- first 60%: development and verification;
- next 20%: validation and declared sensitivity checks; and
- final 20%: locked holdout.

The holdout is evaluated only after rules, thresholds, data processing, and
cost assumptions are frozen. Any strategy-rule change after viewing it creates
a new strategy version and requires a fresh holdout. Results are also reported
by calendar year and recorded regime to reveal instability.

No parameter optimization is part of Phase 2. Sensitivity values are declared
in advance and remain secondary to the frozen baseline.

## 17. Verification layers

Verification proceeds in this order:

1. **Canonical calculation tests** for EMA, Wilder ATR, tick normalization,
   weekly aggregation, and cost-aware sizing.
2. **Pattern examples and counterexamples** for every individual rule, boundary,
   missing-data case, and tie-break.
3. **Golden lifecycle scenarios** covering entry gaps, cancellations, stops,
   targets, ambiguous bars, partial exits, runner ratchets, invalidations, time
   stops, splits, dividends, suspensions, and delistings.
4. **Determinism tests** proving identical inputs produce identical evidence and
   repeated events cannot duplicate an order or fill.
5. **Isolation tests** proving the Phase 2 research path cannot reach broker
   submission interfaces.
6. **Engineering replay** on the current static ASX snapshot.
7. **Promotion replay** on the frozen point-in-time dataset, only when available.

Tests use fixed clocks, official exchange calendars, and immutable fixtures.
They must not depend on the machine's current date, network state, or changing
vendor responses.

## 18. Reports and artifacts

Every run produces machine-readable JSON and CSV evidence plus a concise human
report, tied to deterministic checksums. Report separately:

- EMA20 pullback, bull flag, and double bottom;
- combined confluence portfolio;
- normalized signal-level R outcomes;
- fully cash-funded portfolio outcomes;
- development, validation, and holdout periods;
- baseline and predeclared sensitivities; and
- static-universe and promotion-grade evidence tiers.

Metrics include trade count, net expectancy in R, confidence interval, win and
loss distribution, profit factor, maximum drawdown, exposure, turnover, holding
time, cost drag, maximum favorable and adverse excursion, regime segmentation,
symbol/year/trade concentration, rejections, abstentions, and ambiguous-bar
impact.

Compare portfolio results with an ASX 200 accumulation or equivalent
total-return benchmark over identical sessions. The benchmark source and
transformation belong in the run manifest.

## 19. Promotion gate

Each pattern is assessed separately; a weak pattern cannot hide inside combined
results. Promotion from research authorizes later shadow testing only. It does
not authorize paper orders, autonomous action, or live money.

All of these gates must pass on the frozen baseline:

1. at least 100 completed holdout trades;
2. positive net expectancy after modeled costs;
3. the 95% block-bootstrap lower confidence bound for mean R is above zero;
4. profit factor is at least 1.20;
5. maximum portfolio drawdown is no greater than 20% with approved 1% sizing;
6. expectancy remains positive with doubled slippage and commission
   assumptions; and
7. results are not dominated by one symbol, year, or small group of exceptional
   trades.

For the confidence gate, group completed trades by their entry calendar month
so simultaneous and nearby signals remain together. Resample those month blocks
with replacement 10,000 times using a seed derived from the run manifest, and
use the 2.5th percentile of bootstrapped mean net R as the lower bound.

The concentration gate passes only when net expectancy remains above zero in
all three deterministic leave-out tests:

- remove every trade in the most profitable symbol;
- remove every trade entered in the most profitable calendar year; and
- remove the top 5% of trades ranked by net R, rounding the removal count up.

The report publishes the full symbol, year, and trade concentration
distributions as well as these tests.

Failure or insufficient sample size is a valid Phase 2 result. It cannot be
converted into a pass by relaxing a threshold after seeing the evidence.

## 20. Failure handling and operational safety

- All required-data failures are typed and fail closed.
- A run with a dataset-wide integrity failure has status `INVALID` and cannot be
  scored for promotion.
- A run with disclosed symbol-level abstentions remains analyzable, with counts
  and reasons reported.
- Research artifacts are namespaced by strategy version, dataset manifest, cost
  profile, fill model, and code commit.
- Earlier evidence is never overwritten.
- CI verifies deterministic replay, rule coverage, schema compatibility, and
  broker isolation.
- Logs and artifacts must not contain credentials, account secrets, or broker
  tokens.

## 21. Explicitly deferred work

The following work is outside this specification:

- changing the deployed production swing strategy;
- AI recommendation generation or validation;
- connection to the risk engine, OMS, or broker;
- autonomous or recommend-only paper trading;
- live-money migration;
- aggregate portfolio appetite calibration;
- a 60-day holding horizon;
- regime-gated primary trading or multi-strategy rotation;
- parameter optimization; and
- production-stack parity replay until Option 2 effectiveness is established.

## 22. Acceptance criteria

Phase 2 implementation is complete only when:

1. one deterministic engine implements every baseline rule in this
   specification;
2. all golden, boundary, determinism, and broker-isolation tests pass;
3. the static ASX engineering replay completes with explicit survivorship
   caveats and reproducible artifacts;
4. every decision can be traced to versioned inputs and rule evidence;
5. existing production behavior and the Phase 1 safety invariants remain
   unchanged;
6. implementation documentation identifies all evidence that remains
   provisional because promotion-grade data is unavailable; and
7. a separate approval occurs before any integration with the live application,
   paper environment, AI layer, or OMS.

Promotion-grade results are conditional on obtaining the required point-in-time
dataset. Lack of that dataset does not prevent completion of the deterministic
engine or engineering validation, but it does prevent any claim that the
strategy has proven edge.
