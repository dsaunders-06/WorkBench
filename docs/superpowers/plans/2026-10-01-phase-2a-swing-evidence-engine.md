# Phase 2A Swing Evidence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, deterministic rule-and-evidence engine for the approved EMA20 pullback, bull flag, and double-bottom strategy without changing the deployed swing strategy.

**Architecture:** Add an `authoritative_swing` domain package beside the existing `swing.py`. Typed finalized bars enter pure functions; pattern modules return rule evidence; one engine applies common gates, resistance, exact cost/liquidity sizing, and confluence. Calendar and tick schedules are reused, but all Phase 2 price and money arithmetic is decimal and cannot call the existing float-based `CostModel` arithmetic.

**Tech Stack:** Python 3.12, `decimal.Decimal`, `fractions.Fraction`, frozen dataclasses, `StrEnum`, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Do not modify `src/qat/domain/strategies/swing.py` or deploy the new engine.
- Accept finalized daily bars only; invalid, partial, or insufficient data returns typed `ABSTAIN` evidence.
- Keep regime out of entry eligibility; attach it only as analysis metadata.
- Use a Phase 2 exact-decimal cost profile that mirrors the approved IBKR fee
  rules; do not pass price-bearing values through the existing float-based
  `CostModel` methods.
- Use ASX ticks from `qat.data.broker.ticks`; never duplicate the tick table.
- Parse prices from source text into `Decimal`; store split factors as reduced
  integer rationals. Use numeric policy `phase2-decimal-v1`: precision 50,
  `ROUND_HALF_EVEN`, and analytical quantum `Decimal("1E-12")`. Raw share
  volume and quantity are integers. Binary floats are forbidden in semantic
  strategy state and canonical evidence.
- Use strategy version `phase2-swing-v1` and schema version `swing-evidence-v1`.
- All evidence identifiers derive from canonical semantic content and contain no wall-clock value.
- No network, broker adapter/submission, database, UI, scheduler, or AI import is allowed in the new package. The pure exchange-tick utility is permitted.
- Implement the uncapped 1% sizing rule for engineering evidence only.
  Promotion-tier sizing is replayed from the beginning after Phase 4 freezes
  notional, minimum-stop, cost-to-risk, aggregate, and liquidity controls. This
  plan must not open promotion-grade development observations.

## Execution Preflight

Create the ignored local environment with the bundled Python 3.12 runtime:

```powershell
& 'C:\Users\mailm\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
```

The final command must pass before Task 1 changes source. If dependency installation needs network access, request it for the scoped install command.

## File Structure

- `src/qat/domain/strategies/authoritative_swing/model.py` — immutable inputs, decisions, candidates, and rule evidence.
- `src/qat/domain/strategies/authoritative_swing/evidence.py` — canonical serialization and deterministic IDs.
- `src/qat/domain/strategies/authoritative_swing/numeric.py` — decimal context,
  canonical decimal text, raw/analytical conversion, and exact price steps.
- `src/qat/domain/strategies/authoritative_swing/indicators.py` — canonical EMA, Wilder ATR, and completed-week aggregation.
- `src/qat/domain/strategies/authoritative_swing/ema_pullback.py` — EMA rejection pattern only.
- `src/qat/domain/strategies/authoritative_swing/bull_flag.py` — bull-flag pattern only.
- `src/qat/domain/strategies/authoritative_swing/double_bottom.py` — double-bottom pattern only.
- `src/qat/domain/strategies/authoritative_swing/resistance.py` — swing highs, zones, and 2R entry ceiling.
- `src/qat/domain/strategies/authoritative_swing/sizing.py` — exact costs,
  liquidity capacity, and whole-share 1% risk sizing.
- `src/qat/domain/strategies/authoritative_swing/engine.py` — common gates and confluence orchestration.
- `tests/domain/strategies/authoritative_swing/` — tests mirroring each responsibility.

## Review Focus

