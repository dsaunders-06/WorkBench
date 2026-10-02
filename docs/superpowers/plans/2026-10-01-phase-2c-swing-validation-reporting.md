# Phase 2C Swing Validation and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate datasets, enforce the approved chronological protocol, calculate promotion evidence, and emit reproducible machine and human artifacts for the Phase 2 engine and replay.

**Architecture:** A signed dataset catalog describes physically separate
development, validation, holdout, and holdout-tail shards. Partition-scoped
loaders translate only authorized files into exact Phase 2 inputs. A validation
coordinator applies entry windows and internal outcome embargoes. After the
pre-holdout power audit, an operator-signed permit and external append-only
ledger service control sealed holdout access and reproductions. Statistics and
promotion rules operate only on immutable replay results. An append-only
artifact writer produces manifests, decisions, trades, metrics, checksums, and
a concise report.

**Tech Stack:** Python 3.12, `Decimal`, `Fraction`, pandas, numpy, Ed25519 verification, Phase 2A/2B APIs, JSON/CSV/Markdown artifacts, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Complete Phase 2A and Phase 2B first.
- The existing static 2026 ASX snapshot is engineering evidence only and must always be labeled survivorship-biased and non-promotional.
- Promotion data must be point-in-time, include delistings, and carry split/corporate-action provenance.
- Split chronologically by unique official sessions: first 50%, next 20%, final 30%.
- Require the planned holdout to span at least 36 calendar months. Freeze each
  pattern's `N_required >= 100` and `G_required` from the pre-holdout power
  audit against the operator-declared positive `delta_MME`; do not require
  every holdout month to contain a trade.
- Holdout execution requires a frozen strategy/data/numeric/liquidity/cost/fill
  fingerprint, an operator-signed permit, an operator-owned ledger service,
  and sealed shard access granted only after `DATA_OPENED` is recorded.
- Run and publish the detectable-effect/power audit before holdout unlock; an
  underpowered plan extends the dataset rather than lowering confidence.
- Do not optimize parameters or overwrite any previous artifact directory.
- Pattern edge gates use eligible non-overlapping signal trades in `R_order`;
  the cash-funded arm supplies portfolio safety and `R_fill` remains diagnostic.
- Primary results are regime-neutral; regime appears only in segmented reporting.
- A dataset-wide integrity error makes the run `INVALID` and suppresses promotion scoring.
- A promotion pass authorizes later shadow testing only.

## File Structure

- `src/qat/domain/backtester/swing_dataset.py` — signed catalog, shard schema,
  partition-scoped integrity validation, and loaders.
- `src/qat/domain/backtester/swing_validation.py` — chronological entry windows,
  internal outcome embargoes, attribution, and boundary censoring.
- `src/qat/domain/backtester/swing_holdout.py` — post-power-audit fingerprints,
  signed permits, operator-ledger receipts, sealed-data access,
  exposure/reproduction rules, and full-history lock.
- `src/qat/domain/backtester/swing_statistics.py` — trade/portfolio metrics,
  studentized cluster-multiplier bootstrap, Romano–Wolf adjustment,
  concentration, and sensitivities.
- `src/qat/domain/backtester/swing_promotion.py` — per-pattern and combined promotion verdicts.
- `src/qat/domain/backtester/swing_artifacts.py` — append-only JSON/CSV/checksum writer and Markdown report.
- `scripts/research/run_authoritative_swing.py` — offline command-line runner.
- `docs/phase-2-authoritative-swing-runbook.md` — operator run and interpretation guide.
- `tests/domain/backtester/test_swing_dataset.py` — data integrity tests.
- `tests/domain/backtester/test_swing_validation.py` — partition, embargo, and
  no-cross-boundary tests.
- `tests/domain/backtester/test_swing_holdout.py` — permit, ledger, reuse, and full-history-lock tests.
- `tests/domain/backtester/test_swing_statistics.py` — statistical tests.
- `tests/domain/backtester/test_swing_promotion.py` — gate tests.
- `tests/domain/backtester/test_swing_artifacts.py` — serialization and append-only tests.
- `tests/integration/test_authoritative_swing_engineering_replay.py` — frozen small-universe end-to-end replay.

## Review Focus

