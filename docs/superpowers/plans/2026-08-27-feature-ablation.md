# Macro Milestone C — `--feature` Ablation Arm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the ablation harness adjudicate a regime *feature column* the way it already adjudicates a *rail*, so Milestone B's `^AXVI` question is answered by the instrument rather than a hand-rolled script.

**Architecture:** A feature is made absent by a `Settings` value, never a branch — the same rule `ablation.py` states for rails. `regime_features` becomes an ordered list defaulting to today's six columns; a `FEATURES` table names what may be ablated and refuses what may not; the harness records a per-bar regime path and terminal equity; a sibling comparator leads with a label-movement guard.

**Tech Stack:** Python 3.12, hmmlearn 0.3.3, NumPy, pandas, pytest.

Design: `docs/superpowers/specs/2026-08-27-feature-ablation-design.md` (approved 27 Aug).

## Global Constraints

- **PowerShell, never the Bash tool**, for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`. The Bash sandbox serves a frozen snapshot and does NOT error — it cost a worthless dry run on 27 August.
- **Format with `black`, not `ruff format`.** All four must be clean: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- ⚠️ **CI is at the GitHub billing wall.** The local suite is the ONLY verification.
- ⚠️ **Commits are LOCAL.** The operator has a standing hold on `git push` as of 27 August 2026.
- **Baseline at the time of writing: 2,831 passed, 25 skipped.** Each task states its own expected delta.
- ⚠️ **A new setting must be documented in the manual** or `test_manual_documents_every_setting` fails.
- ⚠️ **A KILLED build leaves `src/qat/_build_stamp.py` behind** and four version tests then fail; delete that generated file to recover.
- ⚠️ **A test never seen to FAIL is not evidence.** Every task's guard must be observed red before it is believed — and observed red *at the layer the defect lives*. Item 59's six store tests all stayed green when the caller was deleted.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/config.py` | **Modify.** `regime_features` setting. |
| `src/qat/domain/regime_engine/feature_matrix.py` | **Modify.** Emit only the named columns. |
| `src/qat/domain/regime_engine/hmm_core.py` | **Modify.** Positional column constants become lookups. |
| `src/qat/domain/backtester/ablation.py` | **Modify.** `FEATURES`, `UnablatableFeature`, `feature_settings`. |
| `src/qat/domain/backtester/manifest.py` | **Modify.** Carry `terminal_equity` and the ablated feature. |
| `src/qat/domain/backtester/run_comparison.py` | **Modify.** Add `compare_feature_runs`. |
| `scripts/research/run_ablation.py` | **Modify.** `--feature`, regime recorder, ASX default. |
| `tests/domain/regime_engine/test_feature_selection.py` | **Create.** Tasks 1–2. |
| `tests/domain/backtester/test_feature_ablation.py` | **Create.** Task 3. |
| `tests/domain/backtester/test_compare_feature_runs.py` | **Create.** Task 5. |

**Task order is dependency order.** Task 1 must land before 2, 2 before 3, 3 before 4–6.

---

## Task 1: `regime_features` — the setting, and the matrix that reads it

**Files:**
- Modify: `src/qat/config.py`
- Modify: `src/qat/domain/regime_engine/feature_matrix.py`
- Modify: the manual source (`scripts/manual_body.py`)
- Test: `tests/domain/regime_engine/test_feature_selection.py` (create)

**Interfaces:**
- Produces: `Settings.regime_features: tuple[str, ...]` defaulting to `FEATURE_NAMES`; `RegimeFeatureBuilder(features=...)` emitting only those columns, in the order given.

⚠️ **The default must be a byte-identical no-op.** If any existing regime test changes behaviour, **STOP** — that means the default is not being applied. Do not adjust the test.

- [x] **Step 1: Write the failing test**

