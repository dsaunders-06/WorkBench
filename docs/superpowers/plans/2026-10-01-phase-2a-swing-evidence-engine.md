# Phase 2A Swing Evidence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, deterministic rule-and-evidence engine for the approved EMA20 pullback, bull flag, and double-bottom strategy without changing the deployed swing strategy.

**Architecture:** Add an `authoritative_swing` domain package beside the existing `swing.py`. Typed finalized bars enter pure functions; pattern modules return rule evidence; one engine applies common gates, resistance, cost-aware sizing, and confluence. Existing cost, calendar, and tick primitives are reused and extended where necessary.

**Tech Stack:** Python 3.12, frozen dataclasses, `StrEnum`, pandas/numpy for numerical series, existing `CostModel`, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Do not modify `src/qat/domain/strategies/swing.py` or deploy the new engine.
- Accept finalized daily bars only; invalid, partial, or insufficient data returns typed `ABSTAIN` evidence.
- Keep regime out of entry eligibility; attach it only as analysis metadata.
- Use `CostModel` for commissions, exchange charges, and slippage.
- Use ASX ticks from `qat.data.broker.ticks`; never duplicate the tick table.
- Use strategy version `phase2-swing-v1` and schema version `swing-evidence-v1`.
- All evidence identifiers derive from canonical semantic content and contain no wall-clock value.
- No network, broker adapter/submission, database, UI, scheduler, or AI import is allowed in the new package. The pure exchange-tick utility is permitted.

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
- `src/qat/domain/strategies/authoritative_swing/indicators.py` — canonical EMA, Wilder ATR, and completed-week aggregation.
- `src/qat/domain/strategies/authoritative_swing/ema_pullback.py` — EMA rejection pattern only.
- `src/qat/domain/strategies/authoritative_swing/bull_flag.py` — bull-flag pattern only.
- `src/qat/domain/strategies/authoritative_swing/double_bottom.py` — double-bottom pattern only.
- `src/qat/domain/strategies/authoritative_swing/resistance.py` — swing highs, zones, and 2R entry ceiling.
- `src/qat/domain/strategies/authoritative_swing/sizing.py` — whole-share 1% risk sizing.
- `src/qat/domain/strategies/authoritative_swing/engine.py` — common gates and confluence orchestration.
- `tests/domain/strategies/authoritative_swing/` — tests mirroring each responsibility.

## Review Focus

- A bar marked partial, synthetic, zero-volume where volume is required, or carrying NaN must abstain; Tasks 1 and 8 pin preservation and refusal.
- ASX band boundaries at $0.10 and $2.00 must still place the stop exactly one valid tick below invalidation; Task 2 pins both boundaries.
- A holiday-shortened Friday week must count as complete while the current week remains excluded; Task 2 pins both cases.
- Multiple valid flag lengths and bottom pairs must use the approved deterministic tie-breaks; Tasks 4 and 5 pin them.
- Confluence must recompute resistance and sizing from the conservative combined stop and limit; Task 8 pins rejection after recomputation.

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
        RuleEvidence("close", RuleOutcome.PASS, measured=float("nan"))
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
    CONFLUENCE = "confluence"

class RuleOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"

@dataclass(frozen=True, slots=True)
class Ohlcv:
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True, slots=True)
class FinalBar:
    symbol: str
    session: date
    raw: Ohlcv
    adjusted: Ohlcv
    source: str
    quality: DataQuality
    adjustment: AdjustmentStatus
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
    measured: float | int | str | bool | None = None
    threshold: float | int | str | None = None
    reason: str | None = None

@dataclass(frozen=True, slots=True)
class PatternCandidate:
    pattern: Pattern
    signal_session: date
    signal_close: float
    invalidation: float
    initial_stop: float
    atr14: float
    metadata: tuple[tuple[str, str | int | float | bool], ...] = ()

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
    entry_limit: float | None
    initial_stop: float | None
    quantity: int
    input_digests: tuple[str, ...]
    analysis_regime: str | None = None
```

`SwingHistory.__post_init__` rejects mixed symbols and duplicate/out-of-order sessions. It preserves malformed numeric values, finalization, quality, and adjustment states so the engine can emit auditable abstentions instead of losing the evaluated session at ingestion. Evidence output itself refuses non-finite measured values. `stable_decision_id()` uses `json.dumps(..., sort_keys=True, separators=(",", ":"), allow_nan=False)` and SHA-256 prefixed with `swing:`.

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

### Task 2: Canonical indicators, completed weeks, and previous ASX tick

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/indicators.py`
- Modify: `src/qat/data/broker/ticks.py`
- Create: `tests/domain/strategies/authoritative_swing/test_indicators.py`
- Modify: `tests/data/broker/test_ticks.py`

**Interfaces:**
- Consumes: `tuple[FinalBar, ...]`, ASX calendar functions, existing `tick_size()`.
- Produces: `ema(values, period)`, `wilder_atr(bars, period=14)`, `completed_weekly_bars(bars)`, and `previous_tick(price, market)`.

