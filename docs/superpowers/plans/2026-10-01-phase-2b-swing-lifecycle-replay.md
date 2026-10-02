# Phase 2B Swing Lifecycle and Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Phase 2A setup evidence into a deterministic position lifecycle and cash-funded historical replay with conservative daily-bar fills.

**Architecture:** Keep lifecycle transitions as pure reducers in the authoritative strategy package. A dedicated backtester adapter walks exchange sessions, applies corporate actions and opening fills, processes protective events, evaluates completed closes, and records immutable evidence. It does not route through the production OMS; production-stack parity replay remains deferred.

**Tech Stack:** Python 3.12, `decimal.Decimal`, Phase 2A domain and exact-cost types, ASX calendar/ticks, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Complete Phase 2A first and keep its public interfaces stable.
- Do not modify or instantiate the production OMS, autonomy executor, IBKR adapter, or deployed `SwingStrategy`.
- Count the entry session as completed holding session one.
- Preserve protection during `EXIT_PENDING`; gap-stop processing precedes a scheduled open exit.
- Resolve unknowable same-bar order in the strategy's worst feasible sequence and flag it.
- Keep all quantities whole and require at least two shares at entry.
- Use actual simulated fills to define lifecycle R, target, cash, costs, and
  realized P&L; retain the submitted-limit denominator for primary `R_order`.
- Preserve decimal prices, money, risks, and R multiples end-to-end; do not
  convert execution state through binary floats.
- Keep the quantity submitted from Phase 2A's limit-price sizing fixed after the
  open; never resize upward from a better fill.
- Track consumed double-bottom pattern instances and used breakout events so a
  replay cannot duplicate an instruction or filled pattern.
- A replay must be deterministic from strategy version, signed dataset catalog
  and authorized shard identities, cost model, and ordered events.
- Promotion replay advances only through Phase 2C's signed official-session
  sequence. The rule-derived production calendar is a fixture/cross-check and
  cannot invent a missing session or erase an ad hoc closure.
- Treat the uncapped cash-funded arm as engineering evidence with status
  `PORTFOLIO_RISK_DESIGN_PENDING`. Promotion-tier development and validation
  are replayed from the beginning only after Phase 4 sizing and risk rules are
  frozen.

## File Structure

- `src/qat/domain/strategies/authoritative_swing/lifecycle.py` — position states and pure transition rules.
- `src/qat/domain/backtester/swing_fills.py` — conservative daily-bar fill resolver.
- `src/qat/domain/backtester/swing_events.py` — typed corporate-action and terminal-outcome events.
- `src/qat/domain/backtester/swing_portfolio.py` — cash, positions, simultaneous allocation, and equity.
- `src/qat/domain/backtester/swing_replay.py` — ordered multi-symbol session loop.
- `src/qat/domain/backtester/swing_results.py` — fills, trades, equity points, and run result types.
- `tests/domain/strategies/authoritative_swing/test_lifecycle.py` — state reducer tests.
- `tests/domain/backtester/test_swing_fills.py` — fill-order tests.
- `tests/domain/backtester/test_swing_portfolio.py` — cash-allocation tests.
- `tests/domain/backtester/test_swing_replay.py` — end-to-end golden scenarios.

## Review Focus

- A scheduled close exit and a gap through the protective stop on the same open must sell once at the gap price; Tasks 2 and 5 pin it.
- A target and newly armed breakeven stop reachable in one bar must bank the partial and close the runner once; Tasks 2 and 3 pin it.
- Odd entry quantities must bank half rounded up and leave a nonzero runner; Task 1 pins quantities 3 and 5.
- Reprocessing the same session or fill must not change cash, quantity, or evidence twice; Tasks 1 and 5 pin it.
- Simultaneous candidates that exceed cash must be scaled as a batch without symbol ordering changing allocations; Task 4 pins reversed input order.

---

### Task 1: Position states, confirmed entry, and idempotent transitions

**Files:**
- Create: `src/qat/domain/strategies/authoritative_swing/lifecycle.py`
- Create: `src/qat/domain/backtester/swing_events.py`
- Create: `tests/domain/strategies/authoritative_swing/test_lifecycle.py`

**Interfaces:**
- Consumes: Phase 2A `SetupDecision` and confirmed fill events.
- Produces: `PositionState`, `PendingEntry`, `SwingPosition`, `LifecycleAction`, `apply_entry_fill()`, `apply_exit_fill()`, `SplitEvent`, `CashDividendEvent`, `SymbolChangeEvent`, `SuspensionEvent`, `DelistingEvent`, and their `SwingMarketEvent` union.