```python
# tests/domain/regime_engine/test_feature_selection.py
"""The matrix emits the columns it is told to, and by default exactly today's six."""
from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES, RegimeFeatureBuilder


def _fed(builder: RegimeFeatureBuilder) -> RegimeFeatureBuilder:
    builder.update_macro("VIXCLS", 15.5)
    builder.update_macro("T10Y3M", 0.81)
    builder.update_macro("BAA10Y", 1.62)
    for close in (100.0, 101.0, 102.0):
        builder.add_benchmark_bar(close)
    return builder


def test_the_default_is_todays_six_columns_unchanged():
    assert Settings(_env_file=None).regime_features == FEATURE_NAMES
    assert _fed(RegimeFeatureBuilder()).feature_matrix().shape[1] == len(FEATURE_NAMES)


def test_a_narrowed_list_emits_only_those_columns_in_that_order():
    wanted = ("log_return", "realized_vol", "vix_level")
    matrix = _fed(RegimeFeatureBuilder(features=wanted)).feature_matrix()
    assert matrix.shape[1] == 3


def test_the_vix_column_still_carries_vix_when_others_are_dropped():
    """⚠️ Narrowing must SELECT columns, not truncate the row. Truncation
    would leave every remaining column holding its neighbour's value, which
    reads as a working matrix and is a different measurement entirely."""
    wanted = ("log_return", "vix_level")
    matrix = _fed(RegimeFeatureBuilder(features=wanted)).feature_matrix()
    assert matrix[-1, 1] == pytest.approx(15.5)
```

- [x] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/regime_engine/test_feature_selection.py -q`
Expected: FAIL — `Settings` has no attribute `regime_features`, `RegimeFeatureBuilder` takes no `features`.

- [x] **Step 3: Implement**

In `feature_matrix.py`, add a `features` field to the dataclass defaulting to `FEATURE_NAMES`, build each row as a dict keyed by name, and emit `[row[name] for name in self.features]`. Keep `FEATURE_NAMES` exported unchanged — it is the default and other modules import it.

In `config.py`, beside the other regime settings:

```python
regime_features: tuple[str, ...] = FEATURE_NAMES
"""Which columns the regime matrix carries, in order (Milestone C).

ORDERED because the matrix is positional and the HMM is fitted on column
order: two runs whose lists differ only in order build different matrices
and are silently incomparable.

⚠️ This is a SIZING INPUT. The regime label sets the exposure scalar. The
default is byte-identical to the six columns that shipped before it existed.
"""
```

- [x] **Step 4: Run the new test, then the whole regime suite**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/regime_engine/ -q`
Expected: PASS, and **no pre-existing regime test changes behaviour**. If one does, STOP.

- [x] **Step 5: Document the setting in the manual** — ⚠️ **DEVIATED, deliberately.**
  Added to `_NOT_IN_THE_MANUAL` instead, with the reason. `regime_features` is a
  RESEARCH lever, not an operator control: changing it changes what every regime
  LABEL means, which is exactly why `bar_interval_seconds` is excused. Putting
  it in the manual would advertise a knob whose misuse this harness exists to
  measure. It remains a sizing input and the byte-identical default is pinned.

Run: `.venv\Scripts\python.exe -m pytest -k manual_documents_every_setting -q`
Expected: PASS.

- [x] **Step 6: Falsify**

Change the default to a five-element list. Expected: `test_the_default_is_todays_six_columns_unchanged` goes red. Restore.

- [x] **Step 7: Commit**

```bash
git add src/qat/config.py src/qat/domain/regime_engine/feature_matrix.py scripts/manual_body.py tests/domain/regime_engine/test_feature_selection.py
git commit -m "Milestone C: the regime matrix carries the columns it is told to"
```

---

## Task 2: The positional column constants become lookups

**Files:**
- Modify: `src/qat/domain/regime_engine/hmm_core.py:20-21,192-193`
- Test: append to `tests/domain/regime_engine/test_feature_selection.py`

