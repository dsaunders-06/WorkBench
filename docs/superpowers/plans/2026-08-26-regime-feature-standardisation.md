# Macro Layer Phase 2 — Regime Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the regime HMM fit on a scale-neutral feature matrix, so that adding Australian macro series to it is statistically meaningful rather than dominated by whichever column happens to carry the largest numbers.

**Architecture:** A `ColumnStandardiser` is fitted on the training matrix and stored on `HMMRegimeModel`. `fit()` standardises before calling hmmlearn, and `predict_proba()` applies the *same stored* transform so inference matches training. State characterisation deliberately keeps reading the RAW matrix, so `StateSignature.mean_return` keeps meaning a return. No feature is added or removed in this milestone — only the scaling of the existing six changes.

**Tech Stack:** Python 3.12, `hmmlearn.hmm.GaussianHMM` (`covariance_type="diag"`), NumPy, pytest.

## Scope decision — read before starting

Phase 2 of `docs/superpowers/specs/2026-08-25-macro-layer-research.md` is three independent subsystems. They are NOT one plan, because **each separately changes a sizing input** — the regime label sets the exposure scalar — and this project's standing rule is that such a change ships alone and is watched for a session.

| Milestone | What | Status |
|---|---|---|
| **A — standardisation** | Scale-neutral matrix, existing six features | **This plan, in full** |
| **B — new ASX features** | `^AXVI`, AU curve, `AUDUSD=X`, `TIO=F`, plus as-of history for non-FRED sources | Task-level sketch; own plan once A has run live |
| **C — feature ablation** | A `--feature` arm for `scripts/research/run_ablation.py` | Task-level sketch; own plan |

**Milestone A is written out fully because it is the blocker and the next real work.** B and C are left at task level on purpose: both are gated on A's measured outcome, and writing bite-sized steps for work whose inputs are not yet known would be inventing detail rather than planning it.

## Global Constraints

- **Run everything through PowerShell, never the Bash tool**, for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`. The Bash sandbox serves a frozen snapshot and does not error.
- **Format with `black`, not `ruff format`.** Before committing, run all four through the venv python: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- ⚠️ **CI is BLOCKED at the GitHub billing wall** (26 Aug 2026, likely until September). Runs fail in ~4s with zero steps. **The local suite is the only verification** — treat it as final.
- **Never deploy mid-session.** Deploy before the open or after the close.
- Baseline before starting: **2,748 passed, 25 skipped.**

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/domain/regime_engine/scaling.py` | **Create.** `ColumnStandardiser` — fit column means/stds once, transform many times, pass constant columns through untouched. |
| `src/qat/domain/regime_engine/hmm_core.py` | **Modify.** `fit()` standardises before hmmlearn; `predict_proba()` reuses the stored transform; `_characterize_states` keeps reading RAW. |
| `src/qat/domain/regime_engine/engine.py` | **Modify.** Log the per-column spread share at refit, so scale dominance is visible rather than inferred. |
| `tests/domain/regime_engine/test_feature_scaling.py` | **Create.** The standardiser's own contract. |
| `tests/domain/regime_engine/test_hmm_scaling_integration.py` | **Create.** Fit and predict agree; signatures stay in raw units. |
| `scripts/research/compare_standardisation.py` | **Create.** Before/after evidence for the deploy. |

---

## Task 1: The column standardiser

**Files:**
- Create: `src/qat/domain/regime_engine/scaling.py`
- Test: `tests/domain/regime_engine/test_feature_scaling.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ColumnStandardiser` with `fit(matrix: np.ndarray) -> None`, `transform(matrix: np.ndarray) -> np.ndarray`, `fit_transform(matrix: np.ndarray) -> np.ndarray`, property `is_fitted: bool`, attributes `means_: np.ndarray | None` and `stds_: np.ndarray | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/regime_engine/test_feature_scaling.py`:

