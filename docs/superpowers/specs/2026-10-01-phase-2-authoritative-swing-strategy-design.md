# Phase 2 — Authoritative Swing Strategy Design

**Status:** Fifth revised draft for operator approval, 2 October 2026

**Recovery phase:** Phase 2 — Authoritative strategy

**Branch:** `recovery/phase-2-authoritative-strategy`

**Baseline:** `87ba9f4782e7f0d0aaf32505704400c8298a7a4f` (merged Phase 1)

**Authority:** the operator-approved decisions recorded here plus the current
review corrections, which remain pending operator approval, interpreted in the
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
portfolio equity, versioned decimal/cost/liquidity policies, and the prior
strategy-position state. It returns typed evidence and proposed state
transitions. It has no broker,
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

All calculations use completed ASX sessions in chronological order. For
promotion evidence, the signed dataset's versioned official-calendar ledger is
the authority for session identity, order, ad hoc closures, and shortened
sessions. It contains one row for every civil date in its effective interval
with `session_kind` equal to `FULL`, `SHORTENED`, `AD_HOC_CLOSED`,
`SCHEDULED_CLOSED`, or `WEEKEND`. Every row binds source identity, retrieval
time, content hash, reason or notice reference, and the expected open and close
times when tradable. `FULL` and `SHORTENED` rows project the ordered
`official_sessions` sequence. They require one matching session of market data;
closed rows prohibit a traded bar. A missing normal date, a bar missing from a
tradable row, or a bar attached to a closed row is therefore distinguishable
from a documented closure and is a dataset integrity failure.

The repository's rule-derived `market_calendar.py` is a fixture and
cross-check only; it must disclose differences but must not add, remove,
reclassify, or synthesize a promotion-calendar row. A missing, duplicated,
contradictory, or unverifiable signed calendar row is a dataset integrity
failure.

### 4.1 Exact numeric and price bases

Price, money, indicator, threshold, risk, and R-multiple values use decimal
arithmetic constructed from source text. Binary floating point is prohibited
in strategy-domain state, evidence, order calculations, cost calculations, and
canonical identifiers. The package uses precision 50, `ROUND_HALF_EVEN`, and
an analytical-price quantum of `1E-12 AUD`; this is numeric policy
`phase2-decimal-v1`. Decimals serialize in canonical, non-scientific form.
Whole-share quantities and raw share volume use integers.

Split and consolidation ratios, including cumulative raw-to-analytical
factors, are reduced integer rationals. Raw source prices remain exact
`Decimal` values. Price-basis conversion first uses an exact rational
intermediate, then quantizes the analytical result once to `1E-12 AUD` under
the versioned context. A general factor such as `3/10` is not required to
satisfy naive decimal equality `(x / f) * f == x`. Conversion tests instead
require the reconstructed raw value to equal the original after the declared
analytical quantum and raw price/tick normalization.

Analytical OHLCV, indicators, pattern geometry, and resistance zones use the
split-normalized analytical basis. At the signal session, the candidate entry,
structural invalidation, stop, and relevant resistance edges are converted to
raw as-traded basis with the manifest's auditable split factor. The resistance
test is repeated after conversion and order-price rounding. Pending orders,
fills, commissions, cash, P&L, and position state remain in raw as-traded basis.
Later splits transform open quantities and raw prices without changing value or
either recorded initial risk denominator. The independent reference
implementation uses integer-rational arithmetic rather than importing the
production decimal helpers, then compares at the declared quantum and tick
boundary.

Statistical routines may use explicitly versioned IEEE 754 binary64 arrays
after immutable decimal trade results are converted at the statistics boundary.
Their seed, library/runtime versions, algorithms, and output formatting belong
in the run manifest and do not enter strategy decision identifiers.

### 4.2 EMA

`EMA(n)` uses the standard exponential multiplier `2 / (n + 1)`, seeded with
the simple mean of the first `n` valid closes. A value is unavailable until the
seed exists. EMA comparisons do not use rounded display values.

### 4.3 ATR

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

### 4.4 Exchange ticks

Every order price is normalized in raw as-traded basis with the ASX price-step
schedule effective for the instrument and session. A stop one tick below an
invalidation subtracts exactly one valid raw price step, then rounds down to a
valid order price. Conservative maximum buy prices also round down. Actual
auction and market fills retain the exact raw traded price supplied by the
dataset even when that price is not on the ordinary order-entry grid.

The baseline ASX ordinary-equity schedule, verified against the ASX price-step
table on 2 October 2026, is `0.001` through `0.099`, `0.005` from `0.100`
through `1.995`, and `0.01` from `2.00` upward. The manifest records the
published schedule URL, retrieval date, content hash, and effective interval.
At a band edge, `previous_raw_order_tick()` must search the lower band's valid
grid rather than call `tick_size()` on the edge and subtract that upper-band
tick: the required predecessors of `0.10` and `2.00` are `0.099` and `1.995`.

### 4.5 Weekly bars

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
- the frozen liquidity-capacity model permits at least two whole shares; and
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

### 5.3 Liquidity and capacity

Promotion replay requires a versioned liquidity-capacity profile frozen before
the first promotion-tier outcome. It contains a maximum participation fraction
and a participation-aware price-impact/slippage curve justified from execution
studies outside the strategy outcome data, the signed reference view, and the
blinded development structural extract defined in Section 16. It may not use
development or validation returns, fills, exits, P&L, or any other forward
outcome. The profile becomes part of every later promotion fingerprint.
Calibration targets execution capacity and cost realism; it may not maximize
strategy returns.

For each instruction, calculate capacity only from the preceding 20 completed
sessions of verified raw share volume and raw dollar volume. The capacity
quantity is the smaller whole-share quantity allowed by the profile against
the median share volume and median dollar volume. Current-session volume,
opening-auction volume inferred from the completed daily bar, or future volume
is forbidden. Submitted quantity is the minimum of risk-sized, cash-feasible,
and capacity quantities. A result below two shares rejects the entry.

Daily data cannot prove opening-auction liquidity. Unless promotion data
contains auditable auction volume, every report must disclose this limitation
and publish participation and price-impact sensitivities. A promotion-grade
fingerprint cannot be created with a missing or provisional capacity profile.

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

When more than one between-bottom bar shares that highest high, every tied bar
is a neckline source member in ascending session order. The neckline price and
the ordered source-member identities are part of the pattern identity.

The neckline must stand above the average bottom price by more than the greater
of:

- 3% of the average bottom price; or
- one ATR(14), measured on the second-bottom session.

The current finalized breakout session qualifies when:

- the immediately preceding completed close is at or below the neckline;
- its close is strictly above the neckline;
- its close is above daily EMA20;
- EMA20 is above its value five completed sessions earlier;
- the 1.5× volume rule passes; and
- the weekly filter passes.

EMA20 need not be above EMA50 because this is the reversal pattern. Use the
pair with the most recent second bottom; break any remaining tie with the most
recent first bottom. The structural invalidation is the second-bottom low. The
initial stop is one valid tick below it.

The breakout must occur no later than 20 completed sessions after the second
bottom. A pattern-instance identity is derived from the first-bottom session,
second-bottom session, and the neckline source bars. A breakout-event identity
adds the crossing session. One crossing can create at most one instruction.

A cancelled or unfilled instruction consumes that breakout event but not the
pattern instance. The same bottom pair may qualify again only after a completed
close returns to or below the neckline and a later completed close crosses
strictly above it before the 20-session expiry. Once an entry for the pair
fills, the pattern instance is consumed permanently. A later filled trade
requires a newly confirmed pair. A cross that occurred before the second
bottom became confirmed cannot create a stale signal while price remains above
the neckline; it must recross or form a new pair.

## 7. Historical resistance and entry instruction