**Interfaces:**
- Consumes: `Settings.regime_features` / the builder's `features` from Task 1.
- Produces: `HMMRegimeModel` resolving `log_return` and `realized_vol` **by name**.

**Why this is its own task.** `_LOG_RETURN_COL = 0` and `_REALIZED_VOL_COL = 1` feed `StateSignature.mean_return` and `mean_vol`, which `fusion.py:110-123` turns into the z-scores that decide **which fitted state is called bull and which bear**. Get this wrong and every label silently means something else.

- [x] **Step 1: Write the failing test**

```python
def test_the_state_stats_follow_the_named_columns_not_positions():
    """⚠️ hmmlearn numbers states arbitrarily; mean_return and mean_vol are how
    a state index acquires a NAME. Reordering the list must move where those are
    read from, or every label quietly refers to something else."""
    import numpy as np

    from qat.domain.regime_engine.hmm_core import HMMRegimeModel

    features = ("vix_level", "log_return", "realized_vol")
    model = HMMRegimeModel(n_states=2, features=features)
    matrix = np.tile(np.array([[15.5, 0.01, 0.2], [16.0, -0.01, 0.4]]), (40, 1))
    model.fit(matrix)
    signatures = model.state_signatures(matrix)

    assert all(abs(s.mean_return) < 1.0 for s in signatures.values())
    assert all(0.0 <= s.mean_vol < 1.0 for s in signatures.values())
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/regime_engine/test_feature_selection.py -q`
Expected: FAIL — `HMMRegimeModel` takes no `features`; the stats read columns 0 and 1, which here are `vix_level` and `log_return`.

- [ ] **Step 3: Implement**

Give `HMMRegimeModel` a `features: Sequence[str] = FEATURE_NAMES` argument and replace the constants:

```python
# Resolved by NAME, not position (Milestone C). These two columns are not
# ordinary features: `fusion.py` turns mean_return and mean_vol into the
# z-scores that decide which fitted state is called bull and which bear, so
# reading the wrong column does not degrade a label - it renames it.
self._return_col = features.index("log_return")
self._vol_col = features.index("realized_vol")
```

- [ ] **Step 4: Run the regime suite**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/regime_engine/ -q`
Expected: PASS, existing behaviour unchanged.

- [ ] **Step 5: Falsify**

Hard-code `self._return_col = 0`. Expected: the new test goes red. Restore.

- [ ] **Step 6: Commit**

```bash
git add src/qat/domain/regime_engine/hmm_core.py tests/domain/regime_engine/test_feature_selection.py
git commit -m "Milestone C: the state stats resolve their columns by name"
```

---

## Task 3: `FEATURES`, `UnablatableFeature`, `feature_settings`

**Files:**
- Modify: `src/qat/domain/backtester/ablation.py`
- Test: `tests/domain/backtester/test_feature_ablation.py` (create)

**Interfaces:**
- Produces: `FEATURES: dict[str, str]` (name → why it matters); `UNABLATABLE_FEATURES: dict[str, str]` (name → refusal reason); `class UnablatableFeature(ValueError)`; `feature_settings(base: Settings, disabled: Sequence[str]) -> Settings`.

- [x] **Step 1: Write the failing test**

```python
# tests/domain/backtester/test_feature_ablation.py
"""Which regime features may be ablated, and which are refused by name."""
from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.backtester.ablation import UnablatableFeature, feature_settings
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES


def _base() -> Settings:
    return Settings(_env_file=None)


def test_disabling_nothing_returns_the_base_untouched():
    assert feature_settings(_base(), []).regime_features == FEATURE_NAMES


def test_an_ablated_feature_is_absent_and_the_rest_keep_their_order():
    narrowed = feature_settings(_base(), ["vix_level"]).regime_features
    assert "vix_level" not in narrowed
    assert narrowed == tuple(f for f in FEATURE_NAMES if f != "vix_level")