- A symbol leaving the index or trading on a different set of sessions must not force common-index trimming or carried-forward bars; Task 1 pins it.
- A corrected file with the same filename must create a different manifest and decision lineage; Tasks 1 and 5 pin it.
- Warm-up history may precede a partition, but entries, outcomes, and metrics
  must not read the next shard; Task 2 pins entry cutoffs, embargoes, and
  censoring.
- A computable fingerprint cannot authorize holdout access, and a changed
  fingerprint cannot reuse exposed bars; Task 4 pins signatures and ledger
  lineage.
- Bootstrap groups all trades from one entry month together, uses common
  manifest-seeded multiplier weights, and applies Romano–Wolf across patterns; Task 3
  pins repeatability, studentization, and clustered signals.
- Static-universe, invalid, or insufficient-holdout runs must be structurally incapable of returning `PASS`; Task 4 pins all three.

---

### Task 1: Frozen dataset schema and integrity validation

**Files:**
- Create: `src/qat/domain/backtester/swing_dataset.py`
- Create: `tests/domain/backtester/test_swing_dataset.py`

**Interfaces:**
- Consumes: a signed public dataset catalog and an authorized shard handle.
- Produces: `DatasetTier`, `DatasetCatalog`, `DatasetShardManifest`,
  `PartitionAccess`, `SwingDataset`, `validate_catalog()`,
  `load_swing_dataset(access)`, and `load_static_asx_engineering_dataset()`.

- [ ] **Step 1: Write failing manifest, membership, and corruption tests**

Use this frozen contract in fixtures. The catalog contains identities,
boundaries, hashes, and signatures but no holdout observations:

```text
dataset-catalog/
  manifest.json

operator-data/
  development/
    membership.csv
    corporate_actions.csv
    benchmark.csv
    regimes.csv
    daily/BHP.AX.csv
  validation/
    ...
  holdout/
    ...
  holdout-outcome-tail/
    ...
```

Daily columns are
`session,raw_open,raw_high,raw_low,raw_close,raw_volume,adjusted_open,adjusted_high,adjusted_low,adjusted_close,adjusted_volume,split_factor_numerator,split_factor_denominator,source,quality,finalized`.
Price, cash, and terminal-price fields are parsed from source text directly
into `Decimal`; split/consolidation ratios and cumulative factors are reduced
positive integer pairs; volume is an integer. Membership columns are
`session,symbol,is_member`. Corporate-action columns are
`event_id,symbol,declaration_date,ex_session,record_date,payment_date,kind,ratio_numerator,ratio_denominator,cash_amount,new_symbol,terminal_price,currency`.
Regime columns are
`session,label,probabilities_json,model_version,input_cutoff,input_hash`.

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
```

Also test duplicate sessions, partial bars, non-finite values, raw OHLC geometry, missing source/quality, unresolved symbol changes, missing delisting outcome, mismatched currency, bad corporate-action ratio, and benchmark gaps. Duplicate/order/hash/schema/corporate-action lineage errors invalidate the dataset. A malformed symbol bar is retained with a non-verified quality state so its symbol-session can abstain and be disclosed.
Test that source text `0.011` remains exactly `Decimal("0.011")`, factors such
as `3/10` remain reduced rationals, reconstructed raw prices agree after the
declared analytical quantum and raw normalization, and no binary float is
present in loaded semantic records. Test that regime rows are point-in-time:
`input_cutoff <= session`, their model/input identities are present, and later
rows cannot alter an earlier regime record.

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

@dataclass(frozen=True, slots=True)
class DatasetShardManifest:
    shard_id: str
    partition: str
    first_session: date
    last_session: date
    files_sha256: Mapping[str, str]
    merkle_root: str

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
    bars: Mapping[str, tuple[FinalBar, ...]]
    membership: Mapping[date, frozenset[str]]
    corporate_actions: tuple[SwingMarketEvent, ...]
    benchmark: tuple[FinalBar, ...]
    regimes: Mapping[date, PointInTimeRegime]
```

The operator packager computes `dataset_id` and sealed shard hashes. The runner
validates the signed catalog without opening any observation shard, then
validates every file in the one authorized shard before constructing
`SwingDataset`. `PartitionAccess` exposes only explicit shard handles; a path
outside that capability is an error. A promotion-tier catalog must
assert point-in-time membership, an accumulation/equivalent total-return
benchmark, exact split factors, raw as-traded data, and at least ten years of
complete history; a shorter longest-complete period requires a nonempty
`coverage_limit_reason` printed in every report. Translate decimal rows to
Phase 2A `FinalBar`, point-in-time regime records, and Phase 2B corporate-action
event types. Structural
corruption invalidates the load; symbol-bar defects become non-verified bars
and recorded issues.