```python
"""The regime feature matrix must be scale-neutral before it is fitted.

GaussianHMM initialises its state means with cluster.KMeans on the RAW matrix
(hmmlearn hmm.py:311). KMeans is Euclidean, so the widest-spread column decides
where the states are first placed. Measured 26 August 2026 over the 300-bar
window the engine actually fits, vix_level carried 87.8% of total spread across
the six features - 420x the spread of log_return, the market's own return. The
regime that sets position size was being initialised almost entirely off one US
series, by accident of scale rather than by design.
"""

from __future__ import annotations

import numpy as np

from qat.domain.regime_engine.scaling import ColumnStandardiser


def test_standardised_columns_have_zero_mean_and_unit_spread():
    matrix = np.array([[1.0, 100.0], [2.0, 300.0], [3.0, 200.0]])
    out = ColumnStandardiser().fit_transform(matrix)

    assert np.allclose(out.mean(axis=0), 0.0, atol=1e-12)
    assert np.allclose(out.std(axis=0), 1.0, atol=1e-12)


def test_no_column_dominates_after_standardising():
    """The defect itself, in miniature: one column 400x the others."""
    rng = np.random.default_rng(0)
    small = rng.normal(0.0, 0.0074, size=300)   # log_return's measured spread
    huge = rng.normal(17.9, 3.0991, size=300)   # vix_level's measured spread
    matrix = np.column_stack([small, huge])

    raw = matrix.std(axis=0) / matrix.std(axis=0).sum()
    assert raw.max() > 0.95, "the fixture should reproduce the domination"

    out = ColumnStandardiser().fit_transform(matrix)
    shares = out.std(axis=0) / out.std(axis=0).sum()
    assert shares.max() < 0.55, f"a column still dominates after scaling: {shares}"


def test_a_constant_column_passes_through_untouched():
    """Constant columns are a KNOWN live condition, not a hypothetical.

    `engine.py:_fit` already logs them by name: a macro series that fails to
    load leaves its feature at a default for the whole session. Dividing by a
    zero standard deviation would turn that logged, survivable warning into a
    matrix full of NaN and a dead classifier.
    """
    matrix = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]])
    out = ColumnStandardiser().fit_transform(matrix)

    assert np.isfinite(out).all(), out
    assert np.allclose(out[:, 1], 5.0), "a constant column should be left alone"


def test_transform_reuses_the_FITTED_statistics():
    """The whole point: inference must use the training scaling.

    If `transform` recomputed the mean and std of whatever it was handed, every
    prediction would be scaled against its own window and the model would be
    reading different units from the ones it was fitted on.
    """
    scaler = ColumnStandardiser()
    scaler.fit(np.array([[0.0], [10.0]]))

    assert np.allclose(scaler.transform(np.array([[5.0]])), [[0.0]])   # training mean
    assert np.allclose(scaler.transform(np.array([[10.0]])), [[1.0]])  # one std above


def test_transform_before_fit_raises():
    scaler = ColumnStandardiser()
    assert not scaler.is_fitted
    try:
        scaler.transform(np.array([[1.0]]))
    except RuntimeError:
        return
    raise AssertionError("transform() before fit() must raise")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/test_feature_scaling.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'qat.domain.regime_engine.scaling'`

- [ ] **Step 3: Write minimal implementation**

Create `src/qat/domain/regime_engine/scaling.py`:

