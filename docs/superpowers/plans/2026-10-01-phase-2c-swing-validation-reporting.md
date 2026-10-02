# Phase 2C Swing Validation and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate engineering datasets, implement the frozen chronological,
statistical, structural-feasibility, and reporting machinery, and finish Phase 2
without opening promotion-tier development, validation, or holdout data.

**Architecture:** A signed catalog describes complete-calendar-month signal
windows, separate 63-session outcome tails, interstitial warm-up rows, and a
field-limited reference view. Partition-scoped loaders accept only authorized
handles. Pure planners implement WCR-S method audits, power, frequency,
incidence, and structural portfolio checks on fixtures. Phase 2C emits
engineering artifacts with `PORTFOLIO_RISK_DESIGN_PENDING`; the minimal
declaration/release gate and later promotion services are implemented by the
separate Phase 2D plan.

**Tech Stack:** Python 3.12, `Decimal`, `Fraction`, pandas, numpy, Ed25519 verification, Phase 2A/2B APIs, JSON/CSV/Markdown artifacts, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Complete Phase 2A and Phase 2B first.
- The existing static 2026 ASX snapshot is engineering evidence only and must always be labeled survivorship-biased and non-promotional.
- Promotion data must eventually be point-in-time, include delistings, and
  carry split/corporate-action provenance, but this plan never opens it.
- Allocate complete signal-eligible months initially 50/20/30 and add one
  63-session tail after each partition. The ten-year minimum excludes tails.
- Keep promotion-grade development, validation, holdout, and tails encrypted
  throughout Phase 2. Use synthetic fixtures for promotion-planner tests.
- Finish with `PORTFOLIO_RISK_DESIGN_PENDING`; no Phase 2C artifact can return
  promotion `PASS`.
- Freeze Phase 4 risk rules and externally timestamped declarations before the
  first promotion-tier outcome, then recompute all development and validation
  evidence under that final fingerprint.
- Do not optimize parameters or overwrite any previous artifact directory.
- Pattern edge gates use eligible non-overlapping signal trades in `R_order`;
  the cash-funded arm supplies portfolio safety and `R_fill` remains diagnostic.
- Primary results are regime-neutral; regime appears only in segmented reporting.
- A dataset-wide integrity error makes the run `INVALID` and suppresses promotion scoring.
- A promotion pass authorizes later shadow testing only.

## File Structure

- `src/qat/domain/backtester/swing_dataset.py` — signed catalog, shard schema,
  partition-scoped integrity validation, and loaders.
- `src/qat/domain/backtester/swing_validation.py` — complete-month signal
  windows, named executable boundaries, tails, attribution, and feasibility.
- `src/qat/domain/backtester/swing_reference.py` — field-limited incidence view,
  bucket merging, exposure windows, and bounds.
- `src/qat/domain/backtester/swing_statistics.py` — trade/portfolio metrics,
  WCR-S, Romano–Wolf, method audit, power, frequency, and sensitivities.
- `src/qat/domain/backtester/swing_promotion.py` — pure structural preflight and
  promotion verdict evaluation from already authorized immutable results.
- `src/qat/domain/backtester/swing_artifacts.py` — append-only JSON/CSV/checksum writer and Markdown report.
- `scripts/research/run_authoritative_swing.py` — offline command-line runner.
- `docs/phase-2-authoritative-swing-runbook.md` — operator run and interpretation guide.
- `tests/domain/backtester/test_swing_dataset.py` — data integrity tests.
- `tests/domain/backtester/test_swing_validation.py` — partition, named-boundary,
  tail-isolation, and no-cross-boundary tests, including optional `T65`.
- `tests/domain/backtester/test_swing_reference.py` — incidence, support,
  bucket, overlap, and holdout-cutoff tests.
- `tests/domain/backtester/test_swing_statistics.py` — statistical tests.
- `tests/domain/backtester/test_swing_promotion.py` — gate tests.
- `tests/domain/backtester/test_swing_artifacts.py` — serialization and append-only tests.
- `tests/integration/test_authoritative_swing_engineering_replay.py` — frozen small-universe end-to-end replay.

## Review Focus

- A symbol leaving the index or trading on a different set of sessions must not force common-index trimming or carried-forward bars; Task 1 pins it.
- A corrected file with the same filename must create a different manifest and decision lineage; Tasks 1 and 5 pin it.
- Warm-up history may precede a signal window, but its 63-session tail cannot
  create entries; Task 2 pins `T0`, `T1`, `T10`, `T11`, and `T64`.
- Tail-only, interstitial, warm-up, and partition-created partial months cannot
  enter the frequency model or `G_required`; Task 2 pins them.
- WCR-S and Romano-Wolf must pass every frozen mandatory scenario, never an
  average across scenarios; Task 3 pins size, power, and early extension.
- Incidence and structural portfolio viability are evaluated before duration;
  Task 4 prevents a failed design from recommending more data.
- Engineering, static-universe, invalid, or deferred-risk runs are
  structurally incapable of returning `PASS`; Tasks 4 and 6 pin it.

---

### Task 1: Frozen dataset schema and integrity validation

**Files:**
- Create: `src/qat/domain/backtester/swing_dataset.py`
- Create: `tests/domain/backtester/test_swing_dataset.py`

**Interfaces:**
- Consumes: a signed public dataset catalog and an authorized shard handle.
- Produces: `DatasetTier`, `DatasetCatalog`, `DatasetShardManifest`,
  `OfficialSessionCalendar`, `PartitionAccess`, `SwingDataset`, `validate_catalog()`,
  `load_swing_dataset(access)`, and `load_static_asx_engineering_dataset()`.

- [ ] **Step 1: Write failing manifest, membership, and corruption tests**

Use this frozen contract in fixtures. The catalog contains identities,
boundaries, hashes, and signatures but no holdout observations:

```text
dataset-catalog/
  manifest.json

operator-data/
  development-signal/
    sessions.csv
    membership.csv
    corporate_actions.csv
    benchmark.csv
    regimes.csv
    daily/BHP.AX.csv
  development-tail/
    ...
  validation-signal/
    ...
  validation-tail/
    ...
  holdout-signal/
    ...
  holdout-tail/
    ...

reference-view/
  manifest.json
  exposure_windows.csv
  bucket_boundaries.json
```

