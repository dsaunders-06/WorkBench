# Phase 2 — Authoritative Swing Strategy Design

**Status:** Second revised draft for operator approval, 1 October 2026

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

All calculations use completed ASX sessions in chronological order.

### 4.1 Exact numeric and price bases

Price, money, adjustment-factor, indicator, threshold, risk, and R-multiple
values use decimal arithmetic constructed from source text. Binary floating
point is prohibited in strategy-domain state, evidence, order calculations,
cost calculations, and canonical identifiers. The implementation uses one
versioned decimal precision and rounding context and serializes decimals in a
canonical, non-scientific form. Whole-share quantities and raw share volume use
integers.

Analytical OHLCV, indicators, pattern geometry, and resistance zones use the
split-normalized analytical basis. At the signal session, the candidate entry,
structural invalidation, stop, and relevant resistance edges are converted to
raw as-traded basis with the manifest's auditable split factor. The resistance
test is repeated after conversion and order-price rounding. Pending orders,
fills, commissions, cash, P&L, and position state remain in raw as-traded basis.
Later splits transform open quantities and raw prices without changing value or
initial risk dollars.

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
holdout access. It contains a maximum participation fraction and a
participation-aware price-impact/slippage curve justified from sources outside
the holdout. The values may be selected using development and validation data,
then become part of the holdout fingerprint. Calibration targets execution
capacity and cost realism; it may not maximize strategy returns.

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
1R target, runner accounting, and net-R denominator use that actual value. The
submitted quantity remains fixed. Re-evaluate and record the actual-fill
cost/risk result and classify resistance as `POST_FILL_RESISTANCE_CLEAR`,
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

The primary edge report measures every qualified trade in R independently of
capital competition. It uses one fixed reference equity recorded in the run
manifest, normally the run's starting equity, for every independent trade. Its
1% risk budget does not compound and it ignores capital competition and signal
overlap. The portfolio replay separately compounds actual current equity. It is
long-only, fully cash-funded, and uses no borrowing, leverage, or margin.
Existing positions reserve their purchase cost.

When simultaneous entries require more cash than is available, scale all their
risk budgets by the same factor, recalculate and round quantities down to whole
shares, and remove allocations below two shares. Repeat until the batch is
cash-feasible. Do not rank symbols with a score absent from the methodology.

Phase 2 deliberately adds neither a per-position notional cap nor an arbitrary
minimum stop distance. The source methodology's aggregate appetite controls
are reported but do not change strategy-edge decisions. Their integration
belongs to Phase 4, where concentration limits, aggregate-risk controls, and a
minimum acceptable stop distance or cost-to-risk threshold will be selected
and the portfolio replay rerun. Until then, the uncapped cash-funded portfolio
is a concentration and gap-risk stress case, not a deployable portfolio
forecast.

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

Initial risk dollars are
`filled quantity × (actual entry fill - initial structural stop)`. Net R is the
total net P&L across every exit leg and eligible dividend, after commissions,
exchange charges, and slippage, divided by those initial risk dollars. For
example, equal halves exited at +1R and +2R produce +1.5R gross before costs.
Splits adjust quantity and prices so the initial risk-dollar denominator is
preserved.

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
- cash-dividend events;
- symbol changes, suspensions, index membership, and delisting outcomes; and
- an integrity manifest with hashes and coverage diagnostics.

Indicators and pattern geometry use split-normalized data. Fill and commission
calculations use prices and quantities as traded. Splits and consolidations
adjust open quantities, cost basis, stops, and pending orders without creating
P&L. Eligible cash dividends are credited separately. Dividend-back-adjusted
prices are not used for signals or fills.

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
- analytical-to-raw split factor and both price bases;
- proposed entry, stop, target, risk quantity, capacity quantity, submitted
  quantity, participation estimate, and modeled costs;
- actual-fill resistance diagnostic and its zone/path evidence;
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

Engineering evidence has two explicit lanes:

1. a frozen synthetic split-only golden dataset that produces every pattern and
   exercises entries, cancellations, partial exits, stops, ambiguity,
   corporate actions, diagnostics, and terminal outcomes; and
2. the existing static ASX snapshot in strict provenance mode.

The static snapshot is marked `VENDOR_ADJUSTED`, survivorship-biased, missing
independent raw prices and corporate-action lineage, and non-promotional. Its
strict replay may legitimately produce zero trades when provenance-dependent
rules abstain. That replay validates loading, disclosure, abstention, and
artifact machinery; the synthetic lane proves complete lifecycle execution.