Development and validation processes receive no handle, mount, or decryption
key for holdout shards. Holdout authorization in Task 4 records
`DATA_OPENED` before the data service returns the sealed holdout and tail
handles; only then may this loader verify their bytes against the catalog.

The synthetic engineering dataset is split-only and must generate full golden
lifecycle coverage. The static adapter reads existing
`scripts/research/asx_bars/*.csv`, marks the cache `VENDOR_ADJUSTED`, and injects
survivorship, absent-raw-price, dividend-separation, and unavailable-action
limitations. In `STRICT_AUTHORITATIVE` mode, every rule requiring split-only
price/volume provenance or raw execution data abstains, so zero trades are
valid. `MECHANICAL_DIAGNOSTIC` mode may use the cached series only as a named
analytical proxy in a distinct non-authoritative namespace; it cannot emit a
promotion verdict.

- [ ] **Step 4: Run tests and static checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_research_universe.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_dataset.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_dataset.py tests/domain/backtester/test_swing_dataset.py
git commit -m "feat: validate authoritative swing datasets"
```

### Task 2: Chronological partitions, entry cutoffs, and outcome embargoes

**Files:**
- Create: `src/qat/domain/backtester/swing_validation.py`
- Create: `tests/domain/backtester/test_swing_validation.py`

**Interfaces:**
- Consumes: signed catalog session boundaries and official exchange sessions.
- Produces: `ValidationPartition`, `PartitionWindow`, `ValidationPlan`,
  `build_validation_plan()`, `attribute_partition()`, and
  `classify_boundary_outcome()`.

- [ ] **Step 1: Write failing split, embargo, attribution, and censor tests**

```python
def test_unique_sessions_split_50_20_30_without_overlap() -> None:
    plan = build_validation_plan(one_hundred_sessions())
    assert len(plan.development.sessions) == 50
    assert len(plan.validation.sessions) == 20
    assert len(plan.holdout.sessions) == 30
    assert not (set(plan.development.sessions) & set(plan.holdout.sessions))

def test_validation_entry_window_ends_ten_sessions_before_boundary() -> None:
    window = build_validation_plan(long_history()).validation
    assert len(window.outcome_embargo) == 10
    assert window.last_entry_session < window.outcome_embargo[0]
    assert window.outcome_embargo[-1] == window.last_session
    assert all(s > window.last_entry_session for s in window.outcome_embargo)

def test_warmup_bars_cannot_create_pre_partition_trade() -> None:
    result = run_partition_with_warmup(ValidationPartition.VALIDATION)
    assert min(t.entry_session for t in result.trades) >= result.partition.first_session

def test_validation_never_reads_holdout_to_finish_a_trade() -> None:
    result = run_validation_with_position_unresolved_at_boundary()
    assert result.trades[-1].status is TradeStatus.BOUNDARY_CENSORED
    assert result.holdout_paths_opened == ()

def test_short_holdout_keeps_earlier_partitions_available() -> None:
    plan = build_validation_plan(dataset_with_only_35_holdout_calendar_months())
    assert plan.promotion_eligible is False
    assert plan.development.accessible and plan.validation.accessible
    assert "under_36_calendar_months" in plan.shortfalls

def test_trade_belongs_to_its_entry_partition() -> None:
    trade = completed_validation_trade()
    assert attribute_partition(trade.entry_session, plan) is ValidationPartition.VALIDATION
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 3: Implement entry windows and shard-local outcomes**

Split the signed catalog's unique official sessions 50/20/30 without loading
observation shards. Each partition starts flat and may use only earlier
authorized data for indicator warm-up. The last ten trading sessions of the
development and validation shards are outcome-only embargoes: no new
instruction can be emitted there. This makes the latest ordinary tenth-session
time exit executable by the final session of the same shard. The holdout entry
window may extend through its final session because Task 4 authorizes a sealed
outcome-tail shard with it.

Development and validation may never open the next partition to finish a
position. A suspension, missing terminal outcome, or other exceptional event
still unresolved at the boundary becomes `BOUNDARY_CENSORED`, is excluded from
power and edge statistics, and is counted in the report. Holdout uses its
separately authorized outcome-tail shard in Task 4. Assign every completed
trade by entry session, never exit session.