```python
"""Scale-neutral feature matrices for the regime HMM (Phase 2.0).

`GaussianHMM` initialises its state means with `cluster.KMeans` on the raw
matrix, and KMeans is Euclidean - so before this existed, the widest-spread
column decided where the states were first placed. Measured 26 August 2026 on
the 300-bar window the engine fits: `vix_level` held 87.8% of the total spread,
420x `log_return`'s.

EM then re-estimates per-feature variances under `covariance_type="diag"`, so
the raw matrix was never *only* the VIX - but the initialisation it starts from
was, and a 100-iteration EM run from a scale-dominated start stays conditioned
on it.
"""

from __future__ import annotations

import numpy as np


class ColumnStandardiser:
    """Per-column z-score, fitted once and reapplied.

    ⚠️ A column with zero spread is passed through UNCHANGED rather than
    divided by zero. Constant columns are a known live condition - `_fit` in
    `engine.py` already logs them by name when a macro series fails to load and
    its feature sits at a default all session. That is a survivable, logged
    degradation; turning it into a matrix of NaN would not be.
    """

    def __init__(self) -> None:
        self.means_: np.ndarray | None = None
        self.stds_: np.ndarray | None = None

    @property
    def is_fitted(self) -> bool:
        return self.means_ is not None

    def fit(self, matrix: np.ndarray) -> None:
        self.means_ = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        # Exactly-zero spread only. NOT a tolerance: `_fit` deliberately
        # measures flatness as peak-to-peak rather than as a standard
        # deviation, because sixty copies of a real VIX print of 18.21 give a
        # std of 3.5e-15 rather than 0.0. A tolerance here would silently stop
        # scaling a column that does genuinely move.
        self.stds_ = np.where(stds == 0.0, 1.0, stds)

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        if self.means_ is None or self.stds_ is None:
            raise RuntimeError("fit() must be called before transform()")
        result: np.ndarray = (matrix - self.means_) / self.stds_
        return result

    def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
        self.fit(matrix)
        return self.transform(matrix)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/test_feature_scaling.py -q`

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/regime_engine/scaling.py tests/domain/regime_engine/test_feature_scaling.py
git commit -m "Phase 2.0: a column standardiser for the regime feature matrix"
```

---

## Task 2: Fit and predict on the standardised matrix, characterise on the raw one

**Files:**
- Modify: `src/qat/domain/regime_engine/hmm_core.py` — `__init__`, `fit`, `predict_proba`, `_characterize_states`
- Test: `tests/domain/regime_engine/test_hmm_scaling_integration.py`

**Interfaces:**
- Consumes: `ColumnStandardiser` from Task 1 — `fit_transform`, `transform`, `is_fitted`.
- Produces: `HMMRegimeModel` unchanged in signature. `fit(feature_matrix)` and `predict_proba(feature_matrix)` still take a RAW matrix; scaling becomes internal. New read-only property `scaler: ColumnStandardiser`.

⚠️ **The one thing that must not change:** `_characterize_states` reads `feature_matrix[mask, _LOG_RETURN_COL]` and `[_REALIZED_VOL_COL]` to build `StateSignature`. It must keep receiving the **raw** matrix. `fusion.py` z-scores those signatures across states, so it is arithmetically invariant to an affine rescale — but `StateSignature.mean_return` should keep meaning a return, not a z-score, for the first consumer that displays it.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/regime_engine/test_hmm_scaling_integration.py`:

```python
"""The model fits on standardised features and reports raw ones."""

from __future__ import annotations

import numpy as np

from qat.domain.regime_engine.hmm_core import HMMRegimeModel


def _two_regime_matrix() -> np.ndarray:
    """Two clearly separated regimes, with one column on a VIX-like scale."""
    rng = np.random.default_rng(7)
    calm = np.column_stack([
        rng.normal(0.001, 0.003, 150),   # log_return
        rng.normal(0.08, 0.01, 150),     # realized_vol
        rng.normal(14.0, 1.0, 150),      # vix_level
    ])
    stressed = np.column_stack([
        rng.normal(-0.002, 0.010, 150),
        rng.normal(0.20, 0.02, 150),
        rng.normal(28.0, 2.0, 150),
    ])
    return np.vstack([calm, stressed])


def test_state_signatures_stay_in_RAW_units():
    """A z-scored mean_return is not a return.

    fusion.py happens to be invariant to this, because it z-scores the
    signatures across states. That invariance is not a licence to feed it
    standardised inputs - the field is named mean_return, and the next consumer
    to read it will believe the name.
    """
    model = HMMRegimeModel(n_states=2)
    model.fit(_two_regime_matrix())

    returns = [s.mean_return for s in model.state_signatures.values()]
    finite = [r for r in returns if np.isfinite(r)]
    assert finite, "no state was assigned any observations"
    # Raw log returns live near zero; z-scores would be order 1.
    assert max(abs(r) for r in finite) < 0.05, f"signatures look standardised: {returns}"


def test_predict_proba_uses_the_SAME_scaling_as_the_fit():
    """Inference must not rescale against its own window.

    The failure this guards against is silent: predict_proba handed a shorter
    matrix would recompute a different mean and std, and the model would read
    units it was never fitted on. The posterior would still be a valid
    probability vector, which is exactly why nothing downstream would notice.
    """
    matrix = _two_regime_matrix()
    model = HMMRegimeModel(n_states=2)
    model.fit(matrix)

    full = model.predict_proba(matrix)[-1]
    tail = model.predict_proba(matrix[-10:])[-1]   # a different window

    assert np.allclose(full, tail, atol=1e-9), (
        f"the same final bar classified differently from a different window: "
        f"{full} vs {tail} - predict_proba is rescaling instead of reusing the fit"
    )


def test_the_scaler_is_fitted_after_fit():
    model = HMMRegimeModel(n_states=2)
    assert not model.scaler.is_fitted
    model.fit(_two_regime_matrix())
    assert model.scaler.is_fitted


def test_a_constant_column_still_fits():
    """A macro series that failed to load leaves a constant column."""
    matrix = _two_regime_matrix()
    matrix[:, 2] = 14.0
    model = HMMRegimeModel(n_states=2)
    model.fit(matrix)

    assert model.is_fitted
    assert np.isfinite(model.predict_proba(matrix)).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/test_hmm_scaling_integration.py -q`