- A bar marked partial, synthetic, zero-volume where volume is required, or carrying NaN must abstain; Tasks 1 and 8 pin preservation and refusal.
- ASX band boundaries at $0.10 and $2.00 must still place the stop exactly one valid tick below invalidation; Task 2 pins both boundaries.
- A holiday-shortened Friday week must count as complete while the current week remains excluded; Task 2 pins both cases.
- Multiple valid flag lengths and bottom pairs must use the approved deterministic tie-breaks; Tasks 4 and 5 pin them.
- Confluence must recompute resistance and sizing from the conservative combined stop and limit; Task 8 pins rejection after recomputation.
- Canonical identifiers must be unchanged by equivalent decimal spellings and
  future bars; Tasks 1, 2, and 8 pin decimal serialization and prefix
  invariance.

---

### Task 1: Immutable market and evidence types

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/__init__.py`
- Create: `src/qat/domain/strategies/authoritative_swing/model.py`
- Create: `src/qat/domain/strategies/authoritative_swing/evidence.py`
- Create: `tests/domain/strategies/authoritative_swing/__init__.py`
- Create: `tests/domain/strategies/authoritative_swing/test_model_and_evidence.py`

**Interfaces:**
- Consumes: Python primitives only.
- Produces: `Ohlcv`, `FinalBar`, `SwingHistory`, `RuleEvidence`, `PatternCandidate`, `PatternDecision`, `SetupDecision`, `canonical_payload()`, and `stable_decision_id()`.

- [ ] **Step 1: Write failing model-invariant and stable-ID tests**

```python
def test_partial_bar_quality_is_preserved_for_engine_abstention() -> None:
    bar = final_bar(finalized=False)
    history = SwingHistory(symbol="BHP.AX", daily=(bar,))
    assert history.daily[-1].finalized is False

def test_semantically_identical_payloads_have_one_id() -> None:
    left = {"symbol": "BHP.AX", "rules": {"b": 2, "a": 1}}
    right = {"rules": {"a": 1, "b": 2}, "symbol": "BHP.AX"}
    assert stable_decision_id(left) == stable_decision_id(right)

def test_non_finite_evidence_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        RuleEvidence("close", RuleOutcome.PASS, measured=Decimal("NaN"))

def test_decimal_prices_have_one_canonical_identity() -> None:
    assert stable_decision_id({"price": Decimal("10.0")}) == stable_decision_id({"price": Decimal("10.000")})
```

- [ ] **Step 2: Run the focused tests and verify import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_model_and_evidence.py -q`

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Implement the immutable types and canonical hash**

Define these public shapes exactly:

```python
class DataQuality(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    SYNTHETIC = "synthetic"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"

class AdjustmentStatus(StrEnum):
    SPLIT_NORMALIZED = "split_normalized"
    VENDOR_ADJUSTED = "vendor_adjusted"
    UNADJUSTED = "unadjusted"
    UNKNOWN = "unknown"

class DecisionStatus(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    ABSTAIN = "abstain"

class Pattern(StrEnum):
    EMA_PULLBACK = "ema_pullback"
    BULL_FLAG = "bull_flag"
    DOUBLE_BOTTOM = "double_bottom"

class RuleOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"

@dataclass(frozen=True, slots=True)
class Ohlcv:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

@dataclass(frozen=True, slots=True)
class FinalBar:
    symbol: str
    session: date
    raw: Ohlcv
    adjusted: Ohlcv
    source: str
    quality: DataQuality
    adjustment: AdjustmentStatus
    raw_to_adjusted_price_factor: SplitFactor  # reduced numerator/denominator
    finalized: bool
    digest: str

@dataclass(frozen=True, slots=True)
class SwingHistory:
    symbol: str
    daily: tuple[FinalBar, ...]

@dataclass(frozen=True, slots=True)
class RuleEvidence:
    code: str
    outcome: RuleOutcome
    measured: Decimal | int | str | bool | None = None
    threshold: Decimal | int | str | None = None
    reason: str | None = None

@dataclass(frozen=True, slots=True)
class PatternCandidate:
    pattern: Pattern
    pattern_instance_id: str
    breakout_event_id: str | None
    signal_session: date
    analytical_signal_close: Decimal
    analytical_invalidation: Decimal
    analytical_atr14: Decimal
    metadata: tuple[tuple[str, str | int | Decimal | bool], ...] = ()

@dataclass(frozen=True, slots=True)
class PatternDecision:
    pattern: Pattern
    status: DecisionStatus
    rules: tuple[RuleEvidence, ...]
    candidate: PatternCandidate | None = None

@dataclass(frozen=True, slots=True)
class SetupDecision:
    strategy_version: str
    schema_version: str
    decision_id: str
    symbol: str
    session: date
    status: DecisionStatus
    patterns: tuple[Pattern, ...]
    pattern_decisions: tuple[PatternDecision, ...]
    entry_limit_raw: Decimal | None
    initial_stop_raw: Decimal | None
    risk_quantity: int
    capacity_quantity: int
    quantity: int
    input_digests: tuple[str, ...]
    analysis_regime: str | None = None
```