- [ ] **Step 1: Write failing state and quantity tests**

```python
def test_entry_fill_defines_r_and_rounds_banked_half_up() -> None:
    position = apply_entry_fill(pending(quantity=5, stop=D("9.00")), fill(price=D("10.00"), quantity=5))
    assert position.state is PositionState.OPEN_FULL
    assert position.initial_r == D("1.00")
    assert position.banked_quantity == 3
    assert position.runner_quantity == 2
    assert position.target_price == D("11.00")

def test_replaying_a_fill_id_is_a_no_op() -> None:
    once = apply_entry_fill(pending(), fill(event_id="fill-1"))
    assert apply_entry_fill(once, fill(event_id="fill-1")) == once
```

Also test valid transitions only, total quantity conservation, entry session
count one, and rejection of a fill at/below stop. Assert that
`fill_initial_risk_dollars` equals
`filled quantity × (actual fill - initial stop)`,
`order_initial_risk_dollars` equals
`filled quantity × (submitted limit - initial stop)`, a fill below the limit
leaves the submitted quantity unchanged, and the same structural stop produces
the actual-fill 1R target.

- [ ] **Step 2: Run and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_lifecycle.py -q`

- [ ] **Step 3: Implement the frozen lifecycle records**

```python
class PositionState(StrEnum):
    FLAT = "flat"
    ENTRY_PENDING = "entry_pending"
    OPEN_FULL = "open_full"
    RUNNER = "runner"
    EXIT_PENDING = "exit_pending"
    CLOSED = "closed"
    CANCELLED = "cancelled"

@dataclass(frozen=True, slots=True)
class SwingPosition:
    position_id: str
    symbol: str
    state: PositionState
    entry_session: date
    submitted_limit: Decimal
    entry_fill: Decimal
    initial_stop: Decimal
    current_stop: Decimal
    initial_r: Decimal
    order_initial_risk_dollars: Decimal
    fill_initial_risk_dollars: Decimal
    total_quantity: int
    banked_quantity: int
    runner_quantity: int
    target_price: Decimal
    completed_sessions: int
    highest_high: Decimal
    applied_event_ids: frozenset[str]
```

All reducers and market events are frozen records keyed by stable event ID and effective session. Define `SwingMarketEvent = SplitEvent | CashDividendEvent | SymbolChangeEvent | SuspensionEvent | DelistingEvent`. Invalid transitions raise `LifecycleInvariantError`; duplicate event IDs return the unchanged state. Pending-entry/replay state also records `used_breakout_event_ids` and `consumed_pattern_instance_ids`. Cancelling or failing to fill an instruction consumes only its breakout event. Confirming a fill consumes both the breakout event and its pattern instance permanently.

- [ ] **Step 4: Run focused tests and type check**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_lifecycle.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing/lifecycle.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/lifecycle.py src/qat/domain/backtester/swing_events.py tests/domain/strategies/authoritative_swing/test_lifecycle.py
git commit -m "feat: add swing position state machine"
```

### Task 2: Close invalidation, time stop, and runner ratchet

**Files:**
- Modify: `src/qat/domain/strategies/authoritative_swing/lifecycle.py`
- Modify: `tests/domain/strategies/authoritative_swing/test_lifecycle.py`

**Interfaces:**
- Consumes: open `SwingPosition`, one finalized session, EMA20, ATR14, and confirmed target fill.
- Produces: `apply_target_fill()`, `evaluate_completed_close()`, and `schedule_exit()`.

- [ ] **Step 1: Add failing target, trail, invalidation, and tenth-session tests**

```python
def test_target_fill_moves_runner_to_breakeven() -> None:
    position = apply_target_fill(open_position(), fill(price=D("11.00"), quantity=5))
    assert position.state is PositionState.RUNNER
    assert position.current_stop == position.entry_fill

def test_trail_uses_highest_high_and_never_moves_down() -> None:
    first = evaluate_completed_close(runner(stop=D("10")), bar(high=D("13")), ema20=D("11"), atr14=D("1"))
    second = evaluate_completed_close(first.position, bar(high=D("12")), ema20=D("11"), atr14=D("1.5"))
    assert first.position.current_stop == D("11")
    assert second.position.current_stop == D("11")

def test_tenth_completed_session_schedules_next_open_exit() -> None:
    result = evaluate_completed_close(position(completed_sessions=9), healthy_bar(), ema20=10, atr14=1)
    assert result.position.state is PositionState.EXIT_PENDING
    assert "time_stop" in result.triggers
```