Resistance uses the three calendar years of split-normalized, completed daily
bars known at the signal close. A swing high is strictly greater than each of
the five highs before and five highs after it. Sort swing highs by price and
then by stable session/member identity. Enumerate every contiguous group in
that order containing at least two highs. A group qualifies when:

- for median price `M`, every member price `P` satisfies
  `abs(P - M) / M <= 0.01`; and
- at least one pair of member sessions is separated by at least 20 completed
  sessions.

`M` is the middle sorted price for an odd member count and the arithmetic mean
of the two middle prices for an even count. A member identity is its source-bar
session and digest; those values break equal-price ties.

Deduplicate identical member sets, then remove any qualifying group whose
members are wholly contained in another qualifying group. Distinct maximal
groups may overlap. For each retained zone, the lower edge is the minimum
member price and the upper edge is the maximum member price. Canonical zone
order is `(lower edge, upper edge, ordered member identities)`. Each zone
records all members and sessions. These rules are normative so independent
implementations produce identical zones.

For an entry price `E` and initial stop `S`, `R = E - S` and the 2R price is
`E + 2R`. A zone is relevant when its upper edge is at or above `E`; only a zone
whose upper edge is below `E` is ignored. If `E` lies within a relevant zone,
including either edge, reject the candidate. Otherwise choose the nearest
relevant zone by the barrier `max(E, lower edge)`, breaking ties with canonical
zone order. Its lower edge must be strictly above the 2R price. Equivalently,
any relevant zone that intersects the closed path from `E` through the 2R price
rejects that entry. If sufficient valid history exists but no relevant zone
exists, the path is clear. Insufficient, unadjusted, malformed, synthetic, or
unverifiable history produces `ABSTAIN`.

The highest acceptable entry imposed by resistance is rounded down to the
greatest valid tick for which the strict clearance rule remains true. A signal
close inside a zone is rejected; it cannot be rescued by lowering the limit.

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

For the cash-funded portfolio arm, the baseline account risk budget is 1% of
current portfolio equity. The independent signal-level arm substitutes its
fixed manifest reference equity as specified below. No 2% baseline, Kelly term,
AI confidence, conviction scalar, or placeholder edge is permitted.

Before the next session opens, choose the largest whole-share quantity `q`
using the submitted limit price `L` as the worst permitted entry price:

```
q × (L - initial stop)
+ modeled entry costs(q)
+ modeled stop-exit costs(q)
<= 0.01 × current portfolio equity
```

Costs include the configured IBKR commission floors, applicable exchange
charges, and modeled entry and stop-exit slippage. Quantity must be at least two
shares. The stop is fixed by chart structure; sizing may never move it. The
submitted quantity is never increased after the opening fill is known.

After a fill, actual price risk per share is `actual fill - initial stop`. The
1R target and lifecycle geometry use that actual value, while the primary
promotion return uses the risk known before the open. Record both:

```
R_order = net P&L / [filled quantity × (submitted limit - initial stop)]
R_fill  = net P&L / [filled quantity × (actual fill - initial stop)]
```

Costs remain in net P&L and are not added to either price-risk denominator.
`R_order` is the primary signal-level expectancy, WCR-S inference, profit-factor,
and concentration unit. `R_fill` is an execution and tail-risk diagnostic. A
trade-by-trade minimum of the two is a declared stress diagnostic only; it is
not a coherent baseline risk unit and cannot promote. The submitted quantity
remains fixed. Re-evaluate and record the actual-fill cost/risk result and
classify resistance as `POST_FILL_RESISTANCE_CLEAR`,
`POST_FILL_RESISTANCE_INSIDE_ZONE`, or
`POST_FILL_RESISTANCE_PATH_BLOCKED`.

A gap down can make a zone that was below the limit relevant to the actual
fill. That is an executable market outcome, not a corrupted replay. Keep the
trade in the baseline and report the diagnostic. An exclusion sensitivity may
show what would have happened without post-fill-blocked trades, but it is not
executable under the approved pre-open order model and cannot promote. Mark the
run `INVALID` only for an impossible or corrupt event, such as a buy fill above
the limit, at or below the structural invalidation, or derived from invalid
source data.

The primary edge report uses a per-pattern signal-level arm independently of
capital competition. It uses one fixed reference equity recorded in the run
manifest, normally the run's starting equity, for every eligible trade. Its 1%
risk budget does not compound. Within one pattern and symbol, accept the first
unique pattern event and suppress later events until that isolated lifecycle
closes; suppressed overlaps remain in decision evidence and do not increase
the promotion trade count. Simultaneous signals from different patterns remain
in their separate hypothesis samples. The portfolio replay separately
compounds actual current equity. It is long-only, fully cash-funded, and uses
no borrowing, leverage, or margin. Existing positions reserve their purchase
cost.

When simultaneous entries require more cash than is available, scale all their
risk budgets by the same factor, recalculate and round quantities down to whole
shares, and remove allocations below two shares. Repeat until the batch is
cash-feasible. Do not rank symbols with a score absent from the methodology.

Phase 2 deliberately adds neither a per-position notional cap nor an arbitrary
minimum stop distance. The source methodology's aggregate appetite controls
are reported but do not change strategy-edge decisions. Their integration
belongs to Phase 4, where concentration limits, aggregate-risk controls, and a
minimum acceptable stop distance or cost-to-risk threshold will be selected.
Until then, the uncapped cash-funded portfolio is an engineering concentration
and gap-risk stress case, not a deployable portfolio forecast and not eligible
for promotion-tier development, validation, or holdout access.

Phase 4 freezes its risk rules from structural quantities without seeing any
real strategy outcome. Permitted inputs are signal-time stop distances,
notional exposures, cost-to-risk ratios, contemporaneous liquidity, pattern
frequency, candidate rejection counts, strategy-independent overnight-gap
data, corporate-event incidence, and synthetic mechanical fixtures. Forward
returns, fills, exits, P&L, R, MFE, MAE, win rate, profit factor, and drawdown
remain blinded until the declaration protocol in Section 16 is complete. Once
Phase 4 is frozen, all promotion-tier development and validation evidence is
computed afresh under its final sizing, commission, liquidity, and eligibility
fingerprint.

A 2% account-risk replay is a declared portfolio-risk sensitivity. It is
reported separately, cannot replace the 1% baseline, and cannot promote a
pattern or portfolio.

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

Record `fill_initial_risk_dollars` as
`filled quantity × (actual entry fill - initial structural stop)` and
`order_initial_risk_dollars` as
`filled quantity × (submitted limit - initial structural stop)`. Net P&L is
the total across every exit leg and eligible dividend after commissions,
exchange charges, and slippage. Divide it by the order denominator for primary
`R_order` and by the fill denominator for diagnostic `R_fill`. For example,
equal halves exited at actual-fill +1R and +2R produce +1.5 `R_fill` gross
before costs; their `R_order` depends on the submitted limit. Splits adjust
quantity and prices so both initial risk-dollar denominators are preserved.

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
  limit, at the quantity fixed before the open.
- An entry open above the limit or at/below structural invalidation cancels the
  instruction.
- A valid gap-down fill remains a trade even when the actual-fill resistance
  diagnostic is inside-zone or path-blocked.
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
- cash-dividend events with declaration, ex, record, and payment dates;
- symbol changes, suspensions, index membership, and delisting outcomes; and
- an integrity manifest with hashes and coverage diagnostics.