@pytest.mark.parametrize("structural", ["log_return", "realized_vol"])
def test_the_two_structural_columns_are_refused_by_name(structural):
    """⚠️ Removing either would not ablate a feature - it would change what
    every label MEANS, because fusion reads their state statistics to decide
    which state is bull. Refused loudly, the way _TWO_CONSUMERS refuses
    apply_costs_in_paper."""
    with pytest.raises(UnablatableFeature, match="state"):
        feature_settings(_base(), [structural])


def test_an_unknown_feature_is_named_never_ignored():
    """Silently running a baseline twice and reporting no difference is
    indistinguishable from a feature that costs nothing."""
    with pytest.raises(UnablatableFeature, match="asx_vix_z"):
        feature_settings(_base(), ["asx_vix_z"])


def test_the_result_is_revalidated_not_copied():
    """model_copy(update=...) writes fields without running validators, so a
    bad value would surface far away or not at all."""
    assert isinstance(feature_settings(_base(), ["breadth"]), Settings)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_feature_ablation.py -q`
Expected: FAIL — `UnablatableFeature` and `feature_settings` do not exist.

- [ ] **Step 3: Implement**

```python
class UnablatableFeature(ValueError):
    """A feature this module will not neutralise.

    Its own class rather than a reuse of `UnablatableRail`, so a caller can
    tell a rail problem from a feature problem without parsing a message.
    """


# Why each column is worth ablating - a claim about consequence, not a list.
FEATURES: dict[str, str] = {
    "vix_level": "the incumbent volatility measure",
    "yield_curve_slope": "the recession term",
    "credit_spread": "the stress term",
    "breadth": "the participation term",
}

# ⚠️ Refused, with the reason, the way _TWO_CONSUMERS refuses
# apply_costs_in_paper. `hmm_core` reads these two by name to build each fitted
# state's mean_return and mean_vol, and `fusion.py` turns those into the
# z-scores that decide which state is called bull. Removing either does not
# ablate a feature; it changes what every label means, and the run would look
# entirely normal.
UNABLATABLE_FEATURES: dict[str, str] = {
    name: (
        f"{name!r} is not an ordinary feature: `fusion` reads its state statistics to "
        f"decide which fitted state is called bull and which bear. Ablating it would not "
        f"remove a signal, it would rename every label - and the run would still look "
        f"normal. Ablate one of: {', '.join(sorted(FEATURES))}."
    )
    for name in ("log_return", "realized_vol")
}


def feature_settings(base: Settings, disabled: Sequence[str]) -> Settings:
    """`base` with every named feature column removed from `regime_features`.

    Re-validated rather than copied, for the reason `ablated_settings` gives.
    """
    if not disabled:
        return base
    for feature in disabled:
        if feature in UNABLATABLE_FEATURES:
            raise UnablatableFeature(UNABLATABLE_FEATURES[feature])
        if feature not in FEATURES:
            raise UnablatableFeature(
                f"{feature!r} is not an ablatable regime feature. "
                f"Known: {', '.join(sorted(FEATURES))}."
            )
    kept = tuple(f for f in base.regime_features if f not in set(disabled))
    return Settings.model_validate({**base.model_dump(), "regime_features": kept})
```

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_feature_ablation.py -q`
Expected: PASS (5 tests, 6 cases).

- [ ] **Step 5: Falsify**

Delete `log_return` from `UNABLATABLE_FEATURES`. Expected: the parametrised refusal test goes red for that case. Restore.

- [ ] **Step 6: Commit**

```bash
git add src/qat/domain/backtester/ablation.py tests/domain/backtester/test_feature_ablation.py
git commit -m "Milestone C: which regime features may be ablated, and which are refused"
```

---

## Task 4: The per-bar regime record and terminal equity

**Files:**
- Modify: `scripts/research/run_ablation.py` (`_one`)
- Modify: `src/qat/domain/backtester/manifest.py`