Pin one close 0.5 ATR below EMA20, two consecutive closes below EMA20, an earlier protective exit, and the rule that the trail starts only after a later completed close than the target-fill session.

- [ ] **Step 2: Verify the new tests fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_lifecycle.py -q`

- [ ] **Step 3: Implement close evaluation in one ordered reducer**

Update highest high and holding-session count, calculate all active triggers, ratchet the stop with `max(existing, entry_fill, highest_high - 2 * atr14)`, and schedule one next-open exit when close invalidation or time stop fires. Preserve the stop and record every simultaneous trigger.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing/test_lifecycle.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/strategies/authoritative_swing/lifecycle.py tests/domain/strategies/authoritative_swing/test_lifecycle.py
git commit -m "feat: manage swing exits and runner stops"
```

### Task 3: Conservative daily-bar fill resolver

**Files:**
- Create: `src/qat/domain/backtester/swing_fills.py`
- Create: `src/qat/domain/backtester/swing_results.py`
- Create: `tests/domain/backtester/test_swing_fills.py`

**Interfaces:**
- Consumes: one raw traded daily bar, pending entry or open position, and Phase 2A `ExactCostProfile`.
- Produces: ordered `SimulatedFill` tuples plus `FillAmbiguity` evidence through `resolve_entry_open()`, `resolve_open_exit()`, and `resolve_protective_session()`.

- [ ] **Step 1: Write failing tests for every execution branch**

Cover valid open plus capped buy slippage, gap above limit cancellation, open at/below invalidation cancellation, missing-open cancellation, gap through stop, intraday stop, target-only fill, original stop and target same bar, and target plus newly armed breakeven stop same bar.

```python
def test_stop_wins_a_bar_that_can_touch_stop_and_target() -> None:
    fills = resolve_protective_session(position(), bar(low=D("8.9"), high=D("11.2")), costs())
    assert [(f.reason, f.quantity) for f in fills] == [("protective_stop", position().total_quantity)]
    assert fills[0].ambiguous is True

def test_target_then_breakeven_is_worst_feasible_when_initial_stop_is_safe() -> None:
    fills = resolve_protective_session(position(stop=D("9"), entry=D("10"), target=D("11")), bar(low=D("9.8"), high=D("11.2")), costs())
    assert [f.reason for f in fills] == ["banked_target", "runner_breakeven"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_fills.py -q`

- [ ] **Step 3: Implement explicit opening, stop, then target ordering**

Apply decimal slippage/impact once in fill price and broker charges separately in
`SimulatedFill.cost`. A sell target gapped above fills at
`max(target, open - sell_slippage)`. Preserve an exact raw auction open even if
it is off the normal order-entry grid. Ambiguous baseline and optimistic
sensitivity use the same resolver with `AmbiguityPolicy.CONSERVATIVE` or
`OPTIMISTIC`.

Define the shared result shapes in `swing_results.py` here so later replay and reporting tasks use one vocabulary:

```python
class RunStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"

class ReplayArm(StrEnum):
    EMA_PULLBACK = "ema_pullback"
    BULL_FLAG = "bull_flag"
    DOUBLE_BOTTOM = "double_bottom"
    COMBINED = "combined"

class PostFillResistanceDiagnostic(StrEnum):
    CLEAR = "post_fill_resistance_clear"
    INSIDE_ZONE = "post_fill_resistance_inside_zone"
    PATH_BLOCKED = "post_fill_resistance_path_blocked"

@dataclass(frozen=True, slots=True)
class SimulatedFill:
    event_id: str
    symbol: str
    session: date
    side: str
    quantity: int
    price: Decimal
    cost: Decimal
    reason: str
    ambiguous: bool = False

@dataclass(frozen=True, slots=True)
class FillAmbiguity:
    event_id: str
    symbol: str
    session: date
    baseline_sequence: tuple[str, ...]
    optimistic_sequence: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SwingTrade:
    trade_id: str
    symbol: str
    patterns: tuple[Pattern, ...]
    entry_session: date
    exit_session: date
    quantity: int
    submitted_limit: Decimal
    entry_price: Decimal
    exit_price: Decimal
    initial_stop: Decimal
    gross_pnl: Decimal
    eligible_dividends: Decimal
    costs: Decimal
    net_pnl: Decimal
    order_initial_risk_dollars: Decimal
    fill_initial_risk_dollars: Decimal
    order_r_multiple: Decimal
    fill_r_multiple: Decimal
    mfe_order_r: Decimal
    mae_order_r: Decimal
    mfe_fill_r: Decimal
    mae_fill_r: Decimal
    exit_reason: str
    observed_triggers: tuple[str, ...]
    post_fill_resistance: PostFillResistanceDiagnostic
    analysis_regime: str | None
    edge_sample_eligible: bool
    edge_exclusion_reason: str | None

@dataclass(frozen=True, slots=True)
class ReplayEquityPoint:
    session: date
    equity: Decimal
    cash: Decimal
    position_value: Decimal
    dividend_receivables: Decimal

@dataclass(frozen=True, slots=True)
class SwingReplayResult:
    status: RunStatus
    arm: ReplayArm
    decisions: tuple[SetupDecision, ...]
    position_events: tuple[LifecycleAction, ...]
    fills: tuple[SimulatedFill, ...]
    trades: tuple[SwingTrade, ...]
    signal_trades: tuple[SwingTrade, ...]
    equity: tuple[ReplayEquityPoint, ...]
    abstentions: tuple[RuleEvidence, ...]
    ambiguities: tuple[FillAmbiguity, ...]
    invalid_reasons: tuple[str, ...] = ()
```

