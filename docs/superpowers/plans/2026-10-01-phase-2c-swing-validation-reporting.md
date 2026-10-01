# Phase 2C Swing Validation and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate datasets, enforce the approved chronological protocol, calculate promotion evidence, and emit reproducible machine and human artifacts for the Phase 2 engine and replay.

**Architecture:** A versioned dataset adapter translates frozen historical files into Phase 2 domain inputs and corporate-action events. A validation coordinator controls development/validation/holdout access. Statistics and promotion rules operate only on immutable replay results. An append-only artifact writer produces manifests, decisions, trades, metrics, checksums, and a concise report.

**Tech Stack:** Python 3.12, pandas, numpy, Phase 2A/2B APIs, JSON/CSV/Markdown artifacts, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- Complete Phase 2A and Phase 2B first.
- The existing static 2026 ASX snapshot is engineering evidence only and must always be labeled survivorship-biased and non-promotional.
- Promotion data must be point-in-time, include delistings, and carry split/corporate-action provenance.
- Split chronologically by unique official sessions: first 50%, next 20%, final 30%.
- Require the holdout to span at least 36 calendar months and each pattern
  seeking promotion to have at least 36 distinct nonempty holdout entry-month
  clusters with completed outcomes.
- Holdout execution requires a frozen strategy/data/cost/fill fingerprint and an explicit matching approval value.
- Run and publish the detectable-effect/power audit before holdout unlock; an
  underpowered plan extends the dataset rather than lowering confidence.
- Do not optimize parameters or overwrite any previous artifact directory.
- Primary results are regime-neutral; regime appears only in segmented reporting.
- A dataset-wide integrity error makes the run `INVALID` and suppresses promotion scoring.
- A promotion pass authorizes later shadow testing only.

## File Structure

- `src/qat/domain/backtester/swing_dataset.py` — dataset schema, manifest hashing, integrity validation, and loaders.
- `src/qat/domain/backtester/swing_validation.py` — chronological partitions, freeze fingerprint, and holdout lock.
- `src/qat/domain/backtester/swing_statistics.py` — trade/portfolio metrics, studentized cluster bootstrap, Romano–Wolf adjustment, concentration, and sensitivities.
- `src/qat/domain/backtester/swing_promotion.py` — per-pattern and combined promotion verdicts.
- `src/qat/domain/backtester/swing_artifacts.py` — append-only JSON/CSV/checksum writer and Markdown report.
- `scripts/research/run_authoritative_swing.py` — offline command-line runner.
- `docs/phase-2-authoritative-swing-runbook.md` — operator run and interpretation guide.
- `tests/domain/backtester/test_swing_dataset.py` — data integrity tests.
- `tests/domain/backtester/test_swing_validation.py` — partition and holdout tests.
- `tests/domain/backtester/test_swing_statistics.py` — statistical tests.
- `tests/domain/backtester/test_swing_promotion.py` — gate tests.
- `tests/domain/backtester/test_swing_artifacts.py` — serialization and append-only tests.
- `tests/integration/test_authoritative_swing_engineering_replay.py` — frozen small-universe end-to-end replay.

## Review Focus

- A symbol leaving the index or trading on a different set of sessions must not force common-index trimming or carried-forward bars; Task 1 pins it.
- A corrected file with the same filename must create a different manifest and decision lineage; Tasks 1 and 5 pin it.
- Warm-up history may precede a partition, but entries and metrics must not leak across its boundary; Task 2 pins it.
- Bootstrap groups all trades from one entry month together, uses common
  manifest-seeded resamples, and applies Romano–Wolf across patterns; Task 3
  pins repeatability, studentization, and clustered signals.
- Static-universe, invalid, or insufficient-holdout runs must be structurally incapable of returning `PASS`; Task 4 pins all three.

---

### Task 1: Frozen dataset schema and integrity validation

**Files:**
- Create: `src/qat/domain/backtester/swing_dataset.py`
- Create: `tests/domain/backtester/test_swing_dataset.py`

**Interfaces:**
- Consumes: an offline dataset directory.
- Produces: `DatasetTier`, `SwingDatasetManifest`, `SwingDataset`, `validate_dataset()`, `load_swing_dataset()`, and `load_static_asx_engineering_dataset()`.

- [ ] **Step 1: Write failing manifest, membership, and corruption tests**