For a holdout shorter than 36 calendar months, return a plan with
`promotion_eligible=False` and a typed shortfall; do not raise during plan
construction or block development and validation. Holdout permits and ledger
access are deliberately deferred until after Task 3 freezes the power audit.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_validation.py tests/domain/backtester/test_swing_validation.py
git commit -m "feat: partition swing validation without holdout leakage"
```

### Task 3: Deterministic statistics and sensitivity calculations

**Files:**
- Create: `src/qat/domain/backtester/swing_statistics.py`
- Create: `tests/domain/backtester/test_swing_statistics.py`

**Interfaces:**
- Consumes: Phase 2B eligible signal trades and cash-funded equity, benchmark
  returns, point-in-time regime labels, operator-declared `delta_MME`, and
  manifest seed material.
- Produces: `SwingStatistics`, `PowerRequirement`,
  `studentized_month_cluster_multiplier_bootstrap()`,
  `romano_wolf_stepdown()`, `detectable_effect_audit()`,
  `concentration_tests()`, `cost_stress()`, and
  `compute_swing_statistics()`.

- [ ] **Step 1: Write failing hand-calculated metric and deterministic-bootstrap tests**

Pin net `R_order` expectancy, diagnostic `R_fill`, profit factor, maximum
drawdown, exposure, turnover, mean
holding sessions, cost drag, cost-to-risk ratio, order- and fill-denominator
MFE/MAE,
maximum/average single-position notional exposure, days above declared
concentration levels, gap loss beyond planned 1% risk,
rejection/abstention counts, regime groups, year groups, symbol groups, and
benchmark total return. Calculate and label signal-level statistics from
eligible, non-overlapping `signal_trades` separately from cash-funded portfolio
statistics from `trades`. Assert that suppressed same-pattern/same-symbol
overlaps do not increase trade count, signal-level sizing uses the manifest's
fixed reference equity and does not compound, and portfolio results do
compound.

```python
def test_studentized_multiplier_bootstrap_is_repeatable_and_keeps_frame() -> None:
    first = studentized_month_cluster_multiplier_bootstrap(clustered_trades(), samples=10_000, seed_material="manifest-a")
    second = studentized_month_cluster_multiplier_bootstrap(clustered_trades(), samples=10_000, seed_material="manifest-a")
    assert first == second
    assert first.block_count == count_entry_months(clustered_trades())

def test_empty_pattern_month_has_zero_score_not_zero_trade_draw() -> None:
    result = joint_multiplier_bootstrap(sparse_three_pattern_trades())
    assert result.pattern("double_bottom").empty_month_scores
    assert result.pattern("double_bottom").undefined_draws == 0

def test_romano_wolf_uses_common_month_weights_across_patterns() -> None:
    result = romano_wolf_stepdown(three_pattern_clustered_trades(), samples=10_000, seed_material="manifest-a")
    assert result.familywise_error_rate == 0.05
    assert result.common_weight_digest

def test_degenerate_cluster_se_is_insufficient_evidence() -> None:
    assert studentized_month_cluster_multiplier_bootstrap(degenerate_trades(), 10_000, "m").status == "insufficient_evidence"

def test_power_audit_freezes_pattern_specific_trade_and_cluster_requirements() -> None:
    requirement = detectable_effect_audit(
        development_and_validation_trades(), delta_mme=D("0.20")
    )
    assert requirement.delta_mme == D("0.20")
    assert requirement.n_required >= 100
    assert requirement.g_required > 0
    assert requirement.projected_power >= Decimal("0.80")

def test_nonpositive_effect_or_preholdout_expectancy_refuses_unlock() -> None:
    with pytest.raises(InvalidPowerPlan):
        detectable_effect_audit(trades(), delta_mme=D("0"))
    audit = detectable_effect_audit(nonpositive_trades(), delta_mme=D("0.20"))
    assert audit.unlock_eligible is False

def test_36_month_holdout_does_not_require_every_month_to_be_nonempty() -> None:
    assert promotion_sample_check(trades_in_frozen_required_clusters()).passed