- [ ] **Step 1: Write failing hand-calculated indicator and calendar tests**

```python
def test_ema_is_seeded_by_the_first_simple_mean() -> None:
    assert ema((1.0, 2.0, 3.0, 4.0), 3) == (None, None, 2.0, 3.0)

def test_wilder_atr_uses_previous_close_for_gaps() -> None:
    values = wilder_atr(gapped_bars(), period=3)
    assert values[-1] == pytest.approx(hand_calculated_atr())

def test_current_week_is_excluded_but_christmas_short_week_is_complete() -> None:
    weekly = completed_weekly_bars(daily_fixture_through("2026-12-29"))
    assert weekly[-1].session == date(2026, 12, 24)

@pytest.mark.parametrize(("price", "expected"), [(0.10, 0.099), (2.00, 1.995)])
def test_previous_tick_crosses_asx_bands(price: float, expected: float) -> None:
    assert previous_tick(price, "ASX") == expected
```

- [ ] **Step 2: Verify the tests fail on absent APIs**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py -q`

Expected: FAIL because the new functions are absent.

- [ ] **Step 3: Implement exact calculations**

`ema()` returns one item per input and `None` before the simple-mean seed. `wilder_atr()` implements spec §4.2 and returns `None` before its seed. `completed_weekly_bars()` groups official ASX sessions and includes a group only when the next ASX trading day lies in a later ISO week. `previous_tick()` returns the greatest valid exchange price strictly below the input, including across tick-band boundaries.

- [ ] **Step 4: Run focused and existing tick/calendar tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py tests/domain/test_market_calendar.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/indicators.py src/qat/data/broker/ticks.py tests/domain/strategies/authoritative_swing/test_indicators.py tests/data/broker/test_ticks.py
git commit -m "feat: add canonical swing calculations"
```

### Task 3: EMA20 pullback detector and weekly filter

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/ema_pullback.py`
- Create: `tests/domain/strategies/authoritative_swing/test_ema_pullback.py`

**Interfaces:**
- Consumes: `SwingHistory`, EMA/ATR/weekly calculations, `previous_tick()`.
- Produces: `evaluate_ema_pullback(history) -> PatternDecision`.

- [ ] **Step 1: Write failing positive, boundary, rejection, and abstention tests**

Cover every spec §6.1 condition individually. Include exactly 50 completed weeks, 49 weeks, a wick exactly twice the body, a close exactly at the upper-third boundary, a doji, a touched EMA that closes below it, and the weekly rejection that requires both bearish clauses.

```python
def test_weekly_filter_rejects_only_when_both_clauses_are_bearish() -> None:
    decision = evaluate_ema_pullback(history(weekly_close_below=True, ema20_below_ema50=False))
    assert rule(decision, "weekly_filter").outcome is RuleOutcome.PASS

def test_stop_is_one_valid_tick_below_lower_invalidation() -> None:
    decision = evaluate_ema_pullback(valid_history(signal_low=1.995, signal_ema20=2.01))
    assert decision.candidate is not None
    assert decision.candidate.initial_stop == 1.99
```

- [ ] **Step 2: Run and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_ema_pullback.py -q`

- [ ] **Step 3: Implement one rule result per condition**

Return `ABSTAIN` for unavailable indicators/history and `REJECTED` for measured market conditions that fail. The candidate carries signal close, invalidation, initial stop, ATR, and the signal-bar digest.

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
- Produces: `evaluate_bull_flag(history, volume_multiplier=1.5) -> PatternDecision`.

- [ ] **Step 1: Write failing tests for pole, flag, breakout, and longest-window selection**

Pin the five-session pole, `max(5%, 2 ATR)`, 3/8-session flag boundaries, non-positive least-squares close slope, 50% maximum retracement, lower mean flag volume, strict breakout above flag high, rising EMA20 above EMA50, 20-session preceding volume mean, zero-volume abstention, and longest qualifying flag.

```python
def test_breakout_volume_excludes_the_breakout_session() -> None:
    decision = evaluate_bull_flag(valid_flag(breakout_volume=1_500, prior_mean=1_000))
    assert rule(decision, "breakout_volume").measured == pytest.approx(1.5)

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
- Produces: `evaluate_double_bottom(history, volume_multiplier=1.5) -> PatternDecision`.

- [ ] **Step 1: Write failing tests for pivots, spacing, tolerance, neckline, and pair tie-breaks**

Pin three bars on each side of each strict local low, 5/30-session spacing, bottom-price difference divided by their mean, neckline strictly between bottoms, `max(3%, 1 ATR)` neckline depth, close above neckline and EMA20, rising EMA20, volume, weekly filter, and most-recent-pair selection. Assert that EMA20 may remain below EMA50.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_double_bottom.py -q`

- [ ] **Step 3: Implement confirmed-pivot and pair selection logic**