Expected: FAIL — `AttributeError: 'HMMRegimeModel' object has no attribute 'scaler'`, and `test_predict_proba_uses_the_SAME_scaling_as_the_fit` fails because nothing is scaled yet.

- [ ] **Step 3: Write minimal implementation**

In `src/qat/domain/regime_engine/hmm_core.py`, add beside the other local imports:

```python
from qat.domain.regime_engine.scaling import ColumnStandardiser
```

In `HMMRegimeModel.__init__`, after `self._model = None`, add:

```python
        self._scaler = ColumnStandardiser()
```

Add beside the other properties:

```python
    @property
    def scaler(self) -> ColumnStandardiser:
        """The transform this model was fitted under.

        Exposed so a caller can see WHETHER scaling happened. Read-only:
        replacing it after a fit would leave the model reading different units
        from the ones it was trained on, which is the exact failure
        `test_predict_proba_uses_the_SAME_scaling_as_the_fit` exists to catch.
        """
        return self._scaler
```

Replace the body of `fit` from the `GaussianHMM(...)` construction onwards with:

```python
        # Standardise BEFORE hmmlearn sees it. KMeans initialisation is
        # Euclidean on the raw matrix, so without this the widest-spread
        # column decides where the states are placed - measured at 87.8% for
        # vix_level on 26 August 2026.
        scaled = self._scaler.fit_transform(feature_matrix)
        model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            random_state=self.random_state,
            n_iter=self.n_iter,
        )
        hmmlearn_logger = logging.getLogger(_HMMLEARN_LOGGER_NAME)
        warning_filter = _NonMonotonicFilter()
        hmmlearn_logger.addFilter(warning_filter)
        try:
            model.fit(scaled)
        finally:
            hmmlearn_logger.removeFilter(warning_filter)
        self._decreasing_loglik_warnings = warning_filter.count
        self._model = model
        # ⚠️ RAW, deliberately. StateSignature.mean_return must keep meaning a
        # return. `_characterize_states` scales internally for its own
        # `model.predict` call.
        self._state_signatures = self._characterize_states(feature_matrix)
```

Change `predict_proba` to:

```python
    def predict_proba(self, feature_matrix: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("fit() must be called before predict_proba()")
        result: np.ndarray = self._model.predict_proba(self._scaler.transform(feature_matrix))
        return result
```

In `_characterize_states`, change only the `states = ...` line:

```python
        # predict needs the units the model was fitted in; the MEANS below are
        # read from the RAW matrix so the signature stays in real units.
        states = model.predict(self._scaler.transform(feature_matrix))
```

Leave the rest of `_characterize_states` exactly as it is.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/ -q`

Expected: all pass, including the pre-existing `test_hmm_core.py` and `test_regime_engine.py`.

⚠️ **If a pre-existing regime test now fails, STOP and read it before touching it.** On 25 August a suppression test caught a fix that would have shipped the exact bug the guard existed to prevent. A test asserting a specific label on specific data is *supposed* to be sensitive to this change — that is the change working. Record what moved; do not retune an assertion to match new output without understanding why it moved.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/regime_engine/hmm_core.py tests/domain/regime_engine/test_hmm_scaling_integration.py
git commit -m "Phase 2.0: fit and predict on standardised features, characterise on raw"
```

---

## Task 3: Make scale dominance visible at every refit

**Files:**
- Modify: `src/qat/domain/regime_engine/engine.py` — inside `_fit`, after the existing flat-column warning and before the `Refitting the regime HMM` line
- Test: `tests/domain/regime_engine/test_hmm_scaling_integration.py` (append)