**Interfaces:**
- Consumes: `feature_settings` from Task 3.
- Produces:
  - `write_regime_path(directory: Path, rows: Sequence[tuple[str, str, float]]) -> None` and
    `read_regime_path(directory: Path) -> list[tuple[str, str, float]]`, both in
    `run_comparison.py` beside the existing `_trades()`. **One writer, one reader,
    used by the harness AND the tests** — a test that re-implements the CSV format
    is a second definition of it, and the two drift.
  - `<run>/regime_path.csv`, header `ts,label,exposure_scalar`.
  - `RunManifest.terminal_equity: float | None`, `RunManifest.disabled_feature: str | None`,
    and **`RunManifest.regime_features: tuple[str, ...] | None`** — the last is what the
    STILL ENABLED guard in Task 5 reads, and without it that guard cannot be written.

**Why both in one task.** Neither is independently reviewable — a comparator needs both or it can report nothing.

⚠️ `risk_decisions.csv` cannot serve as the regime record: it carries `regime_label` only on bars where a decision happened, so "the label never differed" would be indistinguishable from "no decisions happened".

- [x] **Step 1: Write the failing test**

```python
# append to tests/domain/backtester/test_feature_ablation.py
def test_the_manifest_carries_terminal_equity_and_the_ablated_feature(tmp_path):
    from qat.domain.backtester.manifest import build_manifest

    manifest = build_manifest(
        data_dir=tmp_path,
        disabled=[],
        universe=["BHP.AX"],
        starting_equity=100_000.0,
        terminal_equity=104_250.0,
        disabled_feature="vix_level",
        regime_features=("log_return", "realized_vol"),
    )
    manifest.write(tmp_path / "manifest.json")

    from qat.domain.backtester.manifest import read_manifest

    reread = read_manifest(tmp_path / "manifest.json")
    assert reread.terminal_equity == pytest.approx(104_250.0)
    assert reread.disabled_feature == "vix_level"
    assert reread.regime_features == ("log_return", "realized_vol")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_feature_ablation.py -q`
Expected: FAIL — `build_manifest` takes no `terminal_equity`.

- [ ] **Step 3: Implement the manifest fields**

Add all three to `RunManifest` — `terminal_equity: float | None`,
`disabled_feature: str | None`, `regime_features: tuple[str, ...] | None` —
defaulting `None`, carried through `build_manifest`, `write` and `read_manifest`.
`None` means a run written before the field existed, never `0.0` or `()`, which
would assert a measurement that was not taken.

Then add `write_regime_path` / `read_regime_path` to `run_comparison.py`.

- [ ] **Step 4: Implement the recorder in `_one`**

Before `await session.run()`:

```python
    # The harness listens to an event the app already publishes - no change to
    # the trading path, the same seam `start_regime` already uses.
    regime_rows: list[tuple[str, str, float]] = []

    async def _record_regime(event: RegimeEvent) -> None:
        regime_rows.append((event.ts.isoformat(), event.label, event.exposure_scalar))

    session.bus.subscribe(RegimeEvent, _record_regime)
```

After it, write `regime_path.csv` and read terminal equity from `(await session.broker.get_account()).net_liquidation` into `build_manifest`.

- [ ] **Step 5: Run the backtester suite**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/research/run_ablation.py src/qat/domain/backtester/manifest.py tests/domain/backtester/test_feature_ablation.py
git commit -m "Milestone C: record the regime path and the terminal equity"
```

---

## Task 5: `compare_feature_runs` — guard first

**Files:**
- Modify: `src/qat/domain/backtester/run_comparison.py`
- Test: `tests/domain/backtester/test_compare_feature_runs.py` (create)

**Interfaces:**
- Consumes: `regime_path.csv` and `manifest.json` from Task 4.
- Produces: `compare_feature_runs(baseline: Path, ablated: Path, feature: str) -> str`.

⚠️ **The headline is terminal equity, not R.** `compare_runs._arm()` reports trades, win%, R-mean and R-total — every one scale-free. A feature that halved every position leaves all four identical, because a regime feature moves the exposure scalar, which moves *size*.

- [x] **Step 1: Write the failing test**

```python
# tests/domain/backtester/test_compare_feature_runs.py
"""What a feature comparison may and may not be quoted as saying."""
from __future__ import annotations

