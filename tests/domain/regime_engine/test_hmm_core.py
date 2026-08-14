from __future__ import annotations

import numpy as np
import pytest

from qat.domain.regime_engine.hmm_core import HMMRegimeModel


def _two_regime_matrix(n_per_regime: int = 40, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    bull = rng.normal(loc=[0.01, 0.005], scale=[0.002, 0.001], size=(n_per_regime, 2))
    bear = rng.normal(loc=[-0.01, 0.03], scale=[0.003, 0.005], size=(n_per_regime, 2))
    extra_bull = rng.normal(
        loc=[15.0, 1.0, 1.0, 0.7], scale=[1.0, 0.1, 0.1, 0.05], size=(n_per_regime, 4)
    )
    extra_bear = rng.normal(
        loc=[30.0, -0.2, 2.0, 0.3], scale=[2.0, 0.1, 0.2, 0.05], size=(n_per_regime, 4)
    )
    bull_full = np.hstack([bull, extra_bull])
    bear_full = np.hstack([bear, extra_bear])
    return np.vstack([bull_full, bear_full])


def test_fit_requires_minimum_rows():
    model = HMMRegimeModel(n_states=4)
    with pytest.raises(ValueError):
        model.fit(np.zeros((3, 6)))


def test_predict_proba_before_fit_raises():
    model = HMMRegimeModel(n_states=2)
    with pytest.raises(RuntimeError):
        model.predict_proba(np.zeros((5, 6)))


def test_state_signatures_before_fit_raises():
    model = HMMRegimeModel(n_states=2)
    with pytest.raises(RuntimeError):
        _ = model.state_signatures


def test_fit_separates_high_and_low_vol_states():
    matrix = _two_regime_matrix()
    model = HMMRegimeModel(n_states=2, random_state=1)
    model.fit(matrix)

    vols = sorted(sig.mean_vol for sig in model.state_signatures.values())
    assert vols[-1] - vols[0] > 0.005


def test_predict_proba_rows_sum_to_one():
    matrix = _two_regime_matrix()
    model = HMMRegimeModel(n_states=2, random_state=1)
    model.fit(matrix)

    posterior = model.predict_proba(matrix)
    assert posterior.shape == (len(matrix), 2)
    row_sums = posterior.sum(axis=1)
    assert (abs(row_sums - 1.0) < 1e-6).all()


def test_is_fitted_flag():
    model = HMMRegimeModel(n_states=2)
    assert model.is_fitted is False
    model.fit(_two_regime_matrix())
    assert model.is_fitted is True


def test_converged_before_any_fit_is_false_not_an_exception():
    """An observability accessor, not a gate - reading it early must never be
    the thing that breaks a run, so "no fit has converged" reads as False
    rather than raising the way `state_signatures` does before `fit()`."""
    model = HMMRegimeModel(n_states=2)
    assert model.converged is False


def test_a_converged_fit_reports_converged_true():
    """Covers the ordinary path only: `_two_regime_matrix` is well-separated
    enough that hmmlearn's EM converges inside the default `n_iter=100`, which
    this asserts on. It does not exercise the non-convergent branch - driving
    that would mean fitting deliberately pathological data, which is slower
    and flakier than the engine-level counter test that drives
    `HMMRegimeModel.converged` directly."""
    matrix = _two_regime_matrix()
    model = HMMRegimeModel(n_states=2, random_state=1)
    model.fit(matrix)

    assert model.converged is True