Daily columns are
`session,raw_open,raw_high,raw_low,raw_close,raw_volume,adjusted_open,adjusted_high,adjusted_low,adjusted_close,adjusted_volume,split_factor_numerator,split_factor_denominator,source,quality,finalized`.
Price, cash, and terminal-price fields are parsed from source text directly
into `Decimal`; split/consolidation ratios and cumulative factors are reduced
positive integer pairs; volume is an integer. Membership columns are
`session,symbol,is_member`. Corporate-action columns are
`event_id,symbol,declaration_date,ex_session,record_date,payment_date,kind,ratio_numerator,ratio_denominator,cash_amount,new_symbol,terminal_price,currency`.
Regime columns are
`session,label,probabilities_json,model_version,model_code_hash,configuration_hash,training_start,training_end,input_cutoff,max_input_session,input_hash,fit_id,output_hash`.
Official-calendar columns are
`calendar_date,session_kind,open_time,close_time,source,source_version,source_notice,reason,retrieved_at,source_hash,finalized`.
The file contains one row for every civil date in the effective interval.
`session_kind` is exactly `FULL`, `SHORTENED`, `AD_HOC_CLOSED`,
`SCHEDULED_CLOSED`, or `WEEKEND`; only the first two kinds project into the
ordered `official_sessions` sequence and require market rows.
The reference exposure view contains pseudonymous issuer, window start,
eligibility and index labels, market-cap/liquidity bucket labels, event category
and onset, consideration category, and custodian-source hash. It contains no
exact market-cap/traded-value path, OHLC path, strategy signal, or holdout row.

```python
def test_membership_is_point_in_time_without_index_intersection() -> None:
    dataset = load_swing_dataset(development_access(fixture_with_entry_exit_and_delisting()))
    assert dataset.members("2020-01-02") == {"OLD.AX"}
    assert dataset.members("2026-01-02") == {"NEW.AX"}
    assert dataset.bars["OLD.AX"][-1].session < dataset.bars["NEW.AX"][-1].session

def test_changed_source_bytes_fail_catalog_hash_validation() -> None:
    before = load_swing_dataset(development_access(dataset_dir())).catalog.dataset_id
    change_one_close_without_updating_manifest(dataset_dir())
    with pytest.raises(DatasetIntegrityError, match="hash"):
        load_swing_dataset(development_access(dataset_dir()))
    assert before

def test_development_loader_cannot_open_holdout_shard() -> None:
    access = development_access(sealed_fixture())
    with record_opened_paths() as opened:
        load_swing_dataset(access)
    assert not any(
        part.startswith("holdout")
        for path in opened
        for part in path.parts
    )

def test_catalog_validation_does_not_hash_sealed_observations() -> None:
    with record_opened_paths() as opened:
        validate_catalog(public_catalog())
    assert opened == {public_catalog().manifest_path}

def test_signed_official_calendar_preserves_ad_hoc_closure() -> None:
    dataset = load_swing_dataset(development_access(ad_hoc_closure_fixture()))
    row = dataset.official_calendar.row(closure_date())
    assert row.session_kind is SessionKind.AD_HOC_CLOSED
    assert row.source_notice == declared_closure_notice()
    assert closure_date() not in dataset.official_sessions
    assert dataset.official_calendar.source_hash == declared_calendar_hash()

def test_missing_normal_calendar_row_is_not_treated_as_a_closure() -> None:
    with pytest.raises(DatasetIntegrityError, match="calendar row"):
        load_swing_dataset(development_access(calendar_missing_normal_date()))

def test_tradable_rows_require_bars_and_closed_rows_prohibit_them() -> None:
    with pytest.raises(DatasetIntegrityError, match="tradable calendar row"):
        load_swing_dataset(development_access(full_session_without_market_rows()))
    with pytest.raises(DatasetIntegrityError, match="closed calendar row"):
        load_swing_dataset(development_access(ad_hoc_closure_with_market_rows()))

def test_reference_view_has_no_return_or_exact_value_columns() -> None:
    assert set(reference_view().columns).isdisjoint(
        {"open", "high", "low", "close", "market_cap", "traded_value", "return", "r_order"}
    )

def test_holdout_crossing_reference_window_is_excluded() -> None:
    assert max(w.end for w in reference_view().windows) < catalog().holdout_start
```

Also test duplicate sessions, missing civil dates, invalid session kinds,
missing closure notice/reason, shortened-session times, partial bars, non-finite values, raw OHLC geometry,
missing source/quality, unresolved symbol changes, missing delisting outcome,
mismatched currency, bad corporate-action ratio, benchmark gaps, and bars not
consistent with the official-calendar ledger. Duplicate/order/hash/schema/calendar/
corporate-action lineage errors invalidate the dataset. The rule-derived
`market_calendar.py` cross-check must disclose recurring-rule differences but
cannot overwrite the signed session sequence. A malformed symbol bar is retained
with a non-verified quality state so its symbol-session can abstain and be disclosed.
Test that source text `0.011` remains exactly `Decimal("0.011")`, factors such
as `3/10` remain reduced rationals, reconstructed raw prices agree after the
declared analytical quantum and raw normalization, and no binary float is
present in loaded semantic records. Test regime provenance by recomputing every
fixture prefix, changing later inputs without changing an earlier label, and
changing an included input so the provenance digest changes. Production
packaging verifies every input hash and recomputes a stratified sample covering
at least 1% of labels, 100 labels per model version, every calendar year, and
every transition type; any failure makes that model version `UNKNOWN`.

- [ ] **Step 2: Run and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_dataset.py -q`

- [ ] **Step 3: Implement manifest-first loading and typed events**

```python
class DatasetTier(StrEnum):
    ENGINEERING_SYNTHETIC = "engineering_synthetic"
    ENGINEERING_STATIC = "engineering_static"
    PROMOTION_POINT_IN_TIME = "promotion_point_in_time"

class EngineeringMode(StrEnum):
    STRICT_AUTHORITATIVE = "strict_authoritative"
    MECHANICAL_DIAGNOSTIC = "mechanical_diagnostic"

class SessionKind(StrEnum):
    FULL = "FULL"
    SHORTENED = "SHORTENED"
    AD_HOC_CLOSED = "AD_HOC_CLOSED"
    SCHEDULED_CLOSED = "SCHEDULED_CLOSED"
    WEEKEND = "WEEKEND"

@dataclass(frozen=True, slots=True)
class OfficialCalendarRow:
    calendar_date: date
    session_kind: SessionKind
    open_time: time | None
    close_time: time | None
    source: str
    source_version: str
    source_notice: str | None
    reason: str
    retrieved_at: datetime
    source_hash: str
    finalized: bool

@dataclass(frozen=True, slots=True)
class OfficialSessionCalendar:
    rows: tuple[OfficialCalendarRow, ...]
    official_sessions: tuple[date, ...]
    source_hash: str