def test_concentration_removes_symbol_year_and_top_five_percent() -> None:
    result = concentration_tests(concentrated_trades())
    assert result.without_best_symbol_expectancy <= 0
    assert result.passed is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py -q`

- [ ] **Step 3: Implement net, grouped, studentized, and stressed statistics**

Group eligible signal trades by entry calendar month on `R_order`. Derive the
integer RNG seed from the first 16 hex digits of SHA-256 fingerprint material.
With `N` trades, `G` nonempty month clusters, mean net `R_order` `mean`, and
cluster scores `U_g = sum(R_i - mean)`, calculate:

```
SE = sqrt((G / (G - 1)) * sum(U_g ** 2) / N ** 2)
```

Convert immutable decimal R results to versioned binary64 arrays only at this
statistics boundary and record runtime/library versions. Use the union of
holdout entry months as a fixed common frame; a missing pattern-month has score
zero. For each of 10,000 draws generate one common Rademacher weight per month
and calculate `t_star = (sum_g(w_g * U_g) / N) / SE`. Use
`mean - q0.975(t_star) * SE` as a 97.5% one-sided lower bound, equivalent to the
lower endpoint of a two-sided 95% interval. Because observed `N`, frame, and
`SE` remain fixed, no draw can contain zero observations. Return
`INSUFFICIENT_EVIDENCE` when the observed pattern has zero trades,
zero/undefined SE, too few nonempty clusters, or a collapsed multiplier
distribution.

Use common month weights across the three pattern hypotheses and
implement a one-sided Romano–Wolf stepdown test at family-wise error rate 5%, preserving their
cross-pattern dependence. For each pattern use observed `t = mean / SE` and its
null-centered multiplier `t_star`; order hypotheses by descending observed
`t`, compare each with the multiplier maximum over the
remaining stepdown set, and enforce monotone adjusted p-values. Require both
the pattern's 97.5% one-sided studentized lower bound above zero and its adjusted one-sided
p-value below 0.05. The seven gates within one pattern remain conjunctive and
receive no additional multiplicity correction. The combined portfolio is
secondary, cannot pass when an included constituent pattern fails, and no
sensitivity run can promote.

Before examining strategy outcomes, the operator declares one positive
economically meaningful `delta_MME` in `R_order`. It is not the observed or
data-fitted development/validation mean. Use development-plus-validation cluster
variability and eligible signal frequency to calculate each pattern's
pre-holdout detectable-effect/power audit. Report observed means as
diagnostics. A nonpositive development-plus-validation net expectancy refuses
holdout unlock. Freeze `N_required >= 100`, `G_required`, `delta_MME`, minimum
detectable effect, and projected power of at least 80% before permit issuance.
Do not require all 36 calendar months to be nonempty. Realized shortfalls are
`INSUFFICIENT_EVIDENCE`, and requirements cannot be relaxed after exposure.
Include `1.96 / sqrt(G)` only as the documented scale diagnostic. Remove
`ceil(0.05 * trade_count)` trades for the exceptional-trade concentration test.
Double commission and slippage for stress while retaining third-party charges,
then recompute fills and results through Phase 2B rather than subtracting an
estimate afterward. Compute post-fill resistance-exclusion, liquidity/impact,
`R_fill`, per-trade minimum-of-`R_order`/`R_fill`, and 2% sizing sensitivities
as non-promotional results. Report maximum drawdown
for holdout and validation-plus-holdout. Calculate full-history baseline only
after Task 4 authorizes it for the completed holdout fingerprint; label it a
post-holdout risk diagnostic rather than an unbiased edge estimate.

- [ ] **Step 4: Run focused tests and type check**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_statistics.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_statistics.py tests/domain/backtester/test_swing_statistics.py
git commit -m "feat: calculate swing validation statistics"
```

### Task 4: Holdout authorization and per-pattern promotion verdicts

**Files:**
- Create: `src/qat/domain/backtester/swing_holdout.py`
- Create: `src/qat/domain/backtester/swing_promotion.py`
- Create: `tests/domain/backtester/test_swing_holdout.py`
- Create: `tests/domain/backtester/test_swing_promotion.py`

**Interfaces:**
- Consumes: frozen Task 3 power audit, strategy/data/numeric/liquidity/cost/fill
  configuration, Ed25519 public key, signed permit, operator-ledger client,
  sealed-data service, dataset tier, run status, signal-level baseline
  statistics, Romano–Wolf result, cost stress, and cash-funded drawdown.