Use this frozen directory contract in fixtures:

```text
dataset/
  manifest.json
  membership.csv
  corporate_actions.csv
  benchmark.csv
  daily/BHP.AX.csv
  daily/CBA.AX.csv
```

Daily columns are `session,raw_open,raw_high,raw_low,raw_close,raw_volume,adjusted_open,adjusted_high,adjusted_low,adjusted_close,adjusted_volume,source,quality,finalized`. Membership columns are `session,symbol,is_member`. Corporate-action columns are `event_id,symbol,effective_session,kind,ratio,cash_amount,new_symbol,terminal_price,currency`.

```python
def test_membership_is_point_in_time_without_index_intersection() -> None:
    dataset = load_swing_dataset(fixture_with_entry_exit_and_delisting())
    assert dataset.members("2020-01-02") == {"OLD.AX"}
    assert dataset.members("2026-01-02") == {"NEW.AX"}
    assert dataset.bars["OLD.AX"][-1].session < dataset.bars["NEW.AX"][-1].session

def test_changed_source_bytes_change_dataset_id() -> None:
    before = load_swing_dataset(dataset_dir()).manifest.dataset_id
    change_one_close_without_updating_manifest(dataset_dir())
    with pytest.raises(DatasetIntegrityError, match="hash"):
        load_swing_dataset(dataset_dir())
    assert before
```

Also test duplicate sessions, partial bars, non-finite values, raw OHLC geometry, missing source/quality, unresolved symbol changes, missing delisting outcome, mismatched currency, bad corporate-action ratio, and benchmark gaps. Duplicate/order/hash/schema/corporate-action lineage errors invalidate the dataset. A malformed symbol bar is retained with a non-verified quality state so its symbol-session can abstain and be disclosed.

- [ ] **Step 2: Run and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_dataset.py -q`

- [ ] **Step 3: Implement manifest-first loading and typed events**

```python
class DatasetTier(StrEnum):
    ENGINEERING_STATIC = "engineering_static"
    PROMOTION_POINT_IN_TIME = "promotion_point_in_time"

@dataclass(frozen=True, slots=True)
class SwingDatasetManifest:
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
    files_sha256: Mapping[str, str]
    limitations: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SwingDataset:
    manifest: SwingDatasetManifest
    bars: Mapping[str, tuple[FinalBar, ...]]
    membership: Mapping[date, frozenset[str]]
    corporate_actions: tuple[SwingMarketEvent, ...]
    benchmark: tuple[FinalBar, ...]