Compute `net_pnl` across all exit legs and accrued eligible dividends after
commission, exchange charges, and slippage. Define `order_r_multiple` as
`net_pnl / order_initial_risk_dollars` and `fill_r_multiple` as
`net_pnl / fill_initial_risk_dollars`; do not average leg-level R values or use
their per-trade minimum as the baseline. Splits must transform quantity and
prices while preserving both denominators.

- [ ] **Step 4: Run focused and cost tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_costs.py tests/domain/backtester/test_cost_charge.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_results.py tests/domain/backtester/test_swing_fills.py
git commit -m "feat: simulate conservative swing fills"
```

### Task 4: Cash-funded portfolio and simultaneous allocation

**Files:**
- Create: `src/qat/domain/backtester/swing_portfolio.py`
- Create: `tests/domain/backtester/test_swing_portfolio.py`

**Interfaces:**
- Consumes: decimal cash, positions, same-session qualified entry batch, and `ExactCostProfile`.
- Produces: `PortfolioState`, `allocate_entry_batch()`, `apply_fills()`, and `mark_to_market()`.

- [ ] **Step 1: Write failing cash, no-leverage, and order-independence tests**

```python
def test_oversubscribed_batch_scales_every_risk_budget_equally() -> None:
    allocations = allocate_entry_batch(cash=10_000, candidates=three_equal_candidates(), costs=costs())
    assert len({a.scale_factor for a in allocations}) == 1
    assert sum(a.reserved_cash for a in allocations) <= 10_000

def test_symbol_input_order_cannot_choose_a_winner() -> None:
    forward = allocate_entry_batch(cash=10_000, candidates=candidates(), costs=costs())
    reverse = allocate_entry_batch(cash=10_000, candidates=tuple(reversed(candidates())), costs=costs())
    assert by_symbol(forward) == by_symbol(reverse)
```

Also test existing positions reserve purchase cost, commission floors after
scaling, whole shares, removal below two shares, cash debits/credits, dividend
credit, and no negative cash. Do not add a per-position notional cap or minimum
stop distance in Phase 2. Record each allocation's notional exposure,
zero-price equity loss, stop distance, and cost-to-risk ratio so Phase 2C can
report the uncapped replay as a concentration and gap-risk engineering stress
case and Phase 4 can define structural controls without inspecting returns.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_portfolio.py -q`

- [ ] **Step 3: Implement iterative proportional scaling**

Start from each Phase 2A desired quantity. If total reservation exceeds cash, multiply all desired risk budgets by one common cash ratio, recalculate quantities with `size_for_risk()`, remove sub-two-share results, and repeat until feasible. Sort only for stable output serialization, never for allocation priority.