Indicators and pattern geometry use split-normalized data. Fill and commission
calculations use prices and quantities as traded. Splits and consolidations
adjust open quantities, cost basis, stops, and pending orders without creating
P&L. Every consolidation in a promotion shard must state `fractional_rule`
(`round_down`, `round_half_up`, `round_half_even`, `round_up`, or
`cash_in_lieu`). Cash-in-lieu requires an exact non-negative
`cash_in_lieu_price` per fractional share; the
typed event retains both facts. Engineering replay may mark an unmodeled
fractional holding `INVALID`; promotion cannot silently infer a rule or
proceed with an unmodeled settlement.
A position is entitled to a cash dividend only when it holds the shares at
the close immediately before the ex-dividend session. Accrue a dividend
receivable and attribute it to trade P&L once on the ex-date; convert the
receivable to spendable cash on the payment date without creating more P&L. A
purchase on or after the ex-date has no entitlement. An unpaid receivable
remains a separately valued portfolio asset and cannot fund entries.
If its payment date lies beyond a development or validation boundary, that
partition closes with the receivable asset at face value and does not read the
next shard merely to settle cash.
Dividend-back-adjusted prices are not used for signals or fills.

The historical `SwingMarketEvent` types deliberately do not reuse the existing
`qat.domain.corporate_actions` operational classes. That package stores broker
announcements as floats, reads live positions and orders, and can modify broker
state. The promotion dataset adapter may normalize the same underlying vendor
facts, but it must map them into immutable exact-decimal/rational replay events.
The authoritative research path cannot import the operational detector,
adjuster, announcement store, or monitor.

Promotion history is physically sharded into complete-calendar-month signal
windows and separate outcome tails for development, validation, and holdout.
Every signal window ends with its final permissible entry fill. Its physical
tail contains the next 63 official exchange sessions. Development and
validation are separated from the following signal window by their tails and
any interstitial sessions through that calendar month-end. Interstitial rows
may later be used only as warm-up for the next authorized partition.

Each shard contains its own complete official-calendar ledger and
tradable-session projection, daily bars, membership,
corporate actions, benchmark rows, and point-in-time regime evidence. A public signed catalog
contains shard identities, boundaries, and hashes but no sealed observations.
Development and validation processes have no filesystem or decryption access
to later signal or tail shards. A partition-aware loader validates only
authorized shards; it must not open a later shard merely to calculate its hash.
The operator-controlled data service verifies each sealed shard against the
catalog when access is granted.

Before signing a shard, the packager checks every official tradable session
for a raw traded bar for each point-in-time member and each symbol held in the
deterministic preflight replay. A documented halt or unresolved delisting
accounts explicitly for an untradeable held symbol; a halt does not remove
index membership. An unexplained gap refuses packaging. If one nevertheless
reaches an open position during replay, the run remains `INVALID`; no price is
invented or carried forward without a documented halt.

Strict authoritative decisions require verified split-only provenance for all
analytical prices used by daily and weekly EMA, ATR, candle and pattern
geometry, structural stops, resistance, and raw-to-analytical conversion.
Bull-flag and double-bottom volume rules additionally require verified volume
provenance. Historical execution requires raw as-traded OHLC, while lifecycle
accounting requires auditable corporate actions. `VENDOR_ADJUSTED` data that
cannot distinguish split and dividend transformations fails these requirements;
strict mode records typed abstentions rather than producing a trade.

Promotion data must provide realizable delisting proceeds or another explicit,
auditable terminal outcome. A silent disappearance is a dataset integrity
failure. When a position becomes untradeable, keep it through its authorized
tail. During a halt or suspension, baseline equity uses the last traded close
and flags that stale mark on every official trading session until trading
resumes. A point-in-time index member may have no traded bar during a
documented halt without losing membership. The halt itself neither schedules
an exit nor stops the official-session holding clock. Any time or close-based
exit already due waits for the first executable resumed open; normal gap-stop
priority applies there.
Close-based invalidation and trailing-stop updates resume with the first
post-halt completed close. If the position remains untradeable at `T64`, close
it at documented irrevocable proceeds or, absent such consideration, zero.
The baseline does not mark a mere halt to zero at onset or infer its eventual
length at onset. Zero-at-onset belongs only to the separately reported
structural stress sweep. Apply these rules identically to development,
validation, and holdout.

Missing, partial, synthetic, conflicting, or unverifiable required data yields
`ABSTAIN`. A symbol-specific defect may be isolated while replay continues, but
the run must disclose it. A dataset-wide manifest, calendar, adjustment, or
ordering failure invalidates the entire run.

## 13. Decision evidence

Each evaluated symbol-session emits an immutable decision envelope containing:

- deterministic decision and parent-event identifiers;
- strategy and schema versions;
- signed dataset-catalog and authorized shard identities, strategy-spec hash,
  and runner-build hash/code commit;
- symbol, exchange session, and evaluation timestamp;
- input-bar identities or hashes;
- pattern name or confluence membership;
- every measured value, threshold, and pass/fail result;
- rejection or abstention reason codes;
- resistance-zone members and chosen zone;
- analytical-to-raw split factor and both price bases;
- proposed entry, stop, target, risk quantity, capacity quantity, submitted
  quantity, participation estimate, and modeled costs;
- order and fill initial-risk dollars, `R_order`, `R_fill`, and edge-sample
  eligibility or overlap-suppression reason;
- dividend entitlement, receivable, payment, and cash-settlement evidence;
- actual-fill resistance diagnostic and its zone/path evidence;
- prior state, proposed transition, and resulting state;
- every active exit trigger;
- fill assumptions and ambiguity flags; and
- regime label, probabilities, model version, input cutoff, and input hash for
  analysis only.

Identical semantic inputs must produce the same identifier and content.
Evidence is append-only. Corrected source data creates a new manifest and new
decisions rather than silently rewriting earlier evidence.

## 14. Regime treatment

The approved weekly filter is part of the authoritative strategy. QAT's existing
market-regime classification is not an entry gate in the primary Phase 2 test.

Every trade records the contemporaneous regime for segmented analysis. The
frozen dataset carries a point-in-time regime series containing session, label,
probabilities, model version, input cutoff, and input hash. It is generated by
an expanding-window or walk-forward run that uses no information after the
labelled session. A model fitted on full history cannot backfill regime labels.
The existing QAT regime engine may supply the series only through that frozen
offline procedure. Missing or invalid regime evidence is `UNKNOWN` and cannot
affect entry, sizing, lifecycle, or promotion eligibility. A regime-gated
variant may be reported as a declared sensitivity experiment, but it cannot
replace or alter the primary result. Strategy rotation remains Phase 7 work.

## 15. Universe and evidence tiers

### 15.1 Engineering evidence

Engineering evidence has two explicit lanes:

1. a frozen synthetic split-only golden dataset that produces every pattern and
   exercises entries, cancellations, partial exits, stops, ambiguity,
   corporate actions, diagnostics, and terminal outcomes; and
2. the existing static ASX snapshot in strict provenance mode.

The static snapshot contains 95 files with 500 sessions each, from 26 August
2024 through 14 August 2026. It is marked `VENDOR_ADJUSTED`,
survivorship-biased, missing independent raw prices and corporate-action
lineage, shorter than the three calendar years required for resistance, and
non-promotional. Its strict replay therefore abstains for both provenance and
`INSUFFICIENT_RESISTANCE_HISTORY`. Zero trades are expected and acceptable.
That replay validates loading, disclosure, abstention, and artifact machinery;
the synthetic lane proves complete lifecycle execution.

An optional mechanical diagnostic may treat the static adjusted series as an
analytical proxy and report pattern-qualified counts before resistance plus
`INSUFFICIENT_RESISTANCE_HISTORY`; it must not introduce a shorter resistance
lookback or call those candidates trades. Report the raw count, candidates per
1,000 eligible symbol-months, and a coverage-scaled ASX 200 planning proxy:
`candidate_rate_per_symbol_month × 200`; also show the unscaled 95-symbol
observed exposure. Resample symbol and calendar-month clusters to publish a
planning range. This is an upper-bound
procurement diagnostic from a survivorship-biased sample: a low rate can show
that procurement is implausible, while a high rate cannot establish final
trade frequency, power, or edge. It uses a distinct mode and evidence
namespace, cannot emit authoritative decisions, and cannot satisfy any
promotion gate.