- Produces: `HoldoutPermit`, `LedgerReceipt`, `HoldoutLedgerClient`,
  `freeze_fingerprint()`, `verify_holdout_permit()`, `authorize_holdout()`,
  `authorize_full_history()`, `GateResult`, `PromotionVerdict`, and
  `evaluate_promotion()`.

- [ ] **Step 1: Write failing permit, ledger, data-open, and promotion tests**

```python
def test_computable_fingerprint_string_is_not_authorization() -> None:
    with pytest.raises(InvalidPermitError):
        authorize_holdout(plan, permit=f"holdout:{fingerprint}", ledger=ledger_service())

def test_permit_binds_ledger_identity_and_expected_head() -> None:
    with pytest.raises(LedgerIdentityError):
        authorize_holdout(plan, signed_permit(ledger_id="operator-a"), ledger=ledger_service("fresh-empty"))

def test_data_opened_is_committed_before_handle_is_returned() -> None:
    access = authorize_holdout(plan, signed_permit(), ledger=ledger_service())
    handle = access.open_sealed_data()
    assert access.ledger.latest_state == "DATA_OPENED"
    assert handle.partition is ValidationPartition.HOLDOUT

def test_patch_after_pre_exposure_failure_may_receive_replacement_permit() -> None:
    receipt = failed_pre_exposure_reservation()
    assert replacement_permit(new_runner_build(), receipt).allowed

def test_patch_after_data_opened_cannot_make_fresh_claim() -> None:
    receipt = failed_after_exposure()
    with pytest.raises(HoldoutAlreadyExposedError):
        authorize_holdout(plan, signed_permit(new_runner_build()), receipt.ledger)

def test_exact_rerun_is_reproduction_and_full_history_waits_for_completion() -> None:
    assert authorize_holdout(exposed_plan(), original_signed_permit(), exposed_ledger()).mode is HoldoutRunMode.REPRODUCTION
    with pytest.raises(HoldoutLockedError):
        authorize_full_history(plan, signed_permit(), ledger_without_completed_holdout())

@pytest.mark.parametrize("failure", [
    "nonpositive_expectancy", "studentized_lower_bound",
    "romano_wolf_adjusted_p", "profit_factor", "cost_stress", "concentration",
])
def test_each_failed_edge_gate_returns_fail(failure: str) -> None:
    verdict = evaluate_promotion(case_with_only_failure(failure))
    assert verdict.status is PromotionStatus.FAIL
    assert verdict.gates[failure].passed is False

@pytest.mark.parametrize("shortfall", [
    "under_n_required", "under_g_required", "under_36_calendar_months",
    "underpowered", "degenerate_standard_error",
])
def test_evidence_shortfall_is_not_strategy_failure(shortfall: str) -> None:
    assert evaluate_promotion(case_with_only_failure(shortfall)).status is PromotionStatus.INSUFFICIENT_EVIDENCE

@pytest.mark.parametrize("reason", [
    "engineering_tier", "invalid_run", "not_holdout", "invalid_permit",
    "reused_holdout_period", "provisional_liquidity_profile",
])
def test_ineligible_inputs_cannot_be_scored(reason: str) -> None:
    assert evaluate_promotion(case_with_only_failure(reason)).status is PromotionStatus.INELIGIBLE

def test_patterns_are_scored_separately() -> None:
    verdicts = evaluate_all_patterns(mixed_pattern_results())
    assert verdicts[Pattern.EMA_PULLBACK].status is PromotionStatus.PASS
    assert verdicts[Pattern.BULL_FLAG].status is PromotionStatus.FAIL

def test_edge_pass_with_unsafe_drawdown_is_portfolio_risk_blocked() -> None:
    verdict = evaluate_promotion(edge_pass_case(holdout_drawdown=D("0.21")))
    assert verdict.status is PromotionStatus.EDGE_PASS_PORTFOLIO_RISK_BLOCKED

def test_combined_cannot_pass_with_failed_constituent() -> None:
    verdicts = evaluate_all_patterns(one_failed_constituent())
    assert verdicts[ReplayArm.COMBINED].status is not PromotionStatus.PASS
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_holdout.py tests/domain/backtester/test_swing_promotion.py -q`

- [ ] **Step 3: Implement signed access, immutable receipts, and named gates**