`SwingHistory.__post_init__` rejects mixed symbols and duplicate/out-of-order sessions. It preserves non-finite decimals, finalization, quality, and adjustment states so the engine can emit auditable abstentions instead of losing the evaluated session at ingestion. Evidence output refuses non-finite values. `canonical_payload()` converts finite decimals to one non-scientific normalized string before `json.dumps(..., sort_keys=True, separators=(",", ":"), allow_nan=False)`. `stable_decision_id()` hashes that payload with SHA-256 prefixed by `swing:`.

- [ ] **Step 4: Run tests, type check, and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_model_and_evidence.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing`

Run: `.\.venv\Scripts\python.exe -m ruff check src/qat/domain/strategies/authoritative_swing tests/domain/strategies/authoritative_swing`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing tests/domain/strategies/authoritative_swing
git commit -m "feat: add authoritative swing evidence types"
```

### Task 2: Canonical decimal indicators, price bases, completed weeks, and ASX ticks

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/numeric.py`
- Create: `src/qat/domain/strategies/authoritative_swing/indicators.py`
- Modify: `src/qat/data/broker/ticks.py`
- Create: `tests/domain/strategies/authoritative_swing/test_indicators.py`
- Create: `tests/domain/strategies/authoritative_swing/test_numeric.py`
- Modify: `tests/data/broker/test_ticks.py`

**Interfaces:**
- Consumes: decimal source text, reduced integer split factors,
  `tuple[FinalBar, ...]`, ASX calendar functions, and the existing ASX tick
  schedule.
- Produces: `SplitFactor`, `parse_decimal()`, `canonical_decimal()`,
  `to_raw_price()`, `to_analytical_price()`, `ema(values, period)`,
  `wilder_atr(bars, period=14)`, `completed_weekly_bars(bars)`, and
  `previous_raw_order_tick(price, market)`.

- [ ] **Step 1: Write failing hand-calculated indicator and calendar tests**

```python
def test_ema_is_seeded_by_the_first_simple_mean() -> None:
    assert ema(decimals("1", "2", "3", "4"), 3) == (None, None, D("2"), D("3"))

def test_wilder_atr_uses_previous_close_for_gaps() -> None:
    values = wilder_atr(gapped_bars(), period=3)
    assert values[-1] == hand_calculated_decimal_atr()

def test_current_week_is_excluded_but_christmas_short_week_is_complete() -> None:
    weekly = completed_weekly_bars(daily_fixture_through("2026-12-29"))
    assert weekly[-1].session == date(2026, 12, 24)

@pytest.mark.parametrize(("price", "expected"), [("0.10", "0.099"), ("2.00", "1.995"), ("0.011", "0.010")])
def test_previous_tick_crosses_asx_bands_without_float_drift(price: str, expected: str) -> None:
    assert previous_raw_order_tick(D(price), "ASX") == D(expected)

def test_split_factor_is_reduced_and_conversion_uses_declared_quantum() -> None:
    factor = SplitFactor(3, 10)
    adjusted = to_analytical_price(D("1"), factor)
    assert adjusted == D("0.300000000000")
    assert normalize_reconstructed_raw(to_raw_price(adjusted, factor), D("1")) == D("1")

def test_numeric_policy_is_frozen() -> None:
    assert NUMERIC_POLICY.precision == 50
    assert NUMERIC_POLICY.rounding == ROUND_HALF_EVEN
    assert NUMERIC_POLICY.analytical_quantum == D("1E-12")