@dataclass(frozen=True, slots=True)
class DatasetShardManifest:
    shard_id: str
    partition: str
    first_session: date
    last_session: date
    files_sha256: Mapping[str, str]
    merkle_root: str
    shard_kind: str
    signal_months: tuple[str, ...]
    boundary_ids: Mapping[str, date]

@dataclass(frozen=True, slots=True)
class DatasetCatalog:
    schema_version: str
    dataset_id: str
    tier: DatasetTier
    source: str
    adjustment_policy: str
    currency: str
    first_session: date
    last_session: date
    point_in_time_membership: bool
    benchmark_kind: str
    coverage_limit_reason: str | None
    shards: Mapping[str, DatasetShardManifest]
    operator_signature: str
    limitations: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SwingDataset:
    catalog: DatasetCatalog
    manifest: DatasetShardManifest
    official_calendar: OfficialSessionCalendar
    official_sessions: tuple[date, ...]
    bars: Mapping[str, tuple[FinalBar, ...]]
    membership: Mapping[date, frozenset[str]]
    corporate_actions: tuple[SwingMarketEvent, ...]
    benchmark: tuple[FinalBar, ...]
    regimes: Mapping[date, PointInTimeRegime]
    authorized_tail: DatasetShardManifest | None
```

The operator packager computes `dataset_id` and sealed shard hashes. The catalog
binds the official calendar source, version, retrieval time, content hash, and
effective interval. The packager requires one explicit row for every civil date,
derives `official_sessions` only from `FULL` and `SHORTENED`, requires matching
market rows for those dates, and rejects market rows on every closed date. The runner
validates the signed catalog without opening any observation shard, then
validates every file in the one authorized shard before constructing
`SwingDataset`. `PartitionAccess` exposes only explicit shard handles; a path
outside that capability is an error. A promotion-tier catalog must
assert point-in-time membership, an accumulation/equivalent total-return
benchmark, exact split factors, raw as-traded data, at least ten years of
complete signal-eligible months after tails are removed, and a complete
63-session tail after every partition; a shorter longest-complete period requires a nonempty
`coverage_limit_reason` printed in every report. Translate decimal rows to
Phase 2A `FinalBar`, point-in-time regime records, and Phase 2B corporate-action
event types. Structural
corruption invalidates the load; symbol-bar defects become non-verified bars
and recorded issues.

Development and validation processes receive no handle, mount, or decryption
key for later shards. Phase 2 tests only synthetic capabilities. Phase 2D later
records release/data-open receipts before returning production handles; only
then may this loader verify their bytes against the catalog.

The synthetic engineering dataset is split-only and must generate full golden
lifecycle coverage. The static adapter reads existing
`scripts/research/asx_bars/*.csv`: 95 files, exactly 500 sessions per file, from
26 August 2024 through 14 August 2026, with
`ts,open,high,low,close,volume`. Mark the cache `VENDOR_ADJUSTED` and inject
survivorship, absent-raw-price, dividend-separation, unavailable-action, and
under-three-year resistance-history limitations. In `STRICT_AUTHORITATIVE`
mode, provenance-dependent rules abstain and every candidate reaching resistance
returns `INSUFFICIENT_RESISTANCE_HISTORY`, so zero trades are valid.
`MECHANICAL_DIAGNOSTIC` may report pre-resistance pattern candidates, the same
typed history failure, candidates per 1,000 eligible symbol-months, and a
coverage-scaled ASX 200 planning proxy (`rate_per_symbol_month × 200`) beside
the observed 95-symbol exposure, with a symbol/month clustered range. It
must not shorten the resistance lookback, label candidates as trades, emit a
promotion verdict, or enter the formal frequency planner.

- [ ] **Step 4: Run tests and static checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_research_universe.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_dataset.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_dataset.py tests/domain/backtester/test_swing_dataset.py
git commit -m "feat: validate authoritative swing datasets"
```

### Task 2: Complete-month signal windows and named outcome tails

**Files:**
- Create: `src/qat/domain/backtester/swing_validation.py`
- Create: `tests/domain/backtester/test_swing_validation.py`

**Interfaces:**
- Consumes: signed catalog boundaries and official exchange sessions.
- Produces: `ValidationPartition`, `PartitionWindow`, `BoundarySessions`,
  `ValidationPlan`, `build_validation_plan()`, `attribute_partition()`, and
  `apply_terminal_valuation()`.

- [ ] **Step 1: Write failing exact-boundary and isolation tests**

```python
def test_named_sessions_pin_instruction_fill_exit_and_terminal() -> None:
    b = boundaries_for(
        final_entry_fill=date(2020, 12, 31), calendar=official_calendar_fixture()
    )
    assert b.t0 == previous_session(b.t1)
    assert b.t10 == advance_sessions(b.t1, 9)
    assert b.t11 == advance_sessions(b.t1, 10)
    assert b.t64 == advance_sessions(b.t1, 63)
    assert b.t65 == advance_sessions(b.t1, 64)

def test_ad_hoc_closure_uses_signed_sessions_not_rule_calendar() -> None:
    b = boundaries_for(final_entry_fill=t1(), calendar=calendar_with_ad_hoc_closure())
    assert b.calendar.row(ad_hoc_closure_date()).session_kind is SessionKind.AD_HOC_CLOSED
    assert b.t10 == tenth_signed_session_from_t1()
    assert ad_hoc_closure_date() not in b.tail_sessions

def test_missing_normal_calendar_date_invalidates_instead_of_advancing_boundary() -> None:
    with pytest.raises(DatasetIntegrityError):
        boundaries_for(final_entry_fill=t1(), calendar=calendar_with_missing_normal_row())

def test_instruction_that_would_fill_after_t1_is_rejected() -> None:
    assert not may_emit_instruction(session=boundaries.t1, boundaries=boundaries)

def test_tail_cannot_create_entries_or_clusters() -> None:
    result = replay_with_signal_in_tail()
    assert result.tail_entries == ()
    assert result.entry_month_clusters == signal_window_months()

def test_temporary_halt_resolves_inside_tail() -> None:
    trade = replay_halt(resume_session=boundaries.t40)
    assert trade.exit_session == boundaries.t40
    assert trade.terminal_valued is False

def test_unresolved_position_is_zero_at_onset_and_closed_at_t64() -> None:
    trade, equity = replay_unresolved_halt(onset=boundaries.t8)
    assert equity.at(boundaries.t8).position_value == 0
    assert trade.exit_session == boundaries.t64
    assert trade.terminal_value == 0
    assert trade.loss_recognition_count == 1

def test_ten_year_minimum_excludes_three_tails() -> None:
    plan = build_validation_plan(catalog_with_ten_signal_years_plus_tails())
    assert plan.signal_history_calendar_years >= 10
    assert all(len(p.tail_sessions) == 63 for p in plan.partitions)
```

Also prove the initial signal windows approximate 50/20/30 by complete month,
the holdout has at least 36 complete eligible months, no partition-created
partial month contributes entries or `G`, no moving block crosses a tail,
interstitial sessions cannot trade, and a forward-only holdout extension leaves
development, validation, and holdout start unchanged.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 3: Implement the chronological contract**

Allocate complete entry-fill months, then attach a distinct 63-session tail to
each partition. Name `T0`, `T1`, `T10`, `T11`, `T64`, and optional `T65`
exactly as the spec.
The final instruction is at `T0`, final fill at `T1`, tenth holding close at
`T10`, scheduled exit open at `T11`, and tail terminal at `T64`. Partition
ownership follows entry fill. Tail and interstitial rows may resolve positions
or warm indicators only; they cannot emit instructions, add entries, count
toward signal duration, or create frequency clusters.

Keep every eligible trade in the denominator. Resolve a halt at its first
tradable opportunity through `T64`; otherwise apply documented irrevocable
consideration or zero. Mark equity to zero at onset, keep cash unavailable, and
avoid duplicate loss at terminal close. Missing data needed to apply the rule
invalidates the run. Do not implement `BOUNDARY_CENSORED` exclusion.

All boundary advancement uses `SwingDataset.official_sessions`. The
sequence is the validated tradable projection of the complete signed calendar
ledger. The rule-derived ASX calendar is a fixture and recurring-holiday
cross-check only; it cannot invent a promotion session, override an ad hoc
closure, reclassify a signed row, or fill a calendar gap.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_validation.py tests/domain/backtester/test_swing_validation.py
git commit -m "feat: define swing signal windows and outcome tails"
```
### Task 3: WCR-S method audit, power, and frequency feasibility

**Files:**
- Create: `src/qat/domain/backtester/swing_statistics.py`
- Create: `src/qat/domain/backtester/swing_method_audit.py`
- Create: `tests/domain/backtester/test_swing_statistics.py`
- Create: `tests/domain/backtester/test_swing_method_audit.py`

**Interfaces:**
- Consumes: eligible non-overlapping signal trades, complete entry-month frame,
  cash-funded equity, operator-declared `delta_MME`, frozen scenario matrix,
  and complete-month entry-count vectors.
- Produces: `SwingStatistics`, `MethodAuditProtocol`, `MethodAuditResult`,
  `PowerRequirement`, `FrequencyPlan`, `wcr_s_mean_test()`,
  `romano_wolf_stepdown()`, `audit_method_size()`, `audit_power()`, and
  `plan_holdout_duration()`.

`FeasibilityStatus` is exactly `FEASIBLE`, `DATASET_INSUFFICIENT`, or
`FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON`. `FrequencyPlan` always records the
required duration when one exists, available untouched duration, binding
pattern and rate source, predictive probabilities, and whether forward-only
acquisition could make the plan feasible.

- [ ] **Step 1: Write failing metric, size, power, and duration tests**

```python
def test_wcr_s_reference_parity_for_intercept_only_mean() -> None:
    assert wcr_s_mean_test(frozen_cluster_fixture()) == reference_wcr_s_result()

def test_every_mandatory_scenario_must_pass() -> None:
    result = audit_method_size(one_failed_scenario())
    assert result.status is MethodStatus.METHOD_INADEQUATE
    assert result.worst_scenario == "heavy_imbalance_partial_null"

def test_partial_nulls_enter_romano_wolf_audit() -> None:
    protocol = declared_protocol()
    assert set(protocol.null_configurations) == {
        "000", "d00", "0d0", "00d", "dd0", "d0d", "0dd"
    }

def test_sequential_monte_carlo_extension() -> None:
    near = audit_at_20k(upper_limit_within_points="0.25")
    assert near.requested_outer_runs == 100_000

def test_final_audit_uses_upper_monte_carlo_limit() -> None:
    result = audit_at_100k(point_estimate_below_cap=True, upper_limit_above_cap=True)
    assert result.status is MethodStatus.METHOD_INADEQUATE

def test_tail_only_months_are_absent_but_real_zero_months_remain() -> None:
    vector = eligible_month_count_vector(plan(), replay())
    assert development_tail_month() not in vector
    assert genuine_zero_entry_month() in vector

def test_required_duration_is_found_before_available_data_check() -> None:
    plan = plan_holdout_duration(requirement=needs_111_months(), available_months=36)
    assert plan.required_months == 111
    assert plan.status is FeasibilityStatus.DATASET_INSUFFICIENT

def test_no_duration_through_120_is_frequency_inadequate() -> None:
    assert plan_holdout_duration(near_zero_frequency()).status is FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON

def test_dataset_shortfall_maps_to_insufficient_evidence() -> None:
    verdict = evaluate_promotion(case_with_feasibility(FeasibilityStatus.DATASET_INSUFFICIENT))
    assert verdict.status is PromotionStatus.INSUFFICIENT_EVIDENCE
    assert verdict.feasibility_reason is FeasibilityStatus.DATASET_INSUFFICIENT
    assert verdict.forward_acquisition_could_help is True

def test_frequency_shortfall_maps_to_insufficient_evidence_without_extension_advice() -> None:
    verdict = evaluate_promotion(
        case_with_feasibility(FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON)
    )
    assert verdict.status is PromotionStatus.INSUFFICIENT_EVIDENCE
    assert verdict.recommended_holdout_months is None

def test_feasible_planner_result_is_not_a_promotion_pass() -> None:
    verdict = evaluate_promotion(case_where_feasibility_is_only_satisfied_gate())
    assert verdict.feasibility_reason is FeasibilityStatus.FEASIBLE
    assert verdict.status is PromotionStatus.INSUFFICIENT_EVIDENCE

def test_engineering_status_remains_pending_while_feasibility_is_reported() -> None:
    verdict = evaluate_promotion(engineering_case_with_synthetic_feasibility())
    assert verdict.status is PromotionStatus.PORTFOLIO_RISK_DESIGN_PENDING
    assert verdict.feasibility_reason is not None
```

Also pin signal-level `R_order` expectancy, diagnostic `R_fill`, profit factor,
ES1/ES5 reporting without an ES promotion threshold, maximum drawdown, exposure,
turnover, costs, concentration, regime/year/symbol groups, overlap suppression,
fixed signal reference equity, and compounding cash-funded equity.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_method_audit.py -q`

- [ ] **Step 3: Implement the frozen inferential audit**

Implement exact WCR-S for the intercept-only mean using restricted,
jackknife-transformed cluster scores and 9,999 common month weights. Invert the
one-sided test for a 97.5% lower bound. Apply one-sided Romano-Wolf stepdown at
5% FWER across the three patterns and preserve common weights. Compare with a
small independent reference that imports no production helper.

The generic pilot accepts only declared synthetic families and retains every
attempt. `METHOD_AUDIT_DECLARED` later freezes the selected method, pilot hash,
scenario generators, code, seeds, and caps before development outcomes.
Mandatory scenarios cover joint 3-, 6-, and 12-month blocks; observed and
stressed month-size imbalance; empirical skew; complete and every partial null;
and the calibrated terminal-event envelope. The broader
`0.2%/0.5%/1% × -20R/-50R` grid is diagnostic unless calibration places a cell
inside the mandatory envelope. Recenter the entire contaminated distribution
to true mean zero for size and shift it by `delta_MME` for power.

With 9,999 inner draws, start with 20,000 outer simulations. Accept early only
when the upper 95% Monte Carlo limit is at least 0.25 percentage points below
3.25% for the confidence gate and 6% for FWER. Reject early when the lower limit
is at least 0.25 points above. Otherwise extend to 100,000. Every mandatory cell
must pass. At 100,000, accept a cell only when its upper 95% Monte Carlo limit
is less than or equal to the applicable 3.25% or 6% cap; a point estimate below
the cap is insufficient. Every other final result is `METHOD_INADEQUATE`, which
blocks promotion and cannot be repaired with a trimmed or winsorized estimand.

Recompute `N_required >= 100` and `G_required` under the accepted method using
the maximum requirement across mandatory power scenarios. `delta_MME` is
positive, externally declared, and cannot rise to reduce sample requirements.
A nonpositive development-plus-validation expectancy refuses holdout.

- [ ] **Step 4: Implement complete-month frequency planning**

Construct monthly count vectors from complete eligible signal months. Keep real
zero-entry months. Exclude tail, warm-up, interstitial, and partition-created
partial months; never join a block across a tail. Jointly resample all patterns
with circular 3-, 6-, and 12-month blocks.

For each pattern define the stress rate as the minimum of its lowest rolling
36-month development rate, full validation-window rate, and one-sided 90% lower
predictive rate. Treat the rolling minimum as a named historical stress, not a
quantile estimate, and publish the number and overlap of its windows. Scan 36
through 120 months. Require at least 90% baseline and 80% stressed joint
probability that every pattern reaches `N_required` and `G_required`. Publish
which rate binds, expected and 10th/5th/1st percentile counts, required,
available, and shortfall months. Extension is forward-only.

- [ ] **Step 5: Run focused tests and type checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_method_audit.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_statistics.py src/qat/domain/backtester/swing_method_audit.py`

- [ ] **Step 6: Commit**

```powershell
git add src/qat/domain/backtester/swing_statistics.py src/qat/domain/backtester/swing_method_audit.py tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_method_audit.py
git commit -m "feat: audit swing inference and holdout feasibility"
```
### Task 4: Incidence calibration, structural risk, and pure verdicts

**Files:**
- Create: `src/qat/domain/backtester/swing_reference.py`
- Create: `src/qat/domain/backtester/swing_promotion.py`
- Create: `tests/domain/backtester/test_swing_reference.py`
- Create: `tests/domain/backtester/test_swing_promotion.py`

**Interfaces:**
- Consumes: signed field-limited reference view, Phase 4 risk-policy fixture,
  immutable replay results, method/power/frequency results, and evidence tier.
- Produces: `IncidenceCalibration`, `StructuralRiskResult`, `GateResult`,
  `PromotionVerdict`, `calibrate_terminal_incidence()`,
  `evaluate_structural_risk()`, and `evaluate_promotion()`.

`PromotionVerdict` retains `feasibility_reason`, required and available months,
binding source, recommended operator action, and whether forward acquisition
could help even when its overall status is a different enum.

`PromotionStatus` includes `PORTFOLIO_RISK_DESIGN_PENDING`,
`INCIDENCE_DATA_INSUFFICIENT`, `PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE`,
`INSUFFICIENT_EVIDENCE`, `METHOD_INADEQUATE`,
`TERMINAL_OUTCOME_SENSITIVE`, `FAIL`,
`EDGE_PASS_PORTFOLIO_RISK_BLOCKED`, and `PASS`.

- [ ] **Step 1: Write failing incidence and structural tests**

```python
def test_event_date_deterioration_does_not_remove_window() -> None:
    window = eligible_window_at_start(company_that_fails_after_losing_liquidity())
    assert window.event_within_ten_sessions is True

def test_holdout_crossing_exposure_window_is_excluded() -> None:
    assert not incidence_windows().contains(window_crossing_holdout_start())

def test_bucket_merge_is_driven_by_exposure_not_event_count() -> None:
    assert merge_buckets(events_hidden(), min_issuer_years=500, min_issuers=100) == declared_merge_path()

def test_overlapping_windows_use_clustered_bound() -> None:
    result = calibrate_terminal_incidence(reference_view())
    assert result.primary_bound == max(result.clustered_upper, result.landmark_exact_upper)

def test_under_supported_incidence_stops_duration_planning() -> None:
    result = calibrate_terminal_incidence(reference_view_below_merged_support())
    assert result.status is PromotionStatus.INCIDENCE_DATA_INSUFFICIENT
    assert result.recommended_holdout_months is None

def test_phase2_engineering_cannot_pass() -> None:
    assert evaluate_promotion(engineering_case()).status is PromotionStatus.PORTFOLIO_RISK_DESIGN_PENDING

def test_structurally_infeasible_stops_before_duration_advice() -> None:
    result = evaluate_structural_risk(uncapped_tight_stop_portfolio())
    assert result.status is StructuralStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
    assert result.recommended_holdout_months is None

def test_zero_price_loss_is_applied_to_every_funded_trade_placement() -> None:
    result = evaluate_structural_risk(cash_funded_replay())
    assert result.placements_tested == len(all_exposed_trade_session_pairs(cash_funded_replay()))
    assert result.max_drawdown == max(p.max_drawdown for p in result.placements)

def test_halted_position_remains_exposed_until_session_before_terminal_exit() -> None:
    pairs = all_exposed_trade_session_pairs(unresolved_halt_ending_at_t64())
    assert (halted_trade_id(), previous_session(boundaries().t64)) in pairs
    assert (halted_trade_id(), boundaries().t64) not in pairs

def test_incremental_exposure_sweep_matches_brute_force_reference() -> None:
    optimized = evaluate_structural_risk(exposure_parity_fixture())
    reference = brute_force_structural_risk(exposure_parity_fixture())
    assert optimized.placement_drawdowns == reference.placement_drawdowns
    assert optimized.parity_digest == reference.parity_digest

def test_exposure_sweep_does_not_rerun_strategy_or_fill_resolution(monkeypatch) -> None:
    monkeypatch.setattr(AuthoritativeSwingEngine, "evaluate", forbidden)
    monkeypatch.setattr(swing_fills, "resolve_protective_session", forbidden)
    assert evaluate_structural_risk(frozen_baseline_replay()).placements_tested > 0

def test_recovery_only_pass_is_non_promotable() -> None:
    result = evaluate_promotion(conservative_fails_recovery_passes())
    assert result.status is PromotionStatus.TERMINAL_OUTCOME_SENSITIVE
```

Also test event categories, known consideration, short halts, unresolved
63-session suspensions, former members and delisted names, common-support
exclusion, exact merge ordering, minimum 500 issuer-years and 100 issuers,
fewer-than-five-event exact-bound behavior, entry-count-only strategy weights,
25-percentage-point highest-risk concentration shift, and worst-bucket
sensitivity.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_reference.py tests/domain/backtester/test_swing_promotion.py -q`

- [ ] **Step 3: Implement support-matched incidence**

The custodian reference view contains no exact value or return paths. Start with
smaller/larger market cap crossed with lower/higher traded-value liquidity,
split at exposure-weighted medians of point-in-time eligible strategy members.
Admit broader ASX ordinary equities only inside the eligible universe's common
market-cap, price, and liquidity support, including former members and delisted
names. Outside-support micro-caps have zero primary weight and form a separate
sensitivity.

For every eligible start `(issuer, session)`, freeze classification and set
`Y=1` when a qualifying event begins in the next ten sessions. An onset may mark
up to ten overlapping starts because each represents a different exposed trade.
Cluster the primary one-sided 95% bound by issuer-year and take the larger of it
and an exact upper bound from non-overlapping landmark windows. Require 500
unique issuer-years and 100 issuers per effective bucket. Merge liquidity bands
inside market-cap band, then market-cap bands, without event-count access.
Primary weights use development/validation entry counts and labels only; add a
mandatory +25 percentage-point highest-risk shift and a non-promotional
all-worst-bucket sensitivity.

If the declared merge path still cannot reach both support minima, return
`INCIDENCE_DATA_INSUFFICIENT`, report the support and attempted merges, and stop
probabilistic calibration, method/power work, and duration advice. A
deterministic design-envelope diagnostic may still be written but cannot
authorize promotion.

- [ ] **Step 4: Implement structural and tail gates**

Run the Phase 4 design-envelope check before promotion outcomes. After signed
development and validation release, run the funded-trade structural preflight
before method, power, or duration planning. For each funded development or
validation trade, inject onset at every official session on which the position
is exposed, starting immediately after entry fill and ending before baseline
exit. Mark it to zero at that onset, retain cash lock through `T64`, recompute
the actual equity path, and take the worst trade/session placement. Repeat the
identical test on holdout and authorized full-history results only after
exposure. Require worst placement and the 95th-percentile probabilistic tail
drawdown no greater than 20% at every applicable stage. Phase 4 policy supplies notional,
stop-distance, cost-to-risk, aggregate, and sector caps. The design envelope is
`1 - (1 - ordinary_drawdown_budget) * (1 - zero_price_loss)`.

Build the baseline event-sourced equity ledger once. For each placement, apply
an exact-decimal sparse delta stream to cached position marks, exit proceeds,
dividends, cash locks, and the affected equity suffix; never rerun signal
generation, fill resolution, or allocation. A halt does not end exposure. A
position exiting on resumption at `T40` accepts onset placements only through
the prior official session; an unresolved position terminally closed at `T64`
accepts them through the official session immediately before `T64`, with zero
mark and unavailable cash through `T64`. Compare every
placement with a brute-force reference on frozen fixtures and compare a
deterministic stratified production sample spanning ordinary exits, dividends,
halts, resumptions, and terminal valuations. Record affected point count,
sample identities, and parity digest.

For probabilistic stress, select trades using calibrated bucket probabilities
and common market/sector shocks, replace outcomes at event onset, and recompute
`R_order`, `R_fill`, costs, cash, and equity. Require the fifth percentile of
simulated mean net `R_order` above zero and verify it against an analytical
expected-value calculation. Report signal and cash ES1/ES5 without an ES pass
threshold. Report deterministic simultaneous two-issuer zero as a sensitivity.
Never impose a single-event mean gate whose effect dilutes with `N`.

When conservative terminal valuation fails but the later-recovery sensitivity
passes every otherwise applicable gate, return
`TERMINAL_OUTCOME_SENSITIVE`; it is non-promotable. If development/validation
structural preflight fails, return
`PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE` with no duration advice. A revised
Phase 4 policy must enter a new signed protocol lineage and replay development
and validation from the beginning; an unopened, unchanged sealed holdout
remains eligible, subject to recomputed feasibility and permit inputs.

Keep the seven pure edge gates and status taxonomy from the spec. During Phase
2, every result is engineering-tier and must return
`PORTFOLIO_RISK_DESIGN_PENDING`, `INVALID`, or another non-pass status. Actual
permit and exposure enforcement belongs to Phase 2D.

Implement one exhaustive feasibility mapping: `FEASIBLE` continues through the
remaining gates without implying `PASS`; `DATASET_INSUFFICIENT` and
`FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON` return
`INSUFFICIENT_EVIDENCE` with their original reason retained. The latter carries
no recommendation to extend within the declared 120-month maximum. Method and
incidence failures retain `METHOD_INADEQUATE` and
`INCIDENCE_DATA_INSUFFICIENT` precedence. Phase 2 engineering reports the
synthetic planner result but keeps overall status
`PORTFOLIO_RISK_DESIGN_PENDING`.

- [ ] **Step 5: Run focused tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_reference.py tests/domain/backtester/test_swing_promotion.py -q`

```powershell
git add src/qat/domain/backtester/swing_reference.py src/qat/domain/backtester/swing_promotion.py tests/domain/backtester/test_swing_reference.py tests/domain/backtester/test_swing_promotion.py
git commit -m "feat: evaluate swing incidence and structural feasibility"
```
### Task 5: Append-only artifacts, checksums, and human report

**Files:**
- Create: `src/qat/domain/backtester/swing_artifacts.py`
- Create: `tests/domain/backtester/test_swing_artifacts.py`

**Interfaces:**
- Consumes: dataset/validation manifests, replay results, statistics, promotion verdicts, and sensitivities.
- Produces: `write_swing_artifacts(run, output_root) -> Path`.

- [ ] **Step 1: Write failing schema, checksum, caveat, and overwrite tests**

Require this run directory:

```text
<run-id>/
  manifest.json
  decisions.jsonl
  fills.csv
  trades.csv
  equity.csv
  metrics.json
  promotion.json
  method_audit.json
  feasibility.json
  reference_incidence.json
  report.md
  SHA256SUMS
```

```python
def test_existing_run_directory_is_never_overwritten(tmp_path: Path) -> None:
    path = write_swing_artifacts(run(), tmp_path)
    with pytest.raises(FileExistsError):
        write_swing_artifacts(run(), tmp_path)
    assert path.exists()

def test_engineering_report_leads_with_survivorship_warning(tmp_path: Path) -> None:
    path = write_swing_artifacts(engineering_run(), tmp_path)
    report = (path / "report.md").read_text(encoding="utf-8")
    assert "SURVIVORSHIP-BIASED — NOT PROMOTION EVIDENCE" in report.splitlines()[:8]

def test_phase2_artifact_cannot_claim_promotion_ready(tmp_path: Path) -> None:
    result = json.loads((write_swing_artifacts(engineering_run(), tmp_path) / "promotion.json").read_text())
    assert result["status"] == "PORTFOLIO_RISK_DESIGN_PENDING"
```

Also verify every checksum, stable JSON ordering, no NaN/Infinity
serialization, evidence IDs in trade rows, separate pattern/combined sections,
ambiguity sensitivity, regime segmentation, and explicit absence of holdout
authorization metadata in Phase 2.
The manifest records fixed signal-level reference equity; eligible and
overlap-suppressed trade counts; `R_order` and `R_fill`; catalog/shard
identities; `T0/T1/T10/T11/T64/T65`; signal, tail, and interstitial windows;
terminal-valued outcomes and influence; decimal/rational numeric policy;
liquidity profile; WCR-S implementation/reference identity; generic pilot and
scenario-matrix hashes; size caps; method status; power and duration planner
inputs/outputs; incidence support, buckets, merges, bounds, and weights;
structural drawdown preflight; point-in-time regime provenance; and
multiplicity method. Later Phase 2D runs add declaration, permit, rehearsal,
ledger, exposure, and bundle receipts without changing this base schema.
Decimal semantic values serialize
canonically as strings. The report distinguishes edge gates from portfolio
safety and renders `INCIDENCE_DATA_INSUFFICIENT`,
`PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE`, `TERMINAL_OUTCOME_SENSITIVE`, and
`EDGE_PASS_PORTFOLIO_RISK_BLOCKED` explicitly.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_artifacts.py -q`

- [ ] **Step 3: Implement atomic append-only writing**

Write into a sibling temporary directory, calculate all hashes, write `SHA256SUMS`, then atomically rename to the deterministic run ID. Refuse an existing destination. Keep `created_at` in packaging metadata but exclude it from semantic IDs and comparison hashes.

- [ ] **Step 4: Run focused tests and verify a fixture report manually**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_artifacts.py -q`

Open the generated fixture `report.md` and confirm the evidence tier, period,
costs, fill model, limitations, per-pattern results, combined portfolio,
sensitivities, and deferred-risk status are visible without reading JSON.
Confirm it reports primary
`R_order`, diagnostic `R_fill`, and minimum-R stress; eligible, suppressed, and
terminal-valued counts; maximum
and average single-position notional exposure; cost-to-risk ratios; days above
declared concentration levels; gap losses beyond the planned 1% risk; and the
uncapped portfolio's status as a concentration/gap-risk stress case rather than
a deployable forecast. It also reports named tail boundaries, method-audit and
incidence status, duration feasibility, liquidity participation/capacity,
post-fill resistance classifications, the strict-versus-mechanical engineering
mode, and every declared non-promotional sensitivity including 2% sizing.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_artifacts.py tests/domain/backtester/test_swing_artifacts.py
git commit -m "feat: write reproducible swing evidence artifacts"
```

### Task 6: Offline runner and static ASX engineering replay

**Files:**
- Create: `scripts/research/run_authoritative_swing.py`
- Create: `tests/integration/test_authoritative_swing_engineering_replay.py`
- Create: `docs/phase-2-authoritative-swing-runbook.md`

**Interfaces:**
- Consumes: `--catalog`, an authorized engineering shard handle,
  `--engineering-mode`, `--out`, `--partition`, `--ambiguity-policy`, and
  `--volume-multiplier`.
- Produces: one artifact directory and process exit code 0 for a valid
  engineering replay or 2 for invalid data/configuration. Promotion-tier and
  service-profile arguments belong to Phase 2D and are rejected here.

- [ ] **Step 1: Write failing CLI and frozen end-to-end tests**

```python
def test_static_asx_run_cannot_claim_promotion(tmp_path: Path) -> None:
    completed = run_cli("--catalog", "static-asx", "--out", str(tmp_path), "--partition", "development")
    assert completed.returncode == 0
    promotion = read_only_run(tmp_path, "promotion.json")
    assert promotion["status"] == "PORTFOLIO_RISK_DESIGN_PENDING"

def test_cli_never_fetches_network_data(monkeypatch, tmp_path: Path) -> None:
    deny_socket_connect_and_dns(monkeypatch)
    deny_subprocess_and_process_launch(monkeypatch)
    deny_known_http_clients(monkeypatch)
    assert run_small_fixture(tmp_path).returncode == 0
```

`deny_known_http_clients()` covers `requests`, `urllib`, `httpx`, `aiohttp`, and
configured broker SDK entry points; the socket/DNS guard remains the lower-level
backstop.

The split-only synthetic integration fixture must contain one trade per pattern,
one rejected setup, one abstention, one ambiguous fill, one confluence
candidate, one capacity-bound instruction, and both blocked post-fill resistance
diagnostics. It also includes a `3/10` split factor, a lower fill that produces
different `R_order` and `R_fill`, an overlap-suppressed signal, an ex-date
dividend receivable and later cash settlement, and point-in-time regime
metadata. The strict static-cache fixture may contain zero trades but must
produce the exact provenance abstentions. Mechanical static mode must be
structurally incapable of promotion.
The synthetic fixture also pins `T0/T1/T10/T11/T64/T65`, a temporary halt resolving
inside the tail, an unresolved halt valued at zero on onset, terminal close
without duplicate loss, and a tail signal that cannot enter.

The real static replay asserts the baseline inventory exactly: 95 files, 500
sessions per file, 26 August 2024 through 14 August 2026. Strict mode reports
provenance failures and `INSUFFICIENT_RESISTANCE_HISTORY`. Mechanical mode
stops before resistance, reports candidates per 1,000 eligible symbol-months,
and computes its ASX 200 planning proxy from symbol-session exposure with a
symbol/month clustered range. It must not run a shorter-lookback resistance
variant or pass those counts to `plan_holdout_duration()`.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_authoritative_swing_engineering_replay.py -q`

- [ ] **Step 3: Implement the offline coordinator and runbook**

The CLI loads only the authorized frozen shard, constructs exact cost/liquidity
profiles, validates partition capability without probing later shards, and runs
four `ReplayArm` values: each pattern and
`COMBINED`. It runs the baseline plus approved sensitivities (volume
1.25/1.5/2.0, optimistic ambiguity, doubled costs, post-fill resistance
exclusion, liquidity/impact, `R_fill`, minimum-R stress, and 2% sizing), writes artifacts, prints their
absolute path, and never changes deployed settings. Only frozen baseline
pattern arms enter the Romano–Wolf family; sensitivities remain diagnostic.

The runbook documents the exact commands, evidence tiers, signed catalog and
physical signal/tail shards, complete-month 50/20/30 allocation,
`T0/T1/T10/T11/T64/T65`, entry-fill ownership, terminal valuation, the structural
extract allowlist, declaration order, method and incidence audits, Phase 4
dependency, Phase 2D handoff, exit codes, artifact meanings, engineering
statuses, and why neither static nor synthetic evidence can promote the
strategy. It must state that Phase 2 opens no promotion-tier observation.
It also documents every `FeasibilityStatus` to `PromotionStatus` mapping and
operator action, the complete calendar-row contract, the exposure-sweep parity
evidence, and the boundary rule for halted positions through `T64`.

- [ ] **Step 4: Run the frozen integration test and actual engineering replay**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_authoritative_swing_engineering_replay.py -q`

Run: `.\.venv\Scripts\python.exe scripts/research/run_authoritative_swing.py --catalog synthetic-golden --partition development --out data/phase2-engineering-synthetic`

Run: `.\.venv\Scripts\python.exe scripts/research/run_authoritative_swing.py --catalog static-asx --engineering-mode strict_authoritative --partition development --out data/phase2-engineering-static`

Expected: both exit 0 with absolute artifact paths and no broker/network/process
access. The synthetic run exercises every pattern and lifecycle path. The
static run leads with survivorship and vendor-adjustment warnings, cannot pass
promotion, and may report zero trades when strict provenance rules abstain.

- [ ] **Step 5: Commit code and documentation, excluding runtime artifacts**

```powershell
git add scripts/research/run_authoritative_swing.py tests/integration/test_authoritative_swing_engineering_replay.py docs/phase-2-authoritative-swing-runbook.md
git commit -m "feat: run Phase 2 swing engineering evidence"
```

### Task 7: Final determinism, safety, and repository verification

**Files:**
- Modify only files implicated by failures found in this task.
- Create: `tests/reference/authoritative_swing_reference.py`
- Create: `tests/domain/backtester/test_swing_reference_parity.py`
- Create: `tests/domain/backtester/test_swing_prefix_invariance.py`
- Create: `docs/phase-2-authoritative-swing-checkpoint.md`

**Interfaces:**
- Consumes: the complete Phase 2A/2B/2C implementation.
- Produces: reproducible verification evidence and a checkpoint report.

- [ ] **Step 1: Run the same frozen integration replay twice**

Run the integration fixture into two empty temporary output roots. Compare `decisions.jsonl`, `fills.csv`, `trades.csv`, `equity.csv`, `metrics.json`, and `promotion.json` byte-for-byte. Compare semantic manifest fields while excluding `created_at` and artifact path. Verify exact decimal strings and IDs are unchanged by equivalent source decimal spellings.

For every evaluated session `t`, compare the normal result with a dataset
truncated at `t`, then mutate all later bars, membership rows, corporate actions,
and calendar inputs. The decision and evidence at `t` must remain byte-identical.
Compare production rational price conversion, tick, EMA, ATR, resistance,
bisection sizing, WCR-S, Romano-Wolf, incidence, and duration outputs to small
test-only reference implementations that import no production helpers or
decimal context. Prove Phase 2 cannot accept a promotion-tier capability,
cannot emit `PASS`, and cannot expose post-signal outcomes through the blinded
structural extract schema.

- [ ] **Step 2: Run focused safety and Phase 2 tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_swing_portfolio.py tests/domain/backtester/test_swing_replay.py tests/domain/backtester/test_swing_corporate_actions.py tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_swing_validation.py tests/domain/backtester/test_swing_reference.py tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_method_audit.py tests/domain/backtester/test_swing_promotion.py tests/domain/backtester/test_swing_artifacts.py tests/domain/backtester/test_swing_reference_parity.py tests/domain/backtester/test_swing_prefix_invariance.py tests/integration/test_authoritative_swing_engineering_replay.py tests/safety/test_phase2_strategy_isolation.py -q`

Expected: PASS.

- [ ] **Step 3: Run repository-wide quality gates**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts/research/run_authoritative_swing.py`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing src/qat/domain/backtester/swing_events.py src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_results.py src/qat/domain/backtester/swing_portfolio.py src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_dataset.py src/qat/domain/backtester/swing_validation.py src/qat/domain/backtester/swing_reference.py src/qat/domain/backtester/swing_statistics.py src/qat/domain/backtester/swing_method_audit.py src/qat/domain/backtester/swing_promotion.py src/qat/domain/backtester/swing_artifacts.py`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS. Record command, result, duration, and environment in the checkpoint.

- [ ] **Step 4: Write the Phase 2 checkpoint**

Document implemented spec sections, commits, decimal/reference/prefix/isolation
test evidence, both engineering replay artifact IDs, strict static abstentions,
survivorship limitation, `PORTFOLIO_RISK_DESIGN_PENDING`, proof that no
promotion-grade observation was released, Declaration Authority/Phase 2D
handoff status, unchanged production behavior, and the deferred Option 3 parity
replay. Do not state that the strategy has an edge.

- [ ] **Step 5: Commit**

```powershell
git add docs/phase-2-authoritative-swing-checkpoint.md
git commit -m "docs: record Phase 2 swing verification"
```