Create the fingerprint only after Task 3 freezes `delta_MME`, `N_required`,
`G_required`, minimum detectable effect, and projected power. Hash strategy and
evidence versions, strategy-spec hash, runner-build hash/code commit, signed
dataset catalog and sealed shard identities/boundaries, numeric policy,
liquidity/cost/fill profiles, ambiguity policy, and the power requirements.

Verify an Ed25519 permit binding the fingerprint, ledger identity, expected
sequence/head hash, exact holdout and tail shards, operator public-key identity,
nonce, and approval timestamp. The private key is unavailable to the runner.
Promotion mode accepts a configured `HoldoutLedgerClient`, never an arbitrary
writable path. The service atomically compare-and-appends records and returns
signed receipts; reject a fresh ledger, rollback, stale head, invalid service
signature, nonce reuse, or scope mismatch.

Append `EXPOSURE_RESERVED`, then require the sealed-data service to append
`DATA_OPENED` before returning any holdout byte or handle. Finish with
`COMPLETED`, `FAILED_PRE_EXPOSURE`, or `FAILED_AFTER_EXPOSURE`. A patched build
may receive a replacement permit only after `FAILED_PRE_EXPOSURE`. After
`DATA_OPENED`, an exact fingerprint may reproduce; any changed build is a
non-promotional repair diagnostic and needs fresh data for promotion.
Full-history access requires a completed authorized holdout with the identical
fingerprint.

For each pattern, require a valid signed permit and unused-period ledger record,
the locked partition and pre-holdout power protocol, at least 36 holdout
calendar months, at least frozen `G_required` nonempty entry-month clusters,
at least frozen `N_required >= 100` completed trades, a final liquidity profile,
positive signal-level `R_order` expectancy, and a statistical confidence gate
requiring both a 97.5% one-sided studentized cluster-multiplier lower bound above zero and a
one-sided Romano–Wolf adjusted p-value below 0.05. Also require profit factor at
least 1.20, positive
doubled-cost expectancy, and all three leave-out expectancies above zero. These
seven logical gates are conjunctive; do not adjust them against each other.

Only eligible non-overlapping signal-level trades supply `N_required`,
`G_required`, expectancy, confidence, profit factor, cost stress, and
concentration. `R_fill` and the per-trade minimum-R metric are diagnostics. The
cash-funded arm supplies drawdown, allocation, exposure, and portfolio safety.

Evaluate portfolio safety separately. Require maximum drawdown no greater than
20% on both the holdout and full-history baseline for `PASS`. Return
`EDGE_PASS_PORTFOLIO_RISK_BLOCKED` when all edge gates pass but either drawdown
fails; this status cannot authorize shadow testing until Phase 4 adds
concentration controls and the replay passes. Return `FAIL` for an edge-gate
failure, `INSUFFICIENT_EVIDENCE` for sample, cluster, degeneracy, or power
shortfall, and `INELIGIBLE` for engineering-tier/non-holdout input.
Missing authorized full-history diagnostics also prevent a final `PASS`.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_holdout.py tests/domain/backtester/test_swing_promotion.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_holdout.py src/qat/domain/backtester/swing_promotion.py tests/domain/backtester/test_swing_holdout.py tests/domain/backtester/test_swing_promotion.py
git commit -m "feat: authorize and evaluate swing holdout evidence"
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
  holdout_permit.json      # holdout/full-history runs only; public signed payload
  ledger_receipt.json      # holdout/full-history runs only
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
```

Also verify every checksum, stable JSON ordering, no NaN/Infinity
serialization, evidence IDs in trade rows, separate pattern/combined sections,
ambiguity sensitivity, regime segmentation, and holdout authorization metadata.
The manifest records fixed signal-level reference equity; eligible and
overlap-suppressed trade counts; `R_order` and `R_fill`; catalog/shard
identities; entry windows, embargoes, and boundary-censored counts; frozen
`delta_MME`, `N_required`, `G_required`, and entry-month cluster counts;
holdout-tail completion; decimal/rational numeric policy; liquidity profile;
signed-permit digest; ledger identity, sequence, head, signed receipt and final
state; exposure or reproduction mode; power audit; multiplier-bootstrap
seed/weight digest; point-in-time regime provenance; and multiplicity method.
Decimal semantic values serialize
canonically as strings. The report distinguishes edge gates from portfolio
safety and renders
`EDGE_PASS_PORTFOLIO_RISK_BLOCKED` explicitly.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_artifacts.py -q`

- [ ] **Step 3: Implement atomic append-only writing**

