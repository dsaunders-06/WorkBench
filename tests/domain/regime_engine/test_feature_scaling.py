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
    small = rng.normal(0.0, 0.0074, size=300)  # log_return's measured spread
    huge = rng.normal(17.9, 3.0991, size=300)  # vix_level's measured spread
    matrix = np.column_stack([small, huge])

    raw = matrix.std(axis=0) / matrix.std(axis=0).sum()
    assert raw.max() > 0.95, "the fixture should reproduce the domination"

    out = ColumnStandardiser().fit_transform(matrix)
    shares = out.std(axis=0) / out.std(axis=0).sum()
    assert shares.max() < 0.55, f"a column still dominates after scaling: {shares}"


def test_a_constant_column_survives_without_NaN():
    """Constant columns are a KNOWN live condition, not a hypothetical.

    `engine.py:_fit` already logs them by name: a macro series that fails to
    load leaves its feature at a default for the whole session. Dividing by a
    zero standard deviation would turn that logged, survivable warning into a
    matrix full of NaN and a dead classifier.

    The column is CENTRED but not scaled, so it lands on 0.0 rather than
    keeping its raw value. That is fine and is not what this guards: a constant
    offset contributes nothing to Euclidean distance, so it cannot bias the
    KMeans initialisation either way. What matters is that the column stays
    FINITE and stays CONSTANT - the standardiser must never fabricate variance
    the data does not have.
    """
    matrix = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]])
    out = ColumnStandardiser().fit_transform(matrix)

    assert np.isfinite(out).all(), out
    assert out[:, 1].std() == 0.0, "the standardiser must not fabricate variance"


def test_transform_reuses_the_FITTED_statistics():
    """The whole point: inference must use the training scaling.

    If `transform` recomputed the mean and std of whatever it was handed, every
    prediction would be scaled against its own window and the model would be
    reading different units from the ones it was fitted on.
    """
    scaler = ColumnStandardiser()
    scaler.fit(np.array([[0.0], [10.0]]))

    assert np.allclose(scaler.transform(np.array([[5.0]])), [[0.0]])  # training mean
    assert np.allclose(scaler.transform(np.array([[10.0]])), [[1.0]])  # one std above


def test_transform_before_fit_raises():
    scaler = ColumnStandardiser()
    assert not scaler.is_fitted
    try:
        scaler.transform(np.array([[1.0]]))
    except RuntimeError:
        return
    raise AssertionError("transform() before fit() must raise")