An optional mechanical diagnostic may treat the static adjusted series as an
analytical proxy to estimate provisional pattern frequency. It uses a distinct
mode and evidence namespace, cannot emit authoritative decisions, and cannot
prove an edge or satisfy any promotion gate.

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

- first 50%: development and verification;
- next 20%: validation and declared sensitivity checks; and
- final 30%: locked holdout.

Development and validation remain accessible even when the planned holdout is
too short or underpowered. The validation plan records those shortfalls and
sets `promotion_eligible=false`; it does not prevent engineering, development,
or validation runs. Holdout access remains denied until rules, thresholds,
numeric policy, data processing, liquidity, costs, and fill assumptions are
frozen.

The planned holdout must span at least 36 calendar months. Before it is
unlocked, use development and validation entry-month variability and observed
signal frequency to freeze, separately for each pattern:

- expected mean R used only for prospective power planning;
- required completed-trade count `N_required`, with an absolute floor of 100;
- required nonempty entry-month cluster count `G_required`;
- minimum detectable mean R; and
- projected power under the frozen studentized and multiplicity procedures.

Required prospective power is at least 80% at a 5% family-wise error level. As
a scale check before multiplicity and finite-sample effects, a zero lower bound
requires roughly `1.96 / sqrt(G)` month-block standard deviations: 0.400 for 24
clusters, 0.327 for 36, and 0.283 for 48. The bootstrap simulation, rather than
this approximation, governs the audit. Actual holdout shortfalls return
`INSUFFICIENT_EVIDENCE`; thresholds are never relaxed after holdout access.

Holdout execution requires an operator-signed permit that binds the strategy
and evidence versions, code commit, dataset manifest, exact holdout boundaries,
numeric policy, liquidity/cost/fill profiles, fingerprint, and a unique nonce.
The runner verifies the permit with a configured public key; the signing key is
outside the repository and unavailable to the runner or automated agent. A
computable fingerprint or approval string is not authorization.

An operator-controlled append-only holdout ledger first reserves the signed
permit, strategy lineage, and period before any holdout bytes are loaded, then
appends run identity, artifact hashes, completion status, and reproductions.
An exact-fingerprint rerun may be recorded as
`REPRODUCTION` and cannot create a new promotion claim. A changed fingerprint
cannot evaluate a period already exposed for that strategy lineage. After a
rule change, a fresh holdout means a genuinely unused later period or newly
acquired dataset; relabelling the same bars is forbidden. Any outcome-blind
sequential extension rule must be approved and frozen before first exposure.

Partition ownership is determined by entry session, never exit session. Each
partition starts flat. Earlier bars may be read only as indicator and pattern
warm-up. No new entry may occur before the partition begins or after it ends.
After the final partition session, an outcome buffer continues until all open
positions close, normally within ten additional tradable sessions but longer
when suspensions or delistings require it. The complete outcome remains
attributed to its entry partition. The holdout trade count includes entries in
the holdout whose outcomes complete in that buffer.

A full-history replay reads holdout bars and is therefore protected by the same
permit and ledger. It may run only after the authorized holdout result exists,
with the identical frozen fingerprint, and is labelled a post-holdout portfolio
risk diagnostic. It cannot feed rule, threshold, or model changes.

No parameter optimization is part of Phase 2. Sensitivity values are declared
in advance and remain secondary to the frozen baseline. Results are also
reported by calendar year and recorded regime to reveal instability.

## 17. Verification layers

Verification proceeds in this order:

1. **Canonical calculation tests** for decimal parsing and serialization, EMA,
   Wilder ATR, raw/analytical conversion, tick normalization, weekly
   aggregation, liquidity capacity, and cost-aware sizing.
2. **Pattern examples and counterexamples** for every individual rule, boundary,
   missing-data case, and tie-break.
3. **Golden lifecycle scenarios** covering entry gaps, cancellations, stops,
   targets, ambiguous bars, partial exits, runner ratchets, invalidations, time
   stops, splits, dividends, suspensions, and delistings.
4. **Determinism tests** proving identical inputs produce identical evidence and
   repeated events cannot duplicate an order or fill.
5. **Prefix-invariance tests** proving the decision at session `t` is identical
   when later bars are absent or arbitrarily changed, including membership,
   corporate-action, calendar, and weekly-boundary inputs.
6. **Independent reference tests** comparing tick, EMA, ATR, resistance, sizing,
   and bootstrap results with small test-only implementations that share no
   production helpers.
7. **Isolation tests** traversing transitive internal imports and proving the
   Phase 2 research path cannot reach broker, OMS, autonomy, network, DNS, or
   process-launch interfaces. Runtime tests deny sockets and subprocesses in
   addition to spying on known client libraries.
