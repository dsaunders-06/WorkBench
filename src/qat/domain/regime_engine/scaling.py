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