```

Compute `dataset_id` from canonical manifest content and file hashes. Validate every file before constructing `SwingDataset`. A promotion-tier manifest must assert point-in-time membership, an accumulation/equivalent total-return benchmark, and at least ten years of complete history; a shorter longest-complete period requires a nonempty `coverage_limit_reason` that is printed in every report. Translate rows to Phase 2A `FinalBar` and Phase 2B corporate-action event types. Structural corruption invalidates the load; symbol-bar defects become non-verified bars and recorded issues. The static adapter reads existing `scripts/research/asx_bars/*.csv`, sets raw and analytical values from the cached adjusted series, marks the adjustment `VENDOR_ADJUSTED` because the cache cannot separate split and dividend transformations, and injects the required survivorship, absent raw-price, dividend-separation, and unavailable-corporate-action limitations. Authoritative rules that require split-only provenance abstain on this input rather than silently accepting it.

- [ ] **Step 4: Run tests and static checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_research_universe.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_dataset.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_dataset.py tests/domain/backtester/test_swing_dataset.py
git commit -m "feat: validate authoritative swing datasets"
```

### Task 2: Chronological partitions and locked holdout

**Files:**
- Create: `src/qat/domain/backtester/swing_validation.py`
- Create: `tests/domain/backtester/test_swing_validation.py`

**Interfaces:**
- Consumes: dataset sessions, strategy configuration, cost profile, and fill policy.
- Produces: `ValidationPartition`, `ValidationPlan`, `freeze_fingerprint()`, and `authorize_partition()`.

- [ ] **Step 1: Write failing boundary, warm-up, and lock tests**

```python
def test_unique_sessions_split_50_20_30_without_overlap() -> None:
    plan = build_validation_plan(one_hundred_sessions())
    assert len(plan.development.sessions) == 50
    assert len(plan.validation.sessions) == 20
    assert len(plan.holdout.sessions) == 30
    assert not (set(plan.development.sessions) & set(plan.holdout.sessions))

def test_holdout_refuses_without_exact_frozen_fingerprint() -> None:
    with pytest.raises(HoldoutLockedError):
        authorize_partition(plan, ValidationPartition.HOLDOUT, supplied_approval=None)

def test_warmup_bars_cannot_create_pre_partition_trade() -> None:
    result = run_partition_with_warmup(ValidationPartition.VALIDATION)
    assert min(t.entry_session for t in result.trades) >= result.partition.first_session

def test_holdout_requires_36_calendar_months() -> None:
    with pytest.raises(InsufficientHoldoutError):
        build_validation_plan(dataset_with_only_35_holdout_calendar_months())

def test_trade_belongs_to_entry_partition_and_may_exit_in_buffer() -> None:
    trade = run_entry_on_last_holdout_session_and_exit_later()
    assert trade.partition is ValidationPartition.HOLDOUT
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 3: Implement session-based splits, outcome buffers, power audit, and fingerprint lock**

The fingerprint is SHA-256 over strategy version/config, evidence schema,
dataset ID, cost model, ambiguity policy, and replay code commit. Development
and validation are always accessible. Holdout requires a supplied approval
string exactly equal to `holdout:<fingerprint>` and records that value in the
run manifest.

Assign trades by entry session, never exit session. Start every partition flat;
allow prior bars only as warm-up, block entries outside the partition, and
continue an outcome buffer after its final session until its open positions
close. The normal buffer is ten additional tradable sessions, but suspensions
and delistings may extend it. Attribute every later fill and the full result to
the entry partition. Count holdout trades only when their holdout entries have
completed outcomes.

Reject a holdout plan with fewer than 36 calendar months. After replay, record
the distinct nonempty entry-month cluster count for each pattern; Phase 2C
promotion requires at least 36 for any pattern seeking promotion. Before
authorization, calculate and record a detectable-effect/power audit from
development-plus-validation month-cluster
variability and freeze the expected mean-R effect in the fingerprint. Estimate
prospective power with the same studentized cluster process, require at least
80% power at 5% family-wise error, and publish the minimum detectable mean R.
Include the approximation `1.96 / sqrt(G)` as a scale diagnostic (0.400, 0.327,
and 0.283 block standard deviations for 24, 36, and 48 clusters), while making
the bootstrap simulation authoritative. An underpowered result requires more
history; it cannot change the confidence level or statistical gate.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_validation.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_validation.py tests/domain/backtester/test_swing_validation.py
git commit -m "feat: lock chronological swing validation"
```

### Task 3: Deterministic statistics and sensitivity calculations

**Files:**
- Create: `src/qat/domain/backtester/swing_statistics.py`
- Create: `tests/domain/backtester/test_swing_statistics.py`

**Interfaces:**
- Consumes: Phase 2B trades/equity, benchmark returns, regime labels, and manifest fingerprint.
- Produces: `SwingStatistics`, `studentized_month_cluster_bootstrap()`, `romano_wolf_stepdown()`, `detectable_effect_audit()`, `concentration_tests()`, `cost_stress()`, and `compute_swing_statistics()`.

- [ ] **Step 1: Write failing hand-calculated metric and deterministic-bootstrap tests**

Pin net R expectancy, profit factor, maximum drawdown, exposure, turnover, mean
holding sessions, cost drag, cost-to-risk ratio, MFE/MAE,
maximum/average single-position notional exposure, days above declared
concentration levels, gap loss beyond planned 1% risk,
rejection/abstention counts, regime groups, year groups, symbol groups, and
benchmark total return. Calculate and label signal-level statistics from
`signal_trades` separately from cash-funded portfolio statistics from `trades`.
Assert that signal-level sizing uses the manifest's fixed reference equity for
every trade and does not compound, while portfolio results do compound.

```python
def test_studentized_month_bootstrap_is_repeatable_and_keeps_clusters() -> None:
    first = studentized_month_cluster_bootstrap(clustered_trades(), samples=10_000, seed_material="manifest-a")
    second = studentized_month_cluster_bootstrap(clustered_trades(), samples=10_000, seed_material="manifest-a")
    assert first == second
    assert first.block_count == count_entry_months(clustered_trades())

def test_romano_wolf_uses_common_resamples_across_patterns() -> None:
    result = romano_wolf_stepdown(three_pattern_clustered_trades(), samples=10_000, seed_material="manifest-a")
    assert result.familywise_error_rate == 0.05
    assert result.common_resample_digest

def test_degenerate_cluster_se_is_insufficient_evidence() -> None:
    assert studentized_month_cluster_bootstrap(degenerate_trades(), 10_000, "m").status == "insufficient_evidence"

def test_concentration_removes_symbol_year_and_top_five_percent() -> None:
    result = concentration_tests(concentrated_trades())
    assert result.without_best_symbol_expectancy <= 0
    assert result.passed is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py -q`

- [ ] **Step 3: Implement net, grouped, studentized, and stressed statistics**

Group trades by entry calendar month and resample complete month blocks with
replacement 10,000 times. Derive the integer RNG seed from the first 16 hex
digits of SHA-256 fingerprint material. With `N` trades, `G` month clusters,
mean net R `mean`, and cluster scores `U_g = sum(R_i - mean)`, calculate:

```
SE = sqrt((G / (G - 1)) * sum(U_g ** 2) / N ** 2)
```

For each resample compute `mean*`, `SE*`, and
`t* = (mean* - mean) / SE*`. Use
`mean - q0.975(t*) * SE` as the one-sided lower bound. Return
`INSUFFICIENT_EVIDENCE` for zero/undefined SE, too few clusters, or a
degenerate resample distribution.

Use common month-cluster resamples across the three pattern hypotheses and
implement Romano–Wolf stepdown at family-wise error rate 5%, preserving their
cross-pattern dependence. Use the union of holdout entry months as the common
cluster frame, including empty pattern-month clusters. For each pattern use
observed `t = mean / SE` and its null-centered bootstrap `t*`; order hypotheses
by descending observed `t`, compare each with the resampled maximum over the
remaining stepdown set, and enforce monotone adjusted p-values. Require both
the pattern's 95% studentized lower bound above zero and its adjusted one-sided
p-value below 0.05. The seven gates within one pattern remain conjunctive and
receive no additional multiplicity correction. The combined portfolio is
secondary, cannot pass when an included constituent pattern fails, and no
sensitivity run can promote.

Use development-plus-validation cluster variability to calculate the
pre-holdout detectable-effect/power audit. Remove
`ceil(0.05 * trade_count)` trades for the exceptional-trade concentration test.
Double commission and slippage for stress while retaining third-party charges,
then recompute fills and results through Phase 2B rather than subtracting an
estimate afterward. Report maximum drawdown for holdout,
validation-plus-holdout, and full-history baseline; label the last as a risk
diagnostic rather than an unbiased edge estimate.

- [ ] **Step 4: Run focused tests and type check**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_statistics.py -q`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/backtester/swing_statistics.py`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_statistics.py tests/domain/backtester/test_swing_statistics.py
git commit -m "feat: calculate swing validation statistics"
```

### Task 4: Per-pattern promotion verdicts

**Files:**
- Create: `src/qat/domain/backtester/swing_promotion.py`
- Create: `tests/domain/backtester/test_swing_promotion.py`

**Interfaces:**
- Consumes: dataset tier, run status, partition protocol, power audit, baseline
  statistics, Romano–Wolf result, doubled-cost statistics, and portfolio
  drawdown diagnostics.
- Produces: `GateResult`, `PromotionVerdict`, and `evaluate_promotion()`.

- [ ] **Step 1: Write one failing test per gate and an all-pass case**

```python
@pytest.mark.parametrize("failure", [
    "nonpositive_expectancy", "studentized_lower_bound",
    "romano_wolf_adjusted_p", "profit_factor", "cost_stress", "concentration",
])
def test_each_failed_edge_gate_returns_fail(failure: str) -> None:
    verdict = evaluate_promotion(case_with_only_failure(failure))
    assert verdict.status is PromotionStatus.FAIL
    assert verdict.gates[failure].passed is False

@pytest.mark.parametrize("shortfall", [
    "under_100_trades", "under_36_months", "under_36_clusters",
    "underpowered", "degenerate_standard_error",
])
def test_evidence_shortfall_is_not_strategy_failure(shortfall: str) -> None:
    assert evaluate_promotion(case_with_only_failure(shortfall)).status is PromotionStatus.INSUFFICIENT_EVIDENCE

@pytest.mark.parametrize("reason", ["engineering_tier", "invalid_run", "not_holdout"])
def test_ineligible_inputs_cannot_be_scored(reason: str) -> None:
    assert evaluate_promotion(case_with_only_failure(reason)).status is PromotionStatus.INELIGIBLE

def test_patterns_are_scored_separately() -> None:
    verdicts = evaluate_all_patterns(mixed_pattern_results())
    assert verdicts[Pattern.EMA_PULLBACK].status is PromotionStatus.PASS
    assert verdicts[Pattern.BULL_FLAG].status is PromotionStatus.FAIL

def test_edge_pass_with_unsafe_drawdown_is_portfolio_risk_blocked() -> None:
    verdict = evaluate_promotion(edge_pass_case(holdout_drawdown=.21))
    assert verdict.status is PromotionStatus.EDGE_PASS_PORTFOLIO_RISK_BLOCKED

def test_combined_cannot_pass_with_failed_constituent() -> None:
    verdicts = evaluate_all_patterns(one_failed_constituent())
    assert verdicts[Pattern.COMBINED].status is not PromotionStatus.PASS
```

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_promotion.py -q`

- [ ] **Step 3: Implement named gates with measured and required values**

For each pattern, require the locked partition and pre-holdout power protocol,
at least 36 holdout calendar months, at least 36 nonempty entry-month clusters,
at least 100 completed holdout trades, net expectancy above zero, a statistical
confidence gate requiring both a 95% studentized cluster-bootstrap lower bound
above zero and a Romano–Wolf adjusted one-sided p-value below 0.05, profit
factor at least 1.20, positive
doubled-cost expectancy, and all three leave-out expectancies above zero. These
seven logical gates are conjunctive; do not adjust them against each other.

Evaluate portfolio safety separately. Require maximum drawdown no greater than
20% on both the holdout and full-history baseline for `PASS`. Return
`EDGE_PASS_PORTFOLIO_RISK_BLOCKED` when all edge gates pass but either drawdown
fails; this status cannot authorize shadow testing until Phase 4 adds
concentration controls and the replay passes. Return `FAIL` for an edge-gate
failure, `INSUFFICIENT_EVIDENCE` for sample, cluster, degeneracy, or power
shortfall, and `INELIGIBLE` for engineering-tier/non-holdout input.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_swing_promotion.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/swing_promotion.py tests/domain/backtester/test_swing_promotion.py
git commit -m "feat: enforce swing promotion evidence gates"
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
The manifest records fixed signal-level reference equity, partition dates,
entry-month cluster counts, outcome-buffer completion, power audit, bootstrap
seed/resample digest, and multiplicity method. The report distinguishes edge
gates from portfolio safety and renders
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
it reports holdout, validation-plus-holdout, and full-history drawdown; maximum
and average single-position notional exposure; cost-to-risk ratios; days above
declared concentration levels; gap losses beyond the planned 1% risk; and the
uncapped portfolio's status as a concentration/gap-risk stress case rather than
a deployable forecast.

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
- Consumes: `--dataset`, `--out`, `--partition`, `--ambiguity-policy`, `--volume-multiplier`, and optional `--holdout-approval`.
- Produces: one artifact directory and process exit code 0 for a valid replay, 2 for invalid data/configuration, or 3 for a locked holdout.

- [ ] **Step 1: Write failing CLI and frozen end-to-end tests**

```python
def test_static_asx_run_cannot_claim_promotion(tmp_path: Path) -> None:
    completed = run_cli("--dataset", "static-asx", "--out", str(tmp_path), "--partition", "development")
    assert completed.returncode == 0
    promotion = read_only_run(tmp_path, "promotion.json")
    assert promotion["status"] == "ineligible"

def test_cli_never_fetches_network_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("requests.Session.request", forbidden_network_call)
    assert run_small_fixture(tmp_path).returncode == 0
```

The integration fixture must contain one trade per pattern, one rejected setup, one abstention, one ambiguous fill, and one confluence candidate.

- [ ] **Step 2: Run and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_authoritative_swing_engineering_replay.py -q`

- [ ] **Step 3: Implement the offline coordinator and runbook**

The CLI loads only frozen local inputs, constructs the ASX cost profile,
validates partition access, and runs four arms: each pattern independently and
the combined portfolio. It runs the baseline plus approved sensitivities
(volume 1.25/1.5/2.0, optimistic ambiguity, doubled costs, and 2% sizing
disclosed separately), writes artifacts, prints their absolute path, and never
changes deployed settings. Only frozen baseline pattern arms enter the
Romano–Wolf family; sensitivities remain diagnostic.

The runbook documents the exact commands, evidence tiers, 50/20/30 partitions,
entry-session ownership and outcome buffers, pre-holdout power audit, holdout
fingerprint flow, exit codes, artifact meanings, promotion statuses, and why a
static-universe result cannot promote the strategy.

- [ ] **Step 4: Run the frozen integration test and actual engineering replay**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_authoritative_swing_engineering_replay.py -q`

Run: `.\.venv\Scripts\python.exe scripts/research/run_authoritative_swing.py --dataset static-asx --partition development --out data/phase2-engineering`

Expected: exit 0, an absolute artifact path, explicit survivorship and vendor-adjustment warnings, no promotion pass, and no broker/network access. If the current cache lacks three years of valid split-only history, the report must show the resulting resistance/data-provenance abstentions rather than manufacture trades.

- [ ] **Step 5: Commit code and documentation, excluding runtime artifacts**

```powershell
git add scripts/research/run_authoritative_swing.py tests/integration/test_authoritative_swing_engineering_replay.py docs/phase-2-authoritative-swing-runbook.md
git commit -m "feat: run Phase 2 swing engineering evidence"
```

### Task 7: Final determinism, safety, and repository verification

**Files:**
- Modify only files implicated by failures found in this task.
- Create: `docs/phase-2-authoritative-swing-checkpoint.md`

**Interfaces:**
- Consumes: the complete Phase 2A/2B/2C implementation.
- Produces: reproducible verification evidence and a checkpoint report.

- [ ] **Step 1: Run the same frozen integration replay twice**

Run the integration fixture into two empty temporary output roots. Compare `decisions.jsonl`, `fills.csv`, `trades.csv`, `equity.csv`, `metrics.json`, and `promotion.json` byte-for-byte. Compare semantic manifest fields while excluding `created_at` and artifact path.

- [ ] **Step 2: Run focused safety and Phase 2 tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/strategies/authoritative_swing tests/domain/backtester/test_swing_fills.py tests/domain/backtester/test_swing_portfolio.py tests/domain/backtester/test_swing_replay.py tests/domain/backtester/test_swing_corporate_actions.py tests/domain/backtester/test_swing_dataset.py tests/domain/backtester/test_swing_validation.py tests/domain/backtester/test_swing_statistics.py tests/domain/backtester/test_swing_promotion.py tests/domain/backtester/test_swing_artifacts.py tests/integration/test_authoritative_swing_engineering_replay.py tests/safety/test_phase2_strategy_isolation.py -q`

Expected: PASS.

- [ ] **Step 3: Run repository-wide quality gates**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts/research/run_authoritative_swing.py`

Run: `.\.venv\Scripts\python.exe -m mypy src/qat/domain/strategies/authoritative_swing src/qat/domain/backtester/swing_events.py src/qat/domain/backtester/swing_fills.py src/qat/domain/backtester/swing_results.py src/qat/domain/backtester/swing_portfolio.py src/qat/domain/backtester/swing_replay.py src/qat/domain/backtester/swing_dataset.py src/qat/domain/backtester/swing_validation.py src/qat/domain/backtester/swing_statistics.py src/qat/domain/backtester/swing_promotion.py src/qat/domain/backtester/swing_artifacts.py`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS. Record command, result, duration, and environment in the checkpoint.

- [ ] **Step 4: Write the Phase 2 checkpoint**

Document implemented spec sections, commits, test evidence, engineering replay artifact ID, survivorship limitation, absence or status of promotion-grade data, unchanged production behavior, and the deferred Option 3 parity replay. Do not state that the strategy has an edge unless a promotion-grade holdout has actually passed.

- [ ] **Step 5: Commit**

```powershell
git add docs/phase-2-authoritative-swing-checkpoint.md
git commit -m "docs: record Phase 2 swing verification"
```