- [ ] **Step 4: Run focused tests and type check**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_portfolio.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_portfolio.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_portfolio.py tests/domain/backtester/test_swing_portfolio.py
git commit -m "feat: add cash-funded swing portfolio replay"
```

### Task 5: Ordered multi-symbol replay session

**Files:**
- Create: `src/qat/domain/backtester/swing_replay.py`
- Create: `tests/domain/backtester/test_swing_replay.py`
- Modify: `src/qat/domain/backtester/swing_results.py`

**Interfaces:**
- Consumes: per-symbol session data, membership by session, corporate actions, benchmark series, `AuthoritativeSwingEngine`, starting equity, cost model, and ambiguity policy.
- Produces: `AuthoritativeSwingReplay.run() -> SwingReplayResult` with decisions, fills, trades, equity points, abstentions, and ambiguities.

- [ ] **Step 1: Write failing one-symbol and multi-symbol golden replays**

Create fixed fixtures for:

- qualify at close, fill next open, stop later;
- cancel a gap above limit and never chase intraday;
- bank 1R partial, arm breakeven, trail on a later close, then exit;
- daily invalidation with protection surviving until next open;
- tenth-session exit;
- simultaneous signals scaled against cash;
- every qualified setup recorded in the signal-level arm while only the first
  unique same-pattern/same-symbol event remains edge-eligible until its
  isolated lifecycle closes;
- a fill below its limit preserving submitted quantity while calculating
  lifecycle `R_fill`, primary `R_order`, target, costs, and the resistance
  diagnostic;
- gap-down fills that land inside a formerly lower zone or place that zone in
  the new entry-to-2R path, both retained as baseline trades;
- double-bottom cancellation consuming one breakout event, recross permitting
  one later event within expiry, and a filled pair being permanently consumed;
- signal while open recorded but not traded; and
- repeated session input rejected before state changes.

```python
def test_daily_invalidation_keeps_stop_until_replacement_open() -> None:
    result = run_fixture("invalidation_then_gap_stop")
    assert result.trades[0].exit_reason == "protective_stop"
    assert "daily_invalidation" in result.trades[0].observed_triggers
    assert result.position_events.count_reason("sell_fill") == 1

def test_gap_down_can_make_formerly_lower_zone_block_actual_fill_without_invalidating() -> None:
    result = run_entry(limit="10.00", fill="9.40", stop="9.00", zone=("9.50", "9.60"))
    assert result.status is RunStatus.VALID
    assert result.trades[0].post_fill_resistance is PostFillResistanceDiagnostic.PATH_BLOCKED

def test_gap_down_inside_zone_is_retained_and_diagnosed() -> None:
    result = run_entry(limit="10.00", fill="9.90", stop="9.00", zone=("9.80", "9.95"))
    assert result.status is RunStatus.VALID
    assert result.trades[0].post_fill_resistance is PostFillResistanceDiagnostic.INSIDE_ZONE
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_replay.py -q`

- [ ] **Step 3: Implement the session loop in this exact order**

For each official session:

1. apply pre-open splits and symbol changes;
2. resolve gap stops and scheduled exits, then resolve prior entry instructions
   at their fixed submitted quantities;
3. process intraday protective stops and targets;
4. accrue ex-date dividend receivables and settle payment-date receivables to
   cash;
5. mark positions at the completed close;
6. evaluate lifecycle close rules for open positions;
7. evaluate setup evidence for every active member with finalized bars, recording but blocking any candidate whose symbol already has a position or pending entry;
8. allocate the same-session batch from the remaining flat-symbol candidates; and
9. append immutable equity and decision evidence.

Use symbol-specific calendars and membership; do not intersect all symbol dates. A missing required session is an abstention for that symbol, not a fabricated carried-forward bar.

For every entry fill, recompute and record actual price risk, exact costs, and
the actual-fill 2R resistance relationship from the unchanged structural stop.
Classify it as clear, inside-zone, or path-blocked. Keep all three as baseline
trades because the pre-open order has already executed; never resize, cancel,
or invalidate a run from this diagnostic. `RunStatus.INVALID` is reserved for
impossible execution or corrupt data, including a buy fill above its limit or
at/below invalidation. Mark the breakout-event ID used whenever its instruction
is emitted or cancelled, and mark its pattern-instance ID consumed only when a
fill is confirmed. A later signal for the same double-bottom pair requires a
distinct recross event within the 20-session expiry; no event is emitted while
price merely remains above the neckline.

In the same module, implement `replay_signal_candidates()` through the same
fill resolver. Use one fixed reference equity from the run manifest, normally
starting equity, for every candidate's 1% risk budget. This arm does not
compound and ignores cash competition. For each pattern and symbol, the first
unique event opens an isolated signal lifecycle; later events before that
lifecycle closes are recorded as `OVERLAPPING_EVENT` and cannot create a trade
or increase the promotion sample. Different patterns retain separate
lifecycles and may share a price path. The module writes all evidence and the
eligible `signal_trades`; it must not copy entry or exit logic. The separate
portfolio arm compounds current equity.

- [ ] **Step 4: Run focused, determinism, and no-broker tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_replay.py tests/safety/test_phase2_strategy_isolation.py -q`