Sort qualifying pairs by second-bottom session descending, then first-bottom session descending. Record both bottom sessions, prices, neckline source session, ATR, and distance in evidence.

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
- Consumes: three calendar years of prior `FinalBar` objects, candidate stop and signal close.
- Produces: `find_resistance_zones()`, `nearest_resistance_above()`, and `entry_limit_for(candidate, history)`.

- [ ] **Step 1: Write failing tests for swing highs, zone grouping, strict 2R clearance, and insufficient data**

```python
def test_entry_limit_is_signal_close_when_no_zone_exists() -> None:
    result = entry_limit_for(candidate(signal_close=10.0, stop=9.0), clear_history())
    assert result.limit_price == 10.0

def test_limit_is_last_tick_whose_2r_price_is_below_zone() -> None:
    result = entry_limit_for(candidate(signal_close=10.0, stop=9.0), zone_history(lower=11.95))
    assert result.limit_price + 2 * (result.limit_price - 9.0) < 11.95

def test_unadjusted_or_short_history_abstains() -> None:
    assert entry_limit_for(candidate(), invalid_history()).status is DecisionStatus.ABSTAIN
```

Also test five bars on both sides, two highs at least 20 sessions apart, 1% median membership, nearest-zone selection, and exact-zone-touch rejection.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_resistance.py -q`

- [ ] **Step 3: Implement deterministic zone construction and algebraic ceiling**

Solve `E + 2(E - S) < zone_lower` for the maximum `E`, then walk down valid ASX ticks until the strict inequality holds. Cap it at signal close. Store every zone member and chosen edge in evidence.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_resistance.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/resistance.py tests/domain/strategies/authoritative_swing/test_resistance.py
git commit -m "feat: validate swing resistance clearance"
```

### Task 7: Cost-aware 1% whole-share sizing

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/sizing.py`
- Create: `tests/domain/strategies/authoritative_swing/test_sizing.py`

**Interfaces:**
- Consumes: equity, entry, stop, and existing `CostModel`.
- Produces: `size_for_risk(equity, entry, stop, costs, risk_fraction=0.01) -> SizingDecision`.

- [ ] **Step 1: Write failing tests for commission floors, exchange fees, slippage, and two-share minimum**

Use the real ASX fixed and tiered profiles in parameterized tests. Assert the returned quantity is the largest integer whose entry risk plus modeled entry and stop-exit costs is at or below budget, and that `quantity + 1` breaches it.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_sizing.py -q`

- [ ] **Step 3: Implement monotone integer sizing**

Reject non-positive equity or risk distance. Compute a safe upper bound from price risk, then decrement until the complete cost inequality passes. Return `REJECTED` when fewer than two shares fit, with budget and cost components in evidence.

- [ ] **Step 4: Run focused and existing cost tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_sizing.py tests/domain/backtester/test_costs.py tests/domain/backtester/test_market_cost_profiles.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/sizing.py tests/domain/strategies/authoritative_swing/test_sizing.py
git commit -m "feat: size authoritative swing entries"
```

### Task 8: Authoritative setup engine and confluence

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/engine.py`
- Create: `tests/domain/strategies/authoritative_swing/test_engine.py`
- Create: `tests/safety/test_phase2_strategy_isolation.py`

**Interfaces:**
- Consumes: `SwingHistory`, equity, `CostModel`, optional analysis-only regime metadata.
- Produces: `AuthoritativeSwingEngine.evaluate(history, equity, costs) -> SetupDecision` and `evaluate_patterns(...) -> tuple[PatternDecision, ...]`.

- [ ] **Step 1: Write failing orchestration, confluence, determinism, and isolation tests**

```python
def test_confluence_recomputes_with_lowest_limit_and_stop() -> None:
    decision = engine_with_stubbed_patterns(ema(limit=10, stop=9), flag(limit=9.8, stop=8.5)).evaluate(...)
    assert decision.entry_limit == 9.8
    assert decision.initial_stop == 8.5
    assert decision.patterns == (Pattern.EMA_PULLBACK, Pattern.BULL_FLAG)

def test_repeated_evaluation_is_identical() -> None:
    assert engine.evaluate(history, 100_000, costs) == engine.evaluate(history, 100_000, costs)

def test_phase2_package_has_no_execution_imports() -> None:
    forbidden = ("qat.domain.oms", "qat.data.broker.adapter", "qat.domain.autonomy")
    assert not imported_modules_under(authoritative_swing_root()) & set(forbidden)
```

Also test that any required-data defect abstains, a measured failed gate rejects, analysis regime cannot change the result, and a conservative confluence can fail resistance after its wider stop is applied.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_engine.py tests/safety/test_phase2_strategy_isolation.py -q`

- [ ] **Step 3: Implement common-gate ordering and immutable output**

Evaluate all three patterns independently, retain their evidence, combine simultaneous qualifiers, recalculate resistance and sizing once on final terms, and compute the decision ID from the complete semantic envelope. Existing positions are not an input in Phase 2A; lifecycle blocking belongs to Phase 2B.

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