Phase 2 engineering may inspect synthetic fixture outcomes. It may inspect
static-cache signal-time geometry, frequency, and rejection counts, but it must
not use static-cache forward returns, fills, exits, P&L, R, MFE, MAE, win rate,
profit factor, or drawdown to select a Phase 4 risk rule. No promotion-grade
development or validation observation is released during Phase 2.

### 15.2 Promotion evidence

Promotion-grade evidence requires:

- point-in-time ASX 200 membership;
- entrants, exits, symbol changes, and delisted securities;
- split-normalized OHLCV and auditable corporate actions;
- at least ten years, or the longest complete period available with the
  shortfall stated explicitly; and
- a signed catalog with frozen, hashed physical shards.

Acquiring a commercial historical source is a later procurement decision. The
implementation must expose a source port and must not encode one vendor's
schema into the strategy engine.

A separately signed reference-data view may be released before the strategy
declarations. It carries pseudonymous issuer identity, exposure-window start,
eligibility, index-membership and market-cap/liquidity bucket labels,
corporate-event category and onset, consideration category, and hashes back to
custodian records. It contains no daily OHLC path, exact market-cap or
traded-value path, strategy signal, or forward strategy outcome. Its history
ends before holdout; a ten-session exposure window that would cross the
holdout start is excluded. Before returning the view, the custodian records a
signed `REFERENCE_VIEW_RELEASED` receipt binding its schema, row and issuer
counts, maximum included session, source-record hashes, output hash, catalog,
and release identity.

## 16. Validation protocol

### 16.1 Phase boundary and blind design inputs

Phase 2 ends with engineering evidence and status
`PORTFOLIO_RISK_DESIGN_PENDING`. It does not open promotion-grade development,
validation, or holdout observations. Phase 4 freezes its notional,
stop-distance, cost-to-risk, aggregate, and liquidity rules before the first
promotion-tier outcome. The only real-market Phase 4 inputs are the signed
reference view and a blinded structural extract produced by a reviewed
custodian process from the development shard.

The structural extractor may return only signal-time stop distances, pattern
and candidate counts, contemporaneous rejection reasons, price/liquidity
buckets, cost-to-planned-risk values, quantities, notional exposures, and
frequency by pattern and complete calendar month. It cannot return raw rows,
identifiers that join to later observations, post-signal prices, fills, exits,
P&L, R, MFE, MAE, win rate, profit factor, or drawdown. Its code, schema, input
shard, and output hashes are recorded as `DEV_STRUCTURE_DERIVED` before the
operator sees the aggregate. Strategy-independent overnight-gap and
corporate-event inputs come from the reference view, never from
signal-conditioned forward development outcomes.

### 16.2 Declarations and first development release

Before the first promotion-tier outcome, an operator-controlled Declaration
Authority records these append-only signed declarations:

- `EFFECT_DECLARED`, binding positive `delta_MME` in `R_order` and its economic
  rationale;
- `PROMOTION_PROTOCOL_DECLARED`, binding every edge, tail-risk, data,
  portfolio, and feasibility rule; and
- `METHOD_AUDIT_DECLARED`, binding the inferential method family, complete
  scenario matrix, generators, acceptance caps, code, seeds, and generic pilot
  report.

Each record binds operator identity, strategy-spec hash, catalog identity,
ledger identity, sequence, previous head, UTC time, unique nonce, and a valid
RFC 3161 timestamp token. The signing key and declaration ledger are outside
the repository and unavailable to the runner or automated agent. The generic
method pilot may iterate before declaration only on declared synthetic
families; it cannot use QAT engineering, static-cache, development, or
validation outcomes. Preserve every attempted method and its result in the
hashed pilot report.

A minimal development-release gate holds the development decryption key. It
verifies all three declarations, timestamp tokens, ledger lineage, requested
bundle, and shard identity, then appends signed `DEV_DATA_RELEASED` before
returning a scoped development handle. Before declarations it may run only the
reviewed structural extractor. Validation receives its own
`VALIDATION_DATA_RELEASED` receipt only after development artifacts and the
fingerprint are locked.

Development data is reusable for declared development work, but access is not
an unlogged bearer capability. Every open is scoped to a reviewed bundle and
fingerprint and records `DEV_DATA_OPENED`.

A repair is semantics-preserving only when the strategy specification,
eligibility, calendar contract, numeric policy, costs, sizing, and inferential
method are unchanged and the patch restores behavior already determined by
that frozen contract. Before replacement data access, the operator must approve
a defect dossier containing a pre-patch failing conformance test or independent
reference oracle, the predeclared affected input/output scope, discovery time
and actor, discovery channel, data tier and outcomes already visible, the
original symptom and hypothesis, failed-run identity, exact diff, old and new
bundle hashes, and the expected differential-artifact digest. Frozen fixtures
and replay artifacts outside the approved scope must remain byte-identical;
changed outputs inside it must match the independent oracle. Determinism,
prefix invariance across bars, membership, corporate actions and calendar,
reference parity, isolation, and the complete regression suite must pass.

An outcome anomaly may reveal a real defect, but the examined outcome and its
role in discovery remain recorded permanently. It receives same-lineage
`DEV_RERUN_AUTHORIZED` only when the frozen contract and independent oracle
prove the correction without choosing a favorable result. Otherwise it begins
a new declaration lineage. No new parameter, threshold, exception, data-driven
branch, or strategy, eligibility, calendar, numeric, cost, sizing, or inference
change qualifies as semantics-preserving. After holdout `DATA_OPENED`, a changed
bundle cannot regain freshness under this rule.

`DEV_RERUN_AUTHORIZED` binds the signed defect dossier, failed run, exact code
diff, replacement bundle, unchanged specification, permitted changed artifacts,
and comparison results. Prior outcomes remain disclosed as examined.
`DEV_STRUCTURE_DERIVED` is reusable only when its extractor dependency-closure
hash, schema, source shard, and numeric/data policies are byte-identical. Any
affected dependency change requires a new structural extract and receipt.

### 16.3 Chronological windows and outcome tails

The initial promotion history uses complete-calendar-month signal windows in a
50/20/30 development/validation/holdout allocation. The ten-year minimum
applies after tails are removed. Each partition additionally reserves 63
official sessions after its final entry fill, so a nominal ten-year dataset
normally needs about 189 more sessions plus warm-up. If feasibility later
extends holdout forward, development and validation and the holdout start remain
fixed; the final holdout share may exceed 30%. Examined validation observations
can never become holdout.

Use these exact boundary identities for every partition:

```text
T0   final permissible instruction close
T1   final permissible entry fill; holding session 1
T10  holding session 10 close
T11  scheduled time-exit open
T2..T64  the 63-session physical outcome tail
T64  terminal valuation session
T65  first official session after the physical tail, when one exists
```

The entry-fill window ends on the final official session of a complete calendar
month. No instruction may produce a fill after `T1`. Partition ownership is by
entry-fill session. A normal tenth-session exit completes at `T11`; a halt,
suspension, delisting, or delayed corporate action may resolve through `T64`.
Tail rows cannot create entries, increase `N`, create edge observations, or
extend the signal window. Sessions from `T65` through the next month-end are
interstitial: they remain ineligible and may become warm-up only after the next
partition is authorized. No partition counts as available until its complete
tail is acquired, sealed, catalogued, and hashed. Holdout therefore cannot end
at the present.

All eligible outcomes remain in the denominator. `BOUNDARY_CENSORED` exclusion
is forbidden. Unresolved positions receive the Section 12 terminal rule at
`T64`; missing data that prevents that rule is `INVALID`. Later recovery and
terminal-outcome influence are reported as sensitivities but cannot override
the conservative primary result. If the recovery sensitivity passes every
otherwise applicable gate while the conservative terminal valuation causes the
primary result to fail, classify the result
`TERMINAL_OUTCOME_SENSITIVE`. It is non-promotable and is not converted to
`PASS` by later recovery.