```

- [ ] **Step 2: Verify the tests fail on absent APIs**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py -q`

Expected: FAIL because the new functions are absent.

- [ ] **Step 3: Implement exact calculations**

Implement reduced positive integer `SplitFactor` values and reject decimal or
floating adjustment factors in semantic state. Set precision 50,
`ROUND_HALF_EVEN`, and analytical quantum `1E-12` for versioned policy
`phase2-decimal-v1`; construct decimals only from source strings or integers.
Convert price bases through an exact `Fraction` intermediate and quantize once
at the analytical boundary. Test reconstructed raw equality only after the
declared quantum and source/tick normalization; do not require naive decimal
division and multiplication to be identical for recurring ratios. `ema()`
returns one item per input and `None`
before the simple-mean seed. `wilder_atr()` implements spec §4.3 and returns
`None` before its seed. `completed_weekly_bars()` groups official ASX sessions
and includes a group only when the next ASX trading day lies in a later ISO
week. Reuse the existing ASX tick schedule but perform the arithmetic in
`Decimal`. `previous_raw_order_tick()` returns the greatest valid raw order
price strictly below the input, including across tick-band boundaries. Do not
quantize actual auction fills to the ordinary order grid.

- [ ] **Step 4: Run focused and existing tick/calendar tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_numeric.py tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py tests/domain/test_market_calendar.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/numeric.py src/qat/domain/strategies/authoritative_swing/indicators.py src/qat/data/broker/ticks.py tests/domain/strategies/authoritative_swing/test_numeric.py tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py
git commit -m "feat: add canonical swing calculations"
```

### Task 3: EMA20 pullback detector and weekly filter

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/ema_pullback.py`
- Create: `tests/domain/strategies/authoritative_swing/test_ema_pullback.py`

**Interfaces:**
- Consumes: `SwingHistory` and EMA/ATR/weekly calculations.
- Produces: `evaluate_ema_pullback(history) -> PatternDecision`.

- [ ] **Step 1: Write failing positive, boundary, rejection, and abstention tests**

Cover every spec §6.1 condition individually. Include exactly 50 completed weeks, 49 weeks, a wick exactly twice the body, a close exactly at the upper-third boundary, a doji, a touched EMA that closes below it, and the weekly rejection that requires both bearish clauses.

```python
def test_weekly_filter_rejects_only_when_both_clauses_are_bearish() -> None:
    decision = evaluate_ema_pullback(history(weekly_close_below=True, ema20_below_ema50=False))
    assert rule(decision, "weekly_filter").outcome is RuleOutcome.PASS

def test_detector_preserves_analytical_invalidation_before_raw_conversion() -> None:
    decision = evaluate_ema_pullback(valid_history(signal_low="1.995", signal_ema20="2.01"))
    assert decision.candidate is not None
    assert decision.candidate.analytical_invalidation == D("1.995")
```

- [ ] **Step 2: Run and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_ema_pullback.py -q`

- [ ] **Step 3: Implement one rule result per condition**

Return `ABSTAIN` for unavailable indicators/history and `REJECTED` for measured
market conditions that fail. The candidate carries analytical signal close,
invalidation, ATR, split factor, and the signal-bar digest. Raw conversion and
one-tick stop construction occur once in the engine after pattern/confluence
selection.

- [ ] **Step 4: Run tests and static checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_ema_pullback.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing/ema_pullback.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/ema_pullback.py tests/domain/strategies/authoritative_swing/test_ema_pullback.py
git commit -m "feat: detect authoritative EMA pullbacks"
```

### Task 4: Bull-flag detector

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/bull_flag.py`
- Create: `tests/domain/strategies/authoritative_swing/test_bull_flag.py`

**Interfaces:**
- Consumes: `SwingHistory` and canonical indicators.
- Produces: `evaluate_bull_flag(history, volume_multiplier=Decimal("1.5")) -> PatternDecision`.

- [ ] **Step 1: Write failing tests for pole, flag, breakout, and longest-window selection**

Pin the five-session pole, `max(5%, 2 ATR)`, 3/8-session flag boundaries, non-positive least-squares close slope, 50% maximum retracement, lower mean flag volume, strict breakout above flag high, rising EMA20 above EMA50, 20-session preceding volume mean, zero-volume abstention, and longest qualifying flag.

```python
def test_breakout_volume_excludes_the_breakout_session() -> None:
    decision = evaluate_bull_flag(valid_flag(breakout_volume=1_500, prior_mean=1_000))
    assert rule(decision, "breakout_volume").measured == D("1.5")