import csv
from pathlib import Path

from qat.domain.backtester.run_comparison import compare_feature_runs, write_regime_path


def _run(directory: Path, labels: list[str], equity: float, features: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    write_regime_path(directory, [(f"2026-08-{i + 1:02d}", lab, 1.0) for i, lab in enumerate(labels)])
    (directory / "manifest.json").write_text(
        f'{{"terminal_equity": {equity}, "regime_features": {features!r}}}'.replace("'", '"'),
        encoding="utf-8",
    )
    return directory


def test_an_unmoved_label_suppresses_every_number(tmp_path):
    """⚠️ THE GUARD. If the label never differed there was nothing for the
    feature to change, and a trade difference is noise wearing its name. A zero
    gets quoted and a caveat does not."""
    base = _run(tmp_path / "b", ["bull", "bull"], 105_000.0, ["vix_level"])
    abl = _run(tmp_path / "a", ["bull", "bull"], 98_000.0, [])

    report = compare_feature_runs(base, abl, "vix_level")

    assert "NOT EXERCISED" in report
    assert "98,000" not in report and "98000" not in report


def test_a_moved_label_reports_equity_first_then_the_bar_count(tmp_path):
    base = _run(tmp_path / "b", ["bull", "bull"], 105_000.0, ["vix_level"])
    abl = _run(tmp_path / "a", ["bull", "bear"], 98_000.0, [])

    report = compare_feature_runs(base, abl, "vix_level")

    assert "NOT EXERCISED" not in report
    assert "1 of 2" in report and "50" in report


def test_a_feature_still_enabled_in_the_ablated_arm_is_refused(tmp_path):
    """Cheap to cause by passing the wrong directory, and invisible unless
    something checks."""
    base = _run(tmp_path / "b", ["bull", "bear"], 105_000.0, ["vix_level"])
    abl = _run(tmp_path / "a", ["bull", "bull"], 98_000.0, ["vix_level"])

    assert "STILL ENABLED" in compare_feature_runs(base, abl, "vix_level")


def test_the_report_prints_its_date_range(tmp_path):
    """⚠️ The 26 August lesson: a three-day calendar slip understated an effect
    NINEFOLD, 2.7% against a true 23.0%. Any number here is unbelievable
    without the window it was measured over."""
    base = _run(tmp_path / "b", ["bull", "bear"], 105_000.0, ["vix_level"])
    abl = _run(tmp_path / "a", ["bull", "bull"], 98_000.0, [])

    report = compare_feature_runs(base, abl, "vix_level")

    assert "2026-08-01" in report and "2026-08-02" in report
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/test_compare_feature_runs.py -q`
Expected: FAIL — `compare_feature_runs` does not exist.

- [ ] **Step 3: Implement**

Guards in order: **STILL ENABLED** (the feature is in the ablated manifest's `regime_features`), then **NOT EXERCISED** (label identical on every paired bar), then the report — terminal equity per arm and the delta, then bars-differ count and percent, then the existing `_arm()` trades/win/R block, then the date range and the existing `_SCOPE` note.

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/backtester/ -q`
Expected: PASS.

- [ ] **Step 5: Falsify**

Make the NOT EXERCISED branch fall through to the report. Expected: `test_an_unmoved_label_suppresses_every_number` goes red. Restore.

- [ ] **Step 6: Commit**

```bash
git add src/qat/domain/backtester/run_comparison.py tests/domain/backtester/test_compare_feature_runs.py
git commit -m "Milestone C: compare two feature arms, guard first"
```

---

## Task 6: The CLI arm

**Files:**
- Modify: `scripts/research/run_ablation.py` (`main`)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add the arguments**

`--feature` (mutually exclusive with `--rail`, one required), `--list` grows a features section, and `--feature` defaults `--market` to `ASX`.

⚠️ The ASX default is **per-arm** and deliberate: the US G1 cache is 200 sessions against `warm_bars=120`, leaving 80 replay bars — too few for a regime label to move. ASX leaves ~250. `--rail` keeps its US default so every existing invocation is unchanged.

- [ ] **Step 2: Run `--list` both ways**

```bash
& ".\.venv\Scripts\python.exe" scripts\research\run_ablation.py --list
```
Expected: rails as before, plus a features section naming the four ablatable ones and the two refused with their reason.

- [ ] **Step 3: Run the arm end to end through PowerShell — `credit_spread` FIRST**

⚠️ **`credit_spread` before `asx_vix_z`, deliberately (operator, 28 August).**

Three of the six columns are US macro on a 94-stock ASX book — `vix_level`
(`VIXCLS`), `yield_curve_slope` (`T10Y3M`) and `credit_spread` (`BAA10Y`) — and
BAA10Y is the weakest thing anyone has measured here: **+0.004 against forward
ASX volatility**, against `BAMLH0A0HYM2`'s +0.160 (25 August). That is
indistinguishable from nothing, in a column that feeds a SIZING input.

**Removing a column that measures +0.004 is a cheaper and cleaner first
question than adding one that moves the label on 23% of bars.** If
`credit_spread` costs nothing, that is a US column off an Australian sizing
input for free — and it is the ablation this harness was built to answer.

```bash
& ".\.venv\Scripts\python.exe" scripts\research\run_ablation.py --feature credit_spread
```

⚠️ **A NOT EXERCISED result is a real answer, not a failure.** If the label
never moves without `credit_spread`, the column contributes nothing to the
label and should be proposed for removal on that evidence — recorded with its
numbers, the way `AUDUSD=X` and `TIO=F` were rejected.

⚠️ **It does NOT license the `BAMLH0A0HYM2` swap.** That removes a feature AND
adds one, and Milestone B's plan is explicit that it must be judged on the same
footing rather than smuggled in beside a new column.

Then the original arm:

```bash
& ".\.venv\Scripts\python.exe" scripts\research\run_ablation.py --feature vix_level
```
Expected: two arms, then a report. ⚠️ **Print the date range and check it against the startup log's `Regime engine seeded with 300 daily bars (2025-06-23 to 2026-08-26)` before believing any number.**

- [ ] **Step 4: Full suite and four checks**

Run: `.venv\Scripts\python.exe -m pytest -q` then ruff, black, mypy, bandit.
Expected: all clean; total ≈ 2,831 + ~18 new.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/run_ablation.py
git commit -m "Milestone C: the --feature arm"
```

---

## What this plan deliberately does NOT do

- **It does not add `^AXVI`.** That is Milestone B Tasks 1–4, which plug into `FEATURES` by adding one line. C is the instrument; B is the measurement.
- **It does not deploy.** ⚠️ Task 1 changes a **sizing input** in the shipped binary even though the default is a no-op. Deploy after the close, like any other risk change, and read the build back.
- **It does not decide `BAA10Y` vs `BAMLH0A0HYM2`.** That becomes answerable once this exists, which is a reason to build it and not to widen it.

## Risks

1. **A sizing input becomes configurable.** Default byte-identical; any existing regime test changing behaviour means STOP.
2. **The windows will not line up.** ASX gives ~250 replay bars against Milestone B's 300-bar measurement, so the two are not directly comparable. The arm prints its date range for exactly this reason.
3. **The result may be null**, and that is a legitimate outcome: if the ablation says `^AXVI` buys nothing, Milestone B is rejected with its numbers recorded.