### 16.4 Corporate-event incidence and structural risk preflight

Estimate terminal-event incidence independently of strategy outcomes. A
qualifying event is administration, receivership, liquidation, cancellation of
ordinary equity, delisting without irrevocable consideration, or a suspension
lasting beyond `T64`. Short halts and known nonzero consideration are not zero
events; vendor omissions are data failures.

Use broader ASX ordinary-equity history only inside the point-in-time market-cap,
price, and liquidity support of the eligible strategy universe. Include former
members and delisted names. At each eligible ten-session window start, freeze
membership and the market-cap/liquidity bucket and count a qualifying onset in
the next ten sessions even if eligibility later deteriorates. No exposure
window may cross holdout start.

Start with four predeclared buckets: smaller/larger market capitalization crossed
with lower/higher traded-value liquidity. Split at exposure-weighted medians of
the eligible strategy universe. Each effective bucket requires 500 unique
issuer-years and 100 distinct issuers. Merge insufficient liquidity bands
within market-cap band, then merge market-cap bands, following the declared
rule without looking at event counts. Observations outside common support have
zero primary weight and form a separate micro-cap sensitivity.

For eligible window start `(i,t)`, define `Y[i,t]=1` when an event begins within
the next ten sessions and estimate `sum(Y)/eligible_window_starts`. Use the
larger of the one-sided 95% issuer-year clustered-bootstrap upper bound and an
exact upper bound from non-overlapping ten-session landmark windows. When fewer
than five issuer-year event clusters exist, the exact landmark bound binds.
Primary weights use development/validation entry counts and bucket labels only,
never outcomes. The mandatory audit also shifts 25 percentage points of weight
to the highest-risk bucket; all-trades-in-that-bucket is a sensitivity.

If the predeclared merge path cannot produce an effective bucket with at least
500 unique issuer-years and 100 distinct issuers, return
`INCIDENCE_DATA_INSUFFICIENT`. Publish the available support and merge path,
stop probabilistic tail calibration, method/power work, and holdout-duration
planning, and do not issue a promotion permit. The deterministic design-envelope
diagnostic may still be reported, but it cannot repair missing incidence data.

Before power or duration planning, use the frozen Phase 4 sizing rules to run a
structural preflight. For every cash-funded trade, place a zero-price onset at
each official session on which the position was exposed, recompute the equity
path, and require the worst funded trade/session placement to keep maximum
drawdown at or below 20%. Signal
trades excluded by cash competition remain in signal-level tail reports but do
not create portfolio loss. The structural envelope is
`1 - (1 - ordinary_drawdown_budget) * (1 - zero_price_loss)`; Phase 4 must set
its notional and aggregate caps with enough room under the same 20% limit.
Correlated market/sector events enter the probabilistic simulation and Phase 4
aggregate/sector caps; a deterministic simultaneous two-issuer zero is a
sensitivity.

Failure stops planning as `PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE`. It must not
trigger a recommendation to buy more holdout data. If refreshed development
and validation fail this preflight, close the lineage without opening holdout.
Any Phase 4 risk-policy revision requires a new
`PROMOTION_PROTOCOL_DECLARED` lineage and new receipts binding the revised
specification, bundle, and fingerprint; unchanged effect and method declarations
are re-signed into that lineage rather than silently reused. Re-run the
structural extract when its dependency closure changed, then replay development
and validation from the beginning. The sealed holdout remains untouched and
eligible only when no holdout byte was opened and its catalog/window remains
unchanged; feasibility and every permit input must be recomputed.

### 16.5 Method audit, power, and frequency feasibility

**Operator amendment, 4 October 2026 (F1, Option 1 — predeclared method candidates):**
Before any promotion-tier development outcome is released,
`METHOD_AUDIT_DECLARED` initially proposed three production inference
candidates: (1) entry-month WCR-S; (2) WCR-S on fixed consecutive
three-month quarter clusters; and (3) an aligned block-cluster wild bootstrap
with one declared block length `L` in complete calendar months. Block origin,
partial-block treatment, `L`, seeds, scenario identifiers and generators,
and the candidate set are declaration fields. No candidate, block length, or
scenario may be added or removed after development data is released. The
operator selects a method only by the rule below, never by inspecting holdout
outcomes. This amendment supersedes the single entry-month method assumption.