Write into a sibling temporary directory, calculate all hashes, write `SHA256SUMS`, then atomically rename to the deterministic run ID. Refuse an existing destination. Keep `created_at` in packaging metadata but exclude it from semantic IDs and comparison hashes.

- [ ] **Step 4: Run focused tests and verify a fixture report manually**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_artifacts.py -q`

Open the generated fixture `report.md` and confirm the evidence tier, period,
costs, fill model, limitations, per-pattern results, combined portfolio,
sensitivities, and promotion status are visible without reading JSON. Confirm
it reports holdout, validation-plus-holdout, and full-history drawdown; primary
`R_order`, diagnostic `R_fill`, and minimum-R stress; eligible, suppressed, and
boundary-censored counts; maximum
and average single-position notional exposure; cost-to-risk ratios; days above
declared concentration levels; gap losses beyond the planned 1% risk; and the
uncapped portfolio's status as a concentration/gap-risk stress case rather than
a deployable forecast. It also reports liquidity participation/capacity,
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
- Consumes: `--catalog`, an authorized engineering/development/validation shard
  handle, `--engineering-mode`, `--out`, `--partition`, `--ambiguity-policy`,
  `--volume-multiplier`, and for holdout/full-history only `--permit`,
  `--public-key`, `--ledger-profile`, and `--sealed-data-profile`.
- Produces: one artifact directory and process exit code 0 for a valid replay, 2 for invalid data/configuration, or 3 for a locked holdout.

- [ ] **Step 1: Write failing CLI and frozen end-to-end tests**

```python
def test_static_asx_run_cannot_claim_promotion(tmp_path: Path) -> None:
    completed = run_cli("--catalog", "static-asx", "--out", str(tmp_path), "--partition", "development")
    assert completed.returncode == 0
    promotion = read_only_run(tmp_path, "promotion.json")
    assert promotion["status"] == "ineligible"

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
physical shards, 50/20/30 partitions, ten-session embargoes and censoring,
entry-session ownership, declared `delta_MME`, pre-holdout power audit, signing
the permit outside the runner, configured operator ledger/sealed-data profiles,
state receipts, crash/reproduction rules, full-history lock,
exit codes, artifact meanings, promotion statuses, engineering modes, and why a
static-universe result cannot promote the strategy.

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
bisection sizing, and multiplier-bootstrap outputs to small test-only reference
implementations that import no production helpers or decimal context. Prove a
development or validation run cannot open a holdout path or capability, a
fresh/rolled-back ledger cannot verify, and `DATA_OPENED` precedes every sealed
handle return.

- [ ] **Step 2: Run focused safety and Phase 2 tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_swing_portfolio.py tests/domain/backtester/test_swing_replay.py tests/domain/backtester/test_swing_corporate_actions.py tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_swing_validation.py tests/domain/backtester/test_swing_holdout.py tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_promotion.py tests/domain/backtester/test_swing_artifacts.py tests/domain/backtester/test_swing_reference_parity.py tests/domain/backtester/test_swing_prefix_invariance.py tests/integration/test_authoritative_swing_engineering_replay.py tests/safety/test_phase2_strategy_isolation.py -q`

Expected: PASS.

- [ ] **Step 3: Run repository-wide quality gates**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts/research/run_authoritative_swing.py`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing src/qat/domain/backtester/swing_events.py src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_results.py src/qat/domain/backtester/swing_portfolio.py src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_dataset.py src/qat/domain/backtester/swing_validation.py src/qat/domain/backtester/swing_holdout.py src/qat/domain/backtester/swing_statistics.py src/qat/domain/backtester/swing_promotion.py src/qat/domain/backtester/swing_artifacts.py`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS. Record command, result, duration, and environment in the checkpoint.

- [ ] **Step 4: Write the Phase 2 checkpoint**

Document implemented spec sections, commits, decimal/reference/prefix/isolation
test evidence, both engineering replay artifact IDs, strict static abstentions,
survivorship limitation, permit/ledger status, absence or status of
promotion-grade data, unchanged production behavior, and the deferred Option 3
parity replay. Do not state that the strategy has an edge unless a signed,
unused-period promotion holdout has actually passed.

- [ ] **Step 5: Commit**

```powershell
git add docs/phase-2-authoritative-swing-checkpoint.md
git commit -m "docs: record Phase 2 swing verification"
```