def test_longest_qualifying_flag_wins() -> None:
    decision = evaluate_bull_flag(history_with_valid_lengths(4, 6, 8))
    assert decision.candidate is not None
    assert decision.candidate.metadata["flag_sessions"] == 8
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_bull_flag.py -q`

- [ ] **Step 3: Implement deterministic window evaluation**

Evaluate candidate flag lengths in descending order from 8 to 3 and return the first fully qualified length. Record failed measurements for the selected structural interpretation and abstain on any required unverifiable volume.

- [ ] **Step 4: Run focused tests and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_bull_flag.py -q`

Run: `.\.venv\Scripts\python.exe -m ruff check src/qat/domain/strategies/authoritative_swing/bull_flag.py tests/domain/strategies/authoritative_swing/test_bull_flag.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/bull_flag.py tests/domain/strategies/authoritative_swing/test_bull_flag.py
git commit -m "feat: detect authoritative bull flags"
```

### Task 5: Double-bottom detector

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/double_bottom.py`
- Create: `tests/domain/strategies/authoritative_swing/test_double_bottom.py`

**Interfaces:**
- Consumes: `SwingHistory` and canonical indicators.
- Produces: `evaluate_double_bottom(history, volume_multiplier=Decimal("1.5")) -> PatternDecision`.

- [ ] **Step 1: Write failing tests for pivots, spacing, neckline crossing, expiry, and identities**

Pin three bars on each side of each strict local low, 5/30-session spacing,
bottom-price difference divided by their mean, neckline strictly between
bottoms, all session-ordered source bars tied at the highest neckline price,
`max(3%, 1 ATR)` neckline depth, and most-recent-pair selection. Require
the immediately preceding completed close to be at or below the neckline and
the signal close to cross strictly above it no later than 20 completed sessions
after the second bottom. Also pin close above EMA20, rising EMA20, volume, the
weekly filter, and that EMA20 may remain below EMA50. Test that a cross before
the second bottom is confirmed cannot become a stale signal while price stays
above the neckline.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_double_bottom.py -q`

- [ ] **Step 3: Implement confirmed-pivot and pair selection logic**

Sort qualifying pairs by second-bottom session descending, then first-bottom
session descending. Derive a stable pattern-instance ID from both bottom
sessions and all neckline source-bar identities. Derive a breakout-event ID by
adding the crossing session. Record the IDs, both bottom sessions and prices,
neckline members, ATR, elapsed sessions, and distance in evidence. Lifecycle
consumption and recross eligibility are enforced in Phase 2B.

- [ ] **Step 4: Run focused tests and type check**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_double_bottom.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing/double_bottom.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/double_bottom.py tests/domain/strategies/authoritative_swing/test_double_bottom.py
git commit -m "feat: detect authoritative double bottoms"
```

### Task 6: Historical resistance zones and no-chase entry ceiling

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/resistance.py`
- Create: `tests/domain/strategies/authoritative_swing/test_resistance.py`

**Interfaces:**
- Consumes: three calendar years of prior `FinalBar` objects and analytical candidate terms.
- Produces: `find_resistance_zones()`, `nearest_relevant_resistance()`, and `analytical_entry_ceiling_for(candidate, history)`.

- [ ] **Step 1: Write failing tests for swing highs, zone grouping, strict 2R clearance, and insufficient data**

```python
def test_entry_limit_is_signal_close_when_no_zone_exists() -> None:
    result = analytical_entry_ceiling_for(candidate(signal_close="10", invalidation="9"), clear_history())
    assert result.limit_price == D("10")

def test_limit_is_last_tick_whose_2r_price_is_below_zone() -> None:
    result = analytical_entry_ceiling_for(candidate(signal_close="10", invalidation="9"), zone_history(lower="11.95"))
    assert result.limit_price + 2 * (result.limit_price - D("9")) < D("11.95")

def test_unadjusted_or_short_history_abstains() -> None:
    assert analytical_entry_ceiling_for(candidate(), invalid_history()).status is DecisionStatus.ABSTAIN
```