Add a test that monkeypatches every production broker/OMS submission method to raise and proves a complete replay never invokes one.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_results.py tests/domain/backtester/test_swing_replay.py tests/safety/test_phase2_strategy_isolation.py
git commit -m "feat: replay authoritative swing lifecycle"
```

### Task 6: Corporate actions, delisting outcomes, and full Phase 2B regression

**Files:**
- Modify: `src/qat/domain/backtester/swing_replay.py`
- Modify: `src/qat/domain/backtester/swing_results.py`
- Modify: `src/qat/domain/backtester/swing_events.py`
- Create: `tests/domain/backtester/test_swing_corporate_actions.py`

**Interfaces:**
- Consumes: typed split, consolidation, cash-dividend, suspension, symbol-change, and delisting events supplied by Phase 2C's dataset adapter.
- Produces: `SplitEvent`, `CashDividendEvent`, `SymbolChangeEvent`, `SuspensionEvent`, `DelistingEvent`, quantity/cost/stop transformations, and auditable terminal fills.

- [ ] **Step 1: Write failing event tests**

Assert a 2-for-1 split doubles quantity and halves entry, stops, and target
without P&L or changing either initial risk denominator; a consolidation
preserves value; a position held at the close before an ex-date accrues one
dividend receivable and trade P&L once, a purchase on the ex-date receives
nothing, and the payment date converts the receivable to cash without more
P&L; a suspension defers a scheduled open exit; a symbol change preserves
position identity; a delisting uses its explicit realizable outcome; a
suspension resolving inside a 63-session tail exits at its first executable
opportunity; an unresolved position is marked to zero at event onset and closes
at named terminal session `T64` without recognizing the loss twice; and missing
identity, quantity, or event data needed for terminal valuation invalidates the
run. Include a multi-leg trade proving that equal halves at +1R and +2R
produce +1.5 `R_fill` gross before costs while `R_order` uses total net P&L over
the submitted-limit denominator.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_corporate_actions.py -q`

- [ ] **Step 3: Implement event transformations and invalid-run result**

Use the corporate-action event dataclasses established in Task 1 and add
`DividendReceivable` with declaration, ex, record, and payment dates. Entitlement
is the quantity held at the completed close immediately before the ex-session.
Accrue its face value on ex-date, attribute it to the originating trade, carry
it as a non-spendable portfolio asset, and settle it to cash on payment date.
When payment falls after a signal window, use only its authorized 63-session
tail; if payment remains later, retain an irrevocably established receivable at
face value at `T64` without loading the next partition.
Keep original and transformed quantities/prices in evidence. Dataset-wide
integrity errors return `RunStatus.INVALID` and suppress promotion scoring; they
do not produce a plausible partial result.

These immutable exact-decimal/rational historical events deliberately diverge
from `qat.domain.corporate_actions`. The existing package is a live broker
announcement/detection/stop-adjustment subsystem with float values and OMS
dependencies. Reuse vendor source facts only through Phase 2C's normalization
adapter; do not import its `AnnouncementStore`, `SplitDetector`, `StopAdjuster`,
or `CorporateActionMonitor` anywhere in the research dependency graph. Add a
transitive-import test that fails if this boundary is crossed.

- [ ] **Step 4: Run Phase 2A/2B and full repository verification**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_swing_portfolio.py tests/domain/backtester/test_swing_replay.py tests/domain/backtester/test_swing_corporate_actions.py tests/safety/test_phase2_strategy_isolation.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_portfolio.py src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_results.py`

Run: `.\.venv\Scripts\python.exe -m ruff check src/qat/domain/strategies/authoritative_swing src/qat/domain/backtester/swing_events.py src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_results.py src/qat/domain/backtester/swing_portfolio.py src/qat/domain/backtester/swing_replay.py tests/domain/strategies/authoritative_swing tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_swing_portfolio.py tests/domain/backtester/test_swing_replay.py tests/domain/backtester/test_swing_corporate_actions.py tests/safety/test_phase2_strategy_isolation.py`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS; the production strategy, OMS, and broker tests remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_results.py src/qat/domain/backtester/swing_events.py tests/domain/backtester/test_swing_corporate_actions.py
git commit -m "feat: replay swing corporate actions safely"
```