8. **Synthetic engineering replay** exercising every strategy and lifecycle
   path on split-only golden data.
9. **Strict static-cache replay** validating provenance abstentions and
   disclosures, even when it produces zero trades.
10. **Promotion replay** on the frozen point-in-time dataset, only when an
    operator-signed permit and unused holdout ledger entry exist.

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
- baseline and predeclared volume, fill-order, doubled-cost, post-fill
  resistance-exclusion, liquidity/impact, regime, and 2% sizing sensitivities;
  and
- static-universe and promotion-grade evidence tiers.

Metrics include trade count, net expectancy in R, confidence interval, win and
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

The seven edge gates are conjunctive; they define one hypothesis and require no
correction among themselves. All must pass on the frozen baseline:

1. at least the frozen `N_required` completed holdout trades, where
   `N_required >= 100`, and at least the frozen `G_required` nonempty
   entry-month clusters;
2. positive net expectancy after modeled costs;
3. the 97.5% one-sided studentized entry-month cluster-bootstrap lower bound
   for mean R is above zero and the Romano–Wolf adjusted one-sided p-value is
   below 0.05;
4. profit factor is at least 1.20;
5. expectancy remains positive with doubled slippage and commission
   assumptions;
6. results are not dominated by one symbol, year, or small group of exceptional
   trades; and
7. the pre-holdout power audit, minimum 36-calendar-month holdout, liquidity
   profile, signed permit, valid first-exposure ledger receipt, and locked
   partition protocol are satisfied.

For the confidence gate, group completed trades by their entry calendar month
so simultaneous and nearby signals remain together. Let `N` be trade count,
`G` be month-cluster count, `mean` be mean net R, and
`U_g = sum(R_i - mean)` within cluster `g`. Estimate the cluster-robust standard
error as:

```
SE = sqrt((G / (G - 1)) * sum(U_g ** 2) / N ** 2)
```

Resample whole month clusters with replacement 10,000 times using common
resamples and a seed derived from the run manifest. For each resample compute
`mean*`, `SE*`, and `t* = (mean* - mean) / SE*`. The bound
`mean - q0.975(t*) × SE` is explicitly a 97.5% one-sided lower bound, equivalent
to the lower endpoint of a two-sided 95% interval. A zero or undefined standard
error, fewer than the frozen `G_required` clusters, or another degenerate sample
is `INSUFFICIENT_EVIDENCE`, never a pass.

EMA pullback, bull flag, and double bottom are three separately promotable
hypotheses. Apply a one-sided Romano–Wolf stepdown test at family-wise error
rate 5%, using common entry-month resamples to preserve dependence among
patterns. Use
the union of their holdout entry months as the cluster frame; a pattern may
have an empty cluster in a month. For each pattern use observed
`t = mean / SE` and the null-centered resampled `t*` values already produced by
the studentized bootstrap. Order hypotheses by descending observed `t`, compare
each against the resampled maximum over hypotheses still in the stepdown set,
and enforce monotone adjusted p-values. The combined portfolio is secondary
and cannot pass when any included constituent pattern fails. Sensitivity runs
cannot promote a pattern.

The concentration gate passes only when net expectancy remains above zero in
all three deterministic leave-out tests:

- remove every trade in the most profitable symbol;
- remove every trade entered in the most profitable calendar year; and
- remove the top 5% of trades ranked by net R, rounding the removal count up.

The report publishes the full symbol, year, and trade concentration
distributions as well as these tests.

Portfolio safety is assessed separately from statistical edge. The approved
cash-funded 1% replay must have maximum drawdown no greater than 20% in both the
holdout and full-history baseline to authorize shadow testing. The result state
is:

- `PASS` when edge and portfolio safety both pass;
- `FAIL` when an edge requirement fails; or
- `EDGE_PASS_PORTFOLIO_RISK_BLOCKED` when edge passes but portfolio safety
  fails.

The blocked state records evidence of edge but does not authorize shadow
testing. Phase 4 must introduce concentration controls and rerun the portfolio
safety assessment before promotion can proceed.

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
- Holdout permits and ledger records are signature-verified; a missing,
  invalid, reused, or scope-mismatched permit fails closed before holdout bytes
  are loaded.
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
2. all golden, boundary, prefix-invariance, independent-reference,
   determinism, transitive-import, network/process-isolation, and
   broker-isolation tests pass;
3. the synthetic split-only engineering replay exercises every pattern and
   lifecycle path, while the strict static ASX replay completes with explicit
   provenance and survivorship caveats; zero strict static trades are
   acceptable when every abstention is attributable and reproducible;
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