**Interfaces:**
- Consumes: `FEATURE_NAMES`, already imported at `engine.py:33`.
- Produces: one INFO line per refit naming the widest-spread raw column and its share.

**Why this task exists:** the domination was invisible for the life of the project and was only found by reconstructing the matrix by hand. `_fit` already names columns that never moved; it should equally name a column that moves far more than the rest.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/regime_engine/test_hmm_scaling_integration.py`:

```python
def test_refit_logs_which_raw_column_has_the_widest_spread(caplog):
    """The dominance that went unnoticed for the life of the project.

    `_fit` already names columns that never MOVED. A column that moves far more
    than every other one is the same class of fact about the same matrix, and
    it decided where the states were initialised.
    """
    import logging

    from qat.domain.regime_engine.engine import RegimeEngine

    rng = np.random.default_rng(3)
    matrix = np.column_stack([
        rng.normal(0.0, 0.0074, 120),
        rng.normal(0.11, 0.0338, 120),
        rng.normal(17.9, 3.0991, 120),
        rng.normal(0.39, 0.3126, 120),
        rng.normal(1.69, 0.0781, 120),
        rng.normal(0.5, 0.05, 120),
    ])

    # __new__ deliberately: constructing a RegimeEngine drags in a bus, a
    # feed and a benchmark, none of which _fit touches. It reads exactly two
    # attributes, and BOTH must be set or the test fails on an AttributeError
    # that has nothing to do with what it is checking.
    engine = RegimeEngine.__new__(RegimeEngine)
    engine._hmm = HMMRegimeModel(n_states=2)
    engine._non_monotonic_fits = 0   # read when the fit logs a convergence warning

    with caplog.at_level(logging.INFO, logger="qat.domain.regime_engine.engine"):
        engine._fit(matrix)

    assert "vix_level" in caplog.text, caplog.text
    assert "spread" in caplog.text.lower(), caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/test_hmm_scaling_integration.py::test_refit_logs_which_raw_column_has_the_widest_spread -q`

Expected: FAIL on `assert "vix_level" in caplog.text`

- [ ] **Step 3: Write minimal implementation**

In `engine.py`, immediately after the existing `if flat:` block and before `logger.info("Refitting the regime HMM on %d bars x %d features", *matrix.shape)`, insert:

```python
        # Which column would dominate a Euclidean initialisation, and by how
        # much. The matrix is standardised inside HMMRegimeModel.fit before
        # hmmlearn sees it, so this is a statement about the RAW features - it
        # is here so the operator can SEE the shape of the input rather than
        # infer it. Measured 26 August 2026: vix_level held 87.8% of total
        # spread, 420x log_return's, and nothing said so.
        spreads = matrix.std(axis=0)
        total_spread = float(spreads.sum())
        if total_spread > 0.0:
            shares = spreads / total_spread
            widest = int(shares.argmax())
            logger.info(
                "Raw feature spread is led by %s at %.1f%% of the total; the matrix is "
                "standardised before fitting so this does not bias the states",
                FEATURE_NAMES[widest],
                shares[widest] * 100.0,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/domain/regime_engine/ -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/regime_engine/engine.py tests/domain/regime_engine/test_hmm_scaling_integration.py
git commit -m "Phase 2.0: name the widest-spread raw feature at every refit"
```

---

## Task 4: Before/after evidence for the deploy

**Files:**
- Create: `scripts/research/compare_standardisation.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `HMMRegimeModel.fit`/`predict_proba`, `ColumnStandardiser`, `FEATURE_NAMES`.
- Produces: printed output only. No repo state, no data-directory writes.

**Why:** *"A changed label with no stated reason is not an improvement"* (spec §2.2). This milestone changes the live label with no new data, so the deploy needs a number beside it.

- [ ] **Step 1: Decide how to obtain a real matrix**

The comparison must run on a real warm-start matrix; a comparison on invented data proves nothing about the live label. Two routes, in order of preference:

1. Rebuild the warm start offline the way `runtime.py` does, and `np.save` the result of `builder.feature_matrix()`.
2. If that cannot be reproduced offline, add a single `np.save` behind a debug flag in the engine, run one launch **before the open**, then remove the flag.

⚠️ **Do not commit the `.npy`.** It is a snapshot of live market state.

- [ ] **Step 2: Add the ignore rule**

Append to `.gitignore`:

```
scripts/research/regime_matrix.npy
```

- [ ] **Step 3: Write the script**

Create `scripts/research/compare_standardisation.py`:

```python
"""The regime posterior with and without standardisation, on identical data.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\compare_standardisation.py

**RUN THROUGH POWERSHELL, NEVER BASH.** The Bash sandbox serves a frozen
snapshot of the data directory and does not error.

READ ONLY. It writes nothing: no data directory, no ledger, no cache.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))

from hmmlearn.hmm import GaussianHMM  # noqa: E402

from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES  # noqa: E402
from qat.domain.regime_engine.hmm_core import HMMRegimeModel  # noqa: E402
from qat.domain.regime_engine.scaling import ColumnStandardiser  # noqa: E402

_N_STATES = 4


def _unscaled_posterior(matrix: np.ndarray) -> np.ndarray:
    """The OLD behaviour, reproduced exactly: hmmlearn fitted on the raw matrix."""
    model = GaussianHMM(
        n_components=_N_STATES, covariance_type="diag", random_state=0, n_iter=100
    )
    model.fit(matrix)
    posterior: np.ndarray = model.predict_proba(matrix)[-1]
    return posterior


def main() -> None:
    path = pathlib.Path("scripts/research/regime_matrix.npy")
    if not path.exists():
        print(f"No matrix at {path} - see Task 4 Step 1 of the plan.")
        raise SystemExit(1)

    matrix = np.load(path)
    print(f"matrix: {matrix.shape[0]} bars x {matrix.shape[1]} features\n")

    spreads = matrix.std(axis=0)
    shares = spreads / spreads.sum()
    print(f"{'feature':<20}{'std':>12}{'share':>10}")
    print("-" * 42)
    for name, spread, share in zip(FEATURE_NAMES, spreads, shares, strict=True):
        print(f"{name:<20}{spread:>12.4f}{share:>9.1%}")

    scaled = ColumnStandardiser().fit_transform(matrix).std(axis=0)
    scaled = scaled / scaled.sum()
    print(f"\nwidest share   raw {shares.max():.1%}  ->  standardised {scaled.max():.1%}")

    before = _unscaled_posterior(matrix)
    after_model = HMMRegimeModel(n_states=_N_STATES)
    after_model.fit(matrix)
    after = np.asarray(after_model.predict_proba(matrix)[-1])

    print("\nfinal-bar posterior")
    print(f"  before (raw fit)      {np.round(before, 3).tolist()}")
    print(f"  after  (standardised) {np.round(after, 3).tolist()}")
    print(
        "\n⚠️ STATE INDICES ARE NOT COMPARABLE ACROSS FITS - hmmlearn numbers states\n"
        "   arbitrarily. Compare the SHAPE of the posterior and the label the fusion\n"
        "   layer derives from it, never the raw index."
    )


main()
```

- [ ] **Step 4: Run it and record the output**

Run: `.venv/Scripts/python.exe scripts/research/compare_standardisation.py`

Expected: the raw widest share reproduces roughly the 87.8% measured on 26 August, and the standardised share falls to about `1/n_features` (≈16.7% for six).

- [ ] **Step 5: Commit**

```bash
git add scripts/research/compare_standardisation.py .gitignore
git commit -m "Phase 2.0: before/after comparison for the standardisation deploy"
```

---

## Task 5: Full verification, deploy, and a watched session

**Files:** none — this task is the gate.

- [ ] **Step 1: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: at least `2,748 passed` plus the new tests, `25 skipped`.

- [ ] **Step 2: Run the four checks**

Run each through the venv python: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`

Expected: all clean. **This is the whole of the verification — CI is walled.**

- [ ] **Step 3: Record the before/after in the milestone notes**

Put the `compare_standardisation.py` output into `src/qat/version.py`'s milestone block. A label change with no recorded reason is exactly what this task exists to prevent.

- [ ] **Step 4: Build, sign, verify, deploy**

Build only from a clean tree, or the stamp carries `-dirty`. Verify the installed exe is SHA256-identical to the signed artefact, confirm the signature is Valid on the INSTALLED copy, and update `DEPLOYED` in `scripts/handoff_state.py` in the same minute as the copy.

- [ ] **Step 5: Read the build back off its own log**

The deployed build is an observation, not an intention. Confirm the stamp in `qat.log` before calling it deployed.

- [ ] **Step 6: Watch one full session**

⚠️ **This milestone changes a SIZING input.** The regime label sets the exposure scalar, and this changes the label with no new data at all. Watch for:

- the new `Raw feature spread is led by ...` line at each refit;
- whether the label differs from the previous session's under comparable conditions, and if so that the difference is explicable from the recorded before/after;
- the governor's aggregate risk figure across the session, against the previous session's.

**If the label becomes unstable — flipping between refits where it previously held — stop and record it.** That is the signal that standardisation changed the fit's character rather than merely its scale.

---

## Milestone B — new ASX regime features (sketch; own plan after A has run)

Gated on Milestone A being deployed and watched.

| # | Task | Note |
|---|---|---|
| B1 | Generalise `load_macro_history` / `MacroHistory` beyond FRED | The as-of join is FRED-shaped today. `^AXVI` and friends need the same treatment — this is the hidden cost the original plan does not price. |
| B2 | `MarketSeriesSource` for yfinance tickers behind `MacroDataSource` | Shared with Phase 1; already done if Phase 1 has landed. |
| B3 | A per-series transformation policy in `feature_matrix.py` | **The blocker A does NOT solve.** |
| B4 | Add candidates one at a time, each with its own ablation | `^AXVI` first — best measured forward correlation (+0.403 vs `VIXCLS`'s +0.289). |
| B5 | Judge the incumbents by the same rule | `BAA10Y` measured +0.004 against forward ASX vol; `BAMLH0A0HYM2` is the candidate replacement and needs no new source. |

⚠️ **B3 is a distinct problem from A and must not be folded into it.** A makes columns comparable in *scale*; it does nothing about *stationarity*. `TIO=F` and `^AXJO` are trending price levels, and a z-score of a trend is still a trend — the mean and std are fitted once on a window the trend then walks away from. They must enter as log changes, not levels. The existing six are all stationary by construction, which is why A alone is safe for them.

## Milestone C — feature ablation (sketch; own plan)

`scripts/research/run_ablation.py` is built, tested and mature — a run manifest, a frozen macro cache, and a guard that suppresses the comparison when a rail never bound rather than printing a misleading zero. **But its arm is `--rail`; there is no feature dimension.**

| # | Task | Note |
|---|---|---|
| C1 | Add a `--feature <name>` arm that holds a column out and refits | Mirrors the existing `--rail` plumbing. |
| C2 | Carry the held-out feature into the run manifest | The manifest already records which rails were on. |
| C3 | Port the rail guard to features | *"A rail that never bound cannot be ablated"* has an exact analogue: a feature that never moved cannot be ablated, and `_fit` already detects that condition by name. |
| C4 | State the admission rule and write it into the spec | Without it, every measured feature gets kept — which is Gap 4. |

---

## Self-Review

**Spec coverage.** Gap 3 (scaling) is Tasks 1–3, with its test requirement in Task 1 Step 1 and Task 3. Spec §2.2's "before and after on the governor's aggregate" is Task 4 and Task 5 Step 6. Gap 1 (the `DGS3MO`/`DGS10` error) was documentation and is corrected in the spec revision, not here. Gap 2 (reviewing incumbents) is B5. Gap 4 (decision rule) is C4. **Gap 2 and Gap 4 are deliberately NOT in Milestone A** — both depend on C1 existing first.

**Placeholder scan.** Task 4 Step 1 is the one soft spot: how to capture a live feature matrix depends on whether the warm start can be reproduced offline, which is not established. It is written as a decision between two named routes rather than a "TBD", and it blocks only the evidence script, not the fix itself.

**Type consistency.** `ColumnStandardiser.fit` / `transform` / `fit_transform` / `is_fitted` / `means_` / `stds_` are used identically in Tasks 1, 2 and 4. `HMMRegimeModel.scaler` is defined in Task 2 and used in Task 4's test and Task 3's. `FEATURE_NAMES` is already imported at `engine.py:33`, so Task 3 needs no new import.