Also test five bars on both sides and the exact canonical grouping contract:
sort by `(price, source-bar session and digest)`, enumerate all contiguous
groups of at least two highs, calculate an odd-count middle or even-count
two-middle arithmetic median `M`, require every member price `P` to satisfy
`abs(P - M) / M <= 0.01`, require at least one member pair separated by at
least 20 completed sessions, deduplicate identical member sets,
remove groups wholly contained in another qualifying group, and retain
overlapping maximal groups. Assert lower and upper edges are member minimum and
maximum, final ordering is `(lower, upper, ordered member identities)`, and
input permutations produce byte-identical zones. Test a candidate inside a
zone, exact edge touches, overlap anywhere from entry through 2R, deterministic
nearest-barrier tie-breaking, and a zone wholly below entry.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_resistance.py -q`

- [ ] **Step 3: Implement deterministic zone construction and algebraic ceiling**

Construct maximal zones exactly as specified, retaining overlapping maximal
sets. Ignore only zones whose upper edge is below the candidate entry. Reject
an entry inside a zone; otherwise choose the nearest zone by
`max(entry, zone.lower)`, with canonical order as the tie-break. Solve
`E + 2(E - S) < zone_lower` for the maximum analytical `E` and cap it at the
analytical signal close. A signal close inside a zone is rejected rather than
rescued by lowering its limit. Store every zone member, both edges, relevance
decision, and chosen barrier. Task 8 converts the candidate, stop, ceiling, and
zone edges to raw basis, rounds executable prices, and repeats the strict test
before emitting an instruction.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_resistance.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/resistance.py tests/domain/strategies/authoritative_swing/test_resistance.py
git commit -m "feat: validate swing resistance clearance"
```

### Task 7: Exact cost, liquidity, and 1% whole-share sizing

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/sizing.py`
- Modify: `src/qat/domain/backtester/market_cost_profiles.py`
- Create: `tests/domain/strategies/authoritative_swing/test_sizing.py`
- Modify: `tests/domain/backtester/test_market_cost_profiles.py`

**Interfaces:**
- Consumes: decimal equity, raw limit and stop, prior 20 verified raw bars, `ExactCostProfile`, and mandatory `LiquidityProfile`.
- Produces: `size_for_risk()`, `capacity_quantity()`, and `size_instruction(...) -> SizingDecision`.

- [ ] **Step 1: Write failing exact-cost, capacity, look-ahead, and two-share-minimum tests**

Mirror the real ASX fixed and tiered profiles with decimal fixtures. Assert the
risk quantity is the largest integer whose limit-price risk plus modeled entry,
impact, and stop-exit costs is at or below budget, and that `quantity + 1`
breaches it. Derive capacity from the smaller quantity allowed by the frozen
participation fraction against prior-20 median raw share volume and median raw
dollar volume. Assert current/future volume cannot change it, capacity can bind
below risk size, missing/unverified history abstains, and the final submitted
quantity is fixed before the open. Give a tiny-stop fixture with an upper bound
above one million shares and assert integer bisection finds the maximal quantity
in at most 32 cost evaluations. Test every approved fee profile for monotone
nondecreasing total modeled risk.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_sizing.py -q`

- [ ] **Step 3: Implement exact costs, prior-data capacity, and monotone integer sizing**

Define immutable decimal cost and liquidity profiles with version identifiers.
Factor approved fee parameters into canonical text configuration consumed by
both the unchanged legacy float adapter and the new exact-decimal adapter, so
fee schedules have one source without routing Phase 2 arithmetic through
floats.
Reject non-positive equity or limit-to-stop risk distance. Require every exact
cost profile to prove and test that total modeled risk is monotone
nondecreasing in quantity. Compute the safe upper bound
`floor(budget / (limit - stop))`, then use integer bisection to find the largest
quantity satisfying the complete exact-cost inequality. Assert the selected
quantity passes and `quantity + 1` fails. Calculate capacity without reading
the entry session.
Return `REJECTED` when `min(risk_quantity, capacity_quantity)` is below two,
with price basis, budget, participation, impact, and cost components in
evidence. A missing or provisional liquidity profile makes a promotion
fingerprint ineligible. Actual-fill risk and net-R accounting belong to Phase
2B.