The initial three candidates test the intercept-only mean with restricted scores and CV1
studentization, sharing one tie-safe one-sided p-value computation and the
same Romano–Wolf stepdown path across patterns. Under this null there are no
free nuisance regressors: each restricted score is the cluster sum of
observations minus its count times the null mean, consistent with
[MacKinnon, Nielsen, and Webb (2023), Table 1 and Eq. 37](https://doi.org/10.1002/jae.2969).
The cluster definition and its aligned Rademacher weight matrix change by
candidate; each candidate uses common weights across patterns and the paired
audit uses identical outer draws and declared weight matrices for every
candidate. A bootstrap statistic equal to the observed statistic counts as an
exceedance. Enumerate all `2^G` sign vectors exactly when `2^G` does not
exceed the declared inner-draw count; otherwise apply the declared relative
tolerance to the comparison. Both confidence inversion and Romano–Wolf use
this rule. The attainable one-sided p-value floor is `1 / 2^G`. Reaching
both the 2.5% confidence gate and 5% family gate requires at least six
nonempty clusters per pattern: five yield `1/32 = 3.125%`, whereas six
yield `1/64 = 1.5625%`. A candidate below this floor is ineligible before
size or power comparison.

**Operator amendment, 7 October 2026 (final pre-declaration Holm candidate):**
The completed generic pilot found the initial three candidates inadequate.
Aligned block `L = 4` passed the confidence-size cap in all 28 generic
mandatory cells but exceeded the family-size cap under mean and combined
dependence stress. Before any further result, the operator added exactly one
final candidate: the same aligned four-month WCR-S test and 97.5% lower
confidence bound, with one-sided Holm stepdown at 5% family-wise error instead
of Romano–Wolf. Apply Holm to the three patterns' own tie-safe WCR-S p-values,
sorted ascending with deterministic name ordering for ties; multiply each
ordered p-value by its remaining hypothesis count, cap at one, and take the
running maximum. The WCR-S cluster frame, CV1 statistic, weights, exact sign
enumeration, and p-value calculation do not change. With a 36-month frame,
nine aligned clusters enumerate all 512 sign vectors.

Run this candidate on the same seeds, outer draws and weight matrices as the
existing `L = 4` candidate in all 28 generic mandatory cells: volatility
regime, return-baseline AR(1), AR(1) mean stress 0.25, and combined volatility
0.4524 plus mean stress 0.25, each with the seven null configurations. Retain
the 20,000/100,000 sequential rule and 3.25% confidence and 6% family upper
95% Monte Carlo caps. If every cell passes both gates, this is the only
qualifying candidate; update the unsigned method draft accordingly. If any
cell fails, status is `METHOD_INADEQUATE`; make no further candidate,
threshold, or dependence change and hold for operator closure of Phase 2
promotion work under the current evidence standard. No new power-ranking grid
is run for one candidate; power remains blinded until `EFFECT_DECLARED`.
Passing this size audit would validate a holdout test, not predict its success.
Nine clusters imply a duration-planner requirement likely beyond 36 months.
This amendment supersedes the initial three-candidate limit and the common
Romano–Wolf requirement only for the added candidate.

The mandatory matrix consists of predeclared development/validation-calibrated
block-resampled scenarios, zero-mean volatility-regime scenarios calibrated to
the market proxy's monthly realised-volatility persistence, and joint-pattern
AR(1) monthly mean shocks bounded by observed index-return dependence. Include
the explicit positive AR(1) coefficient 0.25 as a mandatory stress outside
that observed return bound. Constant mean shocks lasting one through four
months are sensitivities, not mandatory dependence evidence.
Calibrate persistence on the observable quantity. For lognormal volatility
`exp(0.6 Z - 0.6²/2)`, convert the observed volatility lag-one target 0.4524
to the latent Gaussian AR(1) coefficient
`log(1 + 0.4524 × (exp(0.6²) - 1)) / 0.6²` (about 0.497263). For AR(1)
monthly-average outcomes, center iid trade residuals within each month and
multiply by `sqrt(n/(n-1))` when `n > 1` before adding `0.35` times the common
AR(1) state. This preserves unit trade-residual variance while making the
monthly average's lag-one target −0.0874 or the explicit +0.25 stress.
Generate the exact month-specific trade count before centering.
That proxy uses at least ten years of ASX 200 or All Ordinaries monthly index
returns, absolute returns, and realised volatility; it reports lags 1 through
12, half-lives, and the recommended mandatory persistence set without using
strategy outcomes, static-cache trade results, or promotion shards. If the
repository lacks suitable index history, the operator must approve a source
before this field can be finalized. Longer persistence remains a disclosed
sensitivity; 12-month persistence cannot be a mandatory pass requirement for
a 36-month holdout with these candidates. Mandatory cells also cover observed
and stressed cluster imbalance, empirical skew, complete and every one- and
two-null configuration, and the calibrated terminal-loss envelope. The broader
`0.2%/0.5%/1%` by `-20R/-50R` contamination grid remains a tail sensitivity
unless its cell lies in that envelope. Recenter the entire mixture to true
mean zero for size, then shift by the declared positive `delta_MME` for power.

The operator-approved source audit in
`docs/phase-2-market-regime-proxy.md` uses ASX published end-month S&P/ASX 200
values from January 2010 through August 2026, return-level RBA F18 and ^AXJO
checks, and the explicit discrepancy rule for July 2014 and September 2023.
The operator approved Yahoo's July 2014 close at one-decimal precision,
5632.9, as the primary value; the ASX 5623.9 is retained as discrepancy
evidence and sensitivity. The same source audit gives realised-volatility
lag-one correlation 0.4524 and monthly-return lag-one correlation −0.0874;
the 0.25 positive mean AR(1) coefficient is a separate stress. It supports
constant one-through-four-month mean-shock sensitivities; 6 and 12 months
remain longer-persistence sensitivities. The unsigned draft fixes `L = 4`
as a predeclared short-block candidate spanning the upper end of those
supported sensitivity durations, aligned from the first complete entry
month of each partition. It records this candidate without activating or
timestamping `METHOD_AUDIT_DECLARED`.

Every eligible candidate is evaluated on the same outer draws and weight
matrices in each calibrated cell. With 9,999 declared inner bootstrap draws,
start each mandatory size cell with 20,000 outer null simulations. Accept
early only when its upper 95% Monte Carlo limit is at least 0.25 percentage
points below the applicable cap; reject early only when its lower limit is at
least 0.25 points above; otherwise extend to 100,000. The confidence false-
positive upper-limit cap is 3.25% against nominal 2.5%; the Romano–Wolf family
upper-limit cap is 6% against nominal 5%. At 100,000, a cell passes only when
its upper 95% limit is no greater than the cap. A candidate qualifies only if
every mandatory size cell passes both applicable caps. Among qualifying
candidates, compare projected fractions for the joint event of one-sided
WCR-S confidence `p < 0.025` and Romano–Wolf adjusted `p < 0.05` at `delta_MME` and one
common declared projection sample size. Rank each candidate by its minimum
projected fraction across mandatory power scenarios and patterns; choose the
highest, breaking exact ties by the larger nonempty cluster count at that
projection size. If none qualifies, return
`METHOD_INADEQUATE`. Preserve every attempt and result in the hashed audit;
no trimmed or winsorized estimand may replace mean `R_order`.

The common 430-trade projection point is conditional: before freezing it,
compare each candidate's rank by minimum projected power across all mandatory
scenario and pattern cells at `N = 200` and `N = 430`, for effects 0.10,
0.15, 0.20 and 0.30. Freeze 430 only when the complete rankings are identical
at all eight points. Report rankings in the review summary and keep raw power
values outside Git. The bull-flag incidence proxy is about 70 pre-resistance
candidates in 36 months, so a 430-trade comparison cannot establish its
pattern-specific frequency feasibility. The generic grid alone cannot freeze
430 while development/validation-calibrated mandatory power cells remain
unresolved.

The chosen candidate then recomputes pattern-specific `N_required >= 100`,
`G_required >= 6`, minimum detectable effect, and at least 80% prospective
power using the maximum requirement across mandatory power scenarios.
`delta_MME` is declared before outcomes and cannot rise to reduce sample
needs. A nonpositive development-plus-validation expectancy refuses holdout.
Thresholds never relax after exposure.

The frequency model contains complete signal-eligible calendar months only,
including genuine zero-entry months. Tail, warm-up, interstitial, and
partition-created partial months are excluded; blocks cannot bridge a tail.
Resample joint pattern-count vectors in 3-, 6-, and 12-month blocks. Define the
low-frequency rate for each pattern as the minimum of its lowest rolling
36-month development rate, full validation-window rate, and one-sided 90%
lower predictive rate. Publish which source binds.

Scan 36 through 120 eligible holdout months separately for each pattern while
resampling the joint count vectors. For each pattern, select its first duration
with at least 90% baseline probability and 80% low-frequency-stress probability
of satisfying both `N_required` and `G_required`. Publish that pattern's expected
and 10th/5th/1st percentile counts. A pattern with no passing duration through
120 months receives `FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON`; one whose required
duration exceeds untouched available data receives `DATASET_INSUFFICIENT`.
Other patterns may remain feasible and continue independently. Extension is
forward-only with unseen observations and a complete new tail.

The feasibility planner and promotion verdict use separate types but one frozen
mapping. Each pattern's `FEASIBLE` status continues to its remaining gates and
is never itself a promotion pass. `DATASET_INSUFFICIENT` and
`FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON` both map to
`INSUFFICIENT_EVIDENCE`; the report retains the exact feasibility reason,
required and available months, that pattern's binding rate source, and whether a
forward extension can help. A method failure maps to `METHOD_INADEQUATE`, and
unsupported incidence maps to `INCIDENCE_DATA_INSUFFICIENT`, before feasibility
is evaluated. At least one pattern must be feasible for a permit. A permit may
include only patterns individually feasible and
passing every other gate; a non-feasible pattern cannot borrow another
pattern's frequency evidence. Engineering-tier
runs still return `PORTFOLIO_RISK_DESIGN_PENDING` as their overall promotion
status while reporting the synthetic feasibility result separately.

### 16.6 Promotion control plane and exposure

The production control plane is built only after Phase 4 rules and the refreshed
development/validation fingerprint are final. The operator signs a complete
read-only promotion bundle containing reviewed source and commit, built wheel,
pinned interpreter, hash-locked wheels/native libraries, configuration,
schemas, entrypoint, SBOM, and reproducibility metadata. Operator review covers
all I/O, dependencies, permit states, raw-data egress, determinism, reference
parity, and failure handling; another model may assist but cannot authorize.

The dataset packager and keys run under a custodian account. Ledger and sealed
data run under a separate non-interactive service account or machine. The
automated agent has no holdout files, keys, promotion account, interactive
shell in that account, network, DNS, clipboard, child-process, broker, or
arbitrary filesystem access. Prefer authenticated named-pipe streaming on one
Windows host or mutually authenticated streaming across hosts. A trusted
artifact writer, not the runner, enforces typed schemas, row/field/file/size
limits, and forbids raw-bar output. Administrators and anyone able to replace
service binaries are outside the protection boundary.

The operator, data custodian, and permit signer may be roles performed by one
human. The required separation is technical: distinct least-privilege accounts,
non-exportable or separately stored signing/decryption keys, service ACLs, and
an automated-agent account that possesses none of them. The runbook must state
when one human fills multiple roles and must not describe that arrangement as
independent human review or dual control.

The ledger uses a scoped chain keyed by strategy, catalog, and holdout window,
with signed head attestations and a global service checkpoint. `SCOPE_RESERVED`
normally expires after 24 hours and never later than 72 hours before data open;
the operator may append `RESERVATION_CANCELLED` or `RESERVATION_EXPIRED`. A
permit binds that reservation, declarations, rehearsal receipt, promotion
bundle, exact shards, numeric/cost/fill/risk policies, power and duration
requirements, ledger identity/head, nonce, and approval time.

The exact bundle must first complete a holdout-scale synthetic rehearsal through
the deployed packager, ledger, sealed-data, and artifact services. Inject every
service-step failure, insufficient disk, stream interruption, runner death, and
final-append failure. Bind runner, service, packager, schema, configuration,
environment, fixture, and rehearsal-ledger hashes into the receipt. Any change
expires it.

Ledger state progresses through `EXPOSURE_RESERVED`, `DATA_OPENED`, then
`COMPLETED`, `FAILED_PRE_EXPOSURE`, `FAILED_AFTER_EXPOSURE`, or descriptive
`FAILED_INFRASTRUCTURE_AFTER_EXPOSURE`. The data service records `DATA_OPENED`
before returning any plaintext byte or handle. Before it, cancellation or a
patched build may receive a replacement permit. After it, every crash, sleep,
restart, lease expiry, or infrastructure failure consumes the holdout even when
the writer emitted no result. Phase 2D initially has no checkpoint resume. An
exact-bundle rerun is reproduction-only; any changed bundle needs fresh data.

The runbook records rehearsal p50/p95/p99 runtime, peak memory/disk, lease,
safety margin, host sleep/update controls, and permanent post-open failure
consequences. A future checkpoint design requires a new threat model and must
prove kill/resume artifacts byte-identical to uninterrupted output.

### 16.7 Full-history diagnostic

A full-history replay reads holdout observations and remains behind the same
permit and ledger. It may run only after the authorized holdout result exists,
with the identical frozen fingerprint, and is labelled a post-holdout portfolio
risk diagnostic. It cannot feed rule, threshold, or model changes. No parameter
optimization is part of Phase 2; declared sensitivities remain secondary.

## 17. Verification layers

Verification proceeds in this order:

1. **Canonical calculation tests** for decimal parsing and serialization,
   reduced rational factors, recurring-ratio conversion and quantization, EMA,
   Wilder ATR, tick normalization, weekly aggregation, liquidity capacity,
   monotone costs, and maximal bisection sizing.
2. **Pattern examples and counterexamples** for every individual rule, boundary,
   missing-data case, and tie-break.
3. **Golden lifecycle scenarios** covering entry gaps, cancellations, stops,
   targets, ambiguous bars, partial exits, runner ratchets, invalidations, time
   stops, splits, ex-date dividend entitlement, payment-date settlement,
   suspensions, and delistings.
4. **Determinism tests** proving identical inputs produce identical evidence and
   repeated events cannot duplicate an order or fill.
5. **Prefix-invariance tests** proving the decision at session `t` is identical
   when later bars are absent or arbitrarily changed, including membership,
   corporate-action, point-in-time regime, calendar, and weekly-boundary
   inputs.
6. **Independent reference tests** comparing rational price conversion, tick,
   EMA, ATR, resistance, bisection sizing, WCR-S, Romano-Wolf, incidence, and
   duration-planner results with small test-only implementations that share no
   production helpers or decimal context.
7. **Isolation tests** traversing transitive internal imports and proving the
   Phase 2 research path cannot reach broker, OMS, autonomy, network, DNS, or
   process-launch interfaces. Runtime tests deny sockets and subprocesses in
   addition to spying on known client libraries.
8. **Synthetic engineering replay** exercising every strategy and lifecycle
   path on split-only golden data.
9. **Strict static-cache replay** validating provenance abstentions and
   disclosures, even when it produces zero trades.
10. **Promotion evidence replay** on frozen point-in-time development and
    validation shards only after declarations and their signed release receipts;
    holdout and authorized full-history replay additionally require an
    operator-signed permit and unused scoped-ledger reservation.

Tests use fixed clocks, official exchange calendars, and immutable fixtures.
They must not depend on the machine's current date, network state, or changing
vendor responses.

## 18. Reports and artifacts

Every run produces machine-readable JSON and CSV evidence plus a concise human
report, tied to deterministic checksums. Report separately:

- EMA20 pullback, bull flag, and double bottom;
- combined confluence portfolio;
- non-overlapping signal-level `R_order` outcomes and diagnostic `R_fill`
  outcomes;
- fully cash-funded portfolio outcomes;
- development, validation, and holdout periods;
- baseline and predeclared volume, fill-order, doubled-cost, post-fill
  resistance-exclusion, liquidity/impact, regime, and 2% sizing sensitivities;
  and
- static-universe and promotion-grade evidence tiers.

Metrics include eligible and overlap-suppressed trade counts, net expectancy in
`R_order`, diagnostic `R_fill` expectancy and tails, confidence interval, win and
loss distribution, profit factor, maximum drawdown, exposure, turnover, holding
time, cost drag, cost-to-risk ratio, maximum favorable and adverse excursion,
maximum and average single-position notional exposure, days above declared
concentration levels, gap loss beyond planned 1% risk, regime segmentation,
symbol/year/trade concentration, liquidity participation, capacity binding,
price impact, post-fill resistance classifications, rejections, abstentions,
and ambiguous-bar impact. Portfolio drawdown is reported for holdout,
validation plus holdout, and—only after authorized holdout evaluation—the
full-history baseline. Full-history drawdown is a risk diagnostic, not an
unbiased estimate of edge.

Compare portfolio results with an ASX 200 accumulation or equivalent
total-return benchmark over identical sessions. The benchmark source and
transformation belong in the run manifest.

## 19. Promotion gate

Each pattern is assessed separately; a weak pattern cannot hide inside combined
results. Promotion from research authorizes later shadow testing only. It does
not authorize paper orders, autonomous action, or live money.

The per-pattern, non-overlapping signal-level arm supplies trade count,
`R_order` expectancy, confidence, profit factor, cost stress, and concentration
for the seven edge gates. The cash-funded arm supplies allocation, exposure,
drawdown, and final portfolio safety. Cash competition cannot remove a valid
signal from the edge sample, and a suppressed same-pattern/same-symbol overlap
cannot increase `N_required`.

The seven edge gates are conjunctive; they define one hypothesis and require no
correction among themselves. All must pass on the post-Phase-4 frozen baseline:

1. at least the frozen `N_required` completed holdout trades, where
   `N_required >= 100`, and at least the frozen `G_required` nonempty
   entry-month clusters;
2. positive net `R_order` expectancy after modeled costs;
3. the 97.5% one-sided lower bound under the selected declared candidate for mean `R_order`
   is above zero and the selected method's adjusted one-sided family p-value is below 0.05;
4. profit factor is at least 1.20;
5. expectancy remains positive with doubled slippage and commission
   assumptions;
6. results are not dominated by one symbol, year, or small group of exceptional
   trades; and
7. the declared method audit, power and duration plan, minimum 36 complete
   signal-eligible holdout months, Phase 4 risk profile, signed declarations,
   permit, rehearsal, first-exposure ledger receipt, and locked partition
   protocol are satisfied.

For the confidence gate, group eligible signal-level trades by the selected
declared candidate’s aligned entry-month, consecutive three-month, or `L`-month
block clusters. Apply its Section 16 restricted wild-cluster method with 9,999
declared inner draws, exact sign enumeration when attainable, and tie-safe
comparison. Invert the one-sided test for the 97.5% lower confidence bound.
Empty pattern clusters in the common holdout frame carry zero score. Zero
trades, undefined variance, fewer than `G_required` nonempty clusters, a
collapsed bootstrap, or any failed mandatory method-audit scenario is
`INSUFFICIENT_EVIDENCE` or `METHOD_INADEQUATE`, never a pass.

EMA pullback, bull flag, and double bottom are three separately promotable
hypotheses. Apply one-sided Romano-Wolf stepdown for the initial three
candidates, or one-sided Holm stepdown for the final aligned-block `L = 4`
candidate, at family-wise error rate 5%. Audit the
complete null and every one- and two-null partial configuration. Order
hypotheses by descending observed statistic for Romano-Wolf, compare each
with the bootstrap maximum over the remaining stepdown set, and enforce
monotone adjusted p-values. Holm orders the three marginal p-values ascending
and enforces the same monotonicity. The combined portfolio is secondary and cannot pass when any
included constituent pattern fails. Sensitivity runs cannot promote.

The concentration gate passes only when net expectancy remains above zero in
all three deterministic leave-out tests:

- remove every trade in the most profitable symbol;
- remove every trade entered in the most profitable calendar year; and
- remove the top 5% of trades ranked by net `R_order`, rounding the removal
  count up.

The report publishes the full symbol, year, and trade concentration
distributions as well as these tests.

Tail and portfolio safety are assessed separately from statistical edge. ES1
and ES5 are reported for signal-level net `R_order` and cash-funded percentage
of entry equity, without an arbitrary ES pass threshold. In the calibrated
probabilistic terminal-event simulation, replace selected exits at event onset
with zero-price outcomes using each trade's submitted limit, stop, quantity,
bucket, costs, and actual portfolio timing. Require the fifth percentile of
simulated mean net `R_order` to remain above zero. An analytical expected-value
calculation must agree within the frozen numeric tolerance.

For the deterministic portfolio test, inject one zero-price outcome into each
cash-funded trade in turn at every official session on which that position is
exposed, beginning immediately after its entry fill and including its baseline
exit session. Non-tradability does not end exposure: a halted position remains
exposed throughout the unresolved interval. If it resumes at `T40` and exits at
that session, candidate onsets include `T40`; if it is terminally closed at
`T64`, candidate onsets include `T64`. The zero mark and unavailable cash remain
in force through `T64`.

**Operator review amendment, 4 October 2026 (F7):** inclusion of the exit session
supersedes the earlier exclusive endpoint; onset at exit removes the scheduled
proceeds in the same exact-decimal sparse ledger. Entry-session exclusion is unchanged.

Build the baseline decisions, fills, position marks, dividends, exit proceeds,
cash ledger, and equity path once. Each placement then applies an exact-decimal
sparse delta stream that removes the affected position contribution, cancels or
replaces its later proceeds and dividends, and preserves the cash lock. It must
not rerun pattern detection, fill resolution, or allocation per placement.
Recompute drawdown only over the affected cached equity suffix or chunks and
take the worst maximum drawdown across all placements. The optimized sweep must
be byte-identical to a brute-force full-ledger reference on frozen fixtures and
on a deterministic stratified production sample covering entry, ordinary exit,
halt, resumption, dividend, and `T64` cases. Record placement count, affected
points processed, reference-sample identities, and parity digest.

A placement at the baseline trough is included when the position was then open;
no typical or preferred placement is used. Require that worst result to remain
no greater than 20%. Do not dilute this gate through trade count or apply it to
unfunded signal-arm trades. The approved cash-funded 1% replay must also have
realized maximum drawdown no greater than 20% in both holdout and authorized
full-history baseline, and the calibrated probabilistic tail simulation's
95th-percentile maximum drawdown must remain no greater than 20%. Phase 4
notional and aggregate caps are part of this fingerprint.

The result state is:

- `PASS` when edge and portfolio safety both pass;
- `FAIL` when an edge requirement fails; or
- `TERMINAL_OUTCOME_SENSITIVE` when only the reported recovery sensitivity
  removes a conservative terminal-valuation failure; or
- `EDGE_PASS_PORTFOLIO_RISK_BLOCKED` when edge passes but portfolio safety
  fails.

The blocked state records evidence of edge but does not authorize shadow
testing. A structural preflight expected to fail cannot consume holdout merely
to produce this state. If a post-exposure Phase 4 change is ever required, the
same holdout can support only a diagnostic rerun; a new promotion claim needs
fresh prospective data.

Failure or insufficient sample size is a valid Phase 2 result. It cannot be
converted into a pass by relaxing a threshold after seeing the evidence.

## 20. Failure handling and operational safety

- All required-data failures are typed and fail closed.
- A run with a dataset-wide integrity failure has status `INVALID` and cannot be
  scored for promotion.
- A run with disclosed symbol-level abstentions remains analyzable, with counts
  and reasons reported.
- Research artifacts are namespaced by strategy version, signed dataset catalog
  and shard identities, cost profile, fill model, and code commit.
- Earlier evidence is never overwritten.
- Reference-view release, declaration, structural-extract,
  development-release, validation-release, reservation, data-open, and
  completion receipts are signature- and timestamp-verified in one lineage.
- Holdout permits and ledger records are signature-verified; a missing,
  invalid, reused, or scope-mismatched permit fails closed before holdout bytes
  are loaded.
- Promotion scoped-ledger identity, sequence, expected head, and signed service
  checkpoint are permit-bound. The
  sealed-data service records `DATA_OPENED` before returning a handle; rolled
  back or caller-created ledgers cannot authorize a run.
- No post-`DATA_OPENED` crash, restart, sleep event, lease expiry, or
  infrastructure classification restores freshness. Phase 2D has no
  checkpoint-resume path.
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
- selection of the Phase 4 notional, minimum-stop, cost-to-risk, sector, and
  aggregate exposure controls;
- production operation of the promotion control plane before Phase 4 rules are
  frozen;
- a 60-day holding horizon;
- regime-gated primary trading or multi-strategy rotation;
- parameter optimization; and
- production-stack parity replay until Option 2 effectiveness is established.

## 22. Acceptance criteria

Phase 2 engineering implementation is complete only when:

1. one deterministic engine implements every baseline rule in this
   specification;
2. all golden, named-session boundary, physical-shard isolation,
   terminal-valuation, prefix-invariance,
   independent-reference, determinism, transitive-import,
   network/process-isolation, and broker-isolation tests pass;
3. the synthetic split-only engineering replay exercises every pattern and
   lifecycle path, while the strict static ASX replay completes with explicit
   provenance and survivorship caveats; zero strict static trades are
   acceptable when every abstention is attributable and reproducible;
4. every decision can be traced to versioned inputs and rule evidence;
5. existing production behavior and the Phase 1 safety invariants remain
   unchanged;
6. implementation documentation records `PORTFOLIO_RISK_DESIGN_PENDING`,
   identifies all provisional evidence, and proves no promotion-grade
   development, validation, or holdout observation was released;
7. the Declaration Authority, blinded structural-extract contract, and
   development-release interface are specified and tested with engineering
   keys and fixtures; and
8. a separate approval occurs before any integration with the live application,
   paper environment, AI layer, or OMS.

Promotion readiness is a later milestone. It additionally requires frozen
Phase 4 risk rules, externally timestamped declarations, refreshed
promotion-tier development and validation evidence, a passing structural and
method audit, feasible untouched holdout duration, the production Phase 2D
control plane, a successful holdout-scale rehearsal, and an unused signed
permit. Lack of any item does not prevent Phase 2 engineering completion, but
it prevents any claim that the strategy has proven edge or is ready for shadow
testing.