- [ ] **Step 4: Run focused and existing cost tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_sizing.py tests/domain/backtester/test_costs.py tests/domain/backtester/test_market_cost_profiles.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/sizing.py src/qat/domain/backtester/market_cost_profiles.py tests/domain/strategies/authoritative_swing/test_sizing.py tests/domain/backtester/test_market_cost_profiles.py
git commit -m "feat: size authoritative swing entries"
```

### Task 8: Authoritative setup engine and confluence

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/engine.py`
- Create: `tests/domain/strategies/authoritative_swing/test_engine.py`
- Create: `tests/safety/test_phase2_strategy_isolation.py`

**Interfaces:**
- Consumes: `SwingHistory`, decimal equity, `ExactCostProfile`, `LiquidityProfile`, and optional analysis-only regime metadata.
- Produces: `AuthoritativeSwingEngine.evaluate(history, equity, costs, liquidity) -> SetupDecision` and `evaluate_patterns(...) -> tuple[PatternDecision, ...]`.

- [ ] **Step 1: Write failing orchestration, confluence, determinism, and isolation tests**

```python
def test_confluence_recomputes_with_lowest_limit_and_stop() -> None:
    decision = engine_with_stubbed_patterns(ema(limit="10", invalidation="9"), flag(limit="9.8", invalidation="8.5")).evaluate(...)
    assert decision.entry_limit_raw == D("9.80")
    assert decision.initial_stop_raw == D("8.49")
    assert decision.patterns == (Pattern.EMA_PULLBACK, Pattern.BULL_FLAG)

def test_repeated_evaluation_is_identical() -> None:
    first = engine.evaluate(history, D("100000"), costs, liquidity)
    second = engine.evaluate(history, D("100000"), costs, liquidity)
    assert first == second

def test_phase2_transitive_import_graph_has_no_execution_dependencies() -> None:
    forbidden = ("qat.domain.oms", "qat.data.broker.adapter", "qat.domain.autonomy")
    imported = transitive_internal_imports(authoritative_swing_root())
    assert not any(name == root or name.startswith(root + ".") for name in imported for root in forbidden)
```

Also test that any required-data defect abstains, a measured failed gate
rejects, analysis regime cannot change the result, a conservative confluence
can fail resistance after its wider stop is applied, and every emitted
double-bottom candidate carries stable pattern-instance and breakout-event IDs.
Add cases where raw conversion and tick rounding change the analytical result;
the raw-basis repeat check governs. Mutating any history bar after the signal
session must leave the decision byte-identical; Phase 2C extends this prefix
test to membership, corporate-action, and calendar inputs.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_engine.py tests/safety/test_phase2_strategy_isolation.py -q`

- [ ] **Step 3: Implement common-gate ordering and immutable output**

Evaluate all three patterns independently, retain their evidence, and represent
confluence only as a tuple of constituent `Pattern` values—never as a fourth
`Pattern`. Combine simultaneous qualifiers, convert final analytical terms and
zone edges to raw basis, construct the raw one-tick stop and grid-valid limit,
repeat resistance, apply exact risk/capacity sizing once, and compute the
decision ID from the complete semantic envelope. Existing positions and
consumed identities are not inputs in Phase 2A; lifecycle blocking belongs to
Phase 2B.

- [ ] **Step 4: Run the package suite and static checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing tests/safety/test_phase2_strategy_isolation.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing`

Run: `.\.venv\Scripts\python.exe -m ruff check src/qat/domain/strategies/authoritative_swing tests/domain/strategies/authoritative_swing tests/safety/test_phase2_strategy_isolation.py`

Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS with the deployed `SwingStrategy` tests unchanged.

```powershell
git add src/qat/domain/strategies/authoritative_swing/engine.py tests/domain/strategies/authoritative_swing/test_engine.py tests/safety/test_phase2_strategy_isolation.py
git commit -m "feat: orchestrate authoritative swing evidence"
```
