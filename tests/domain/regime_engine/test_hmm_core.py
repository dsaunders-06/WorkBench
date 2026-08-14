from __future__ import annotations

import inspect
import logging

import numpy as np
import pytest

from qat.domain.regime_engine.hmm_core import HMMRegimeModel, _NonMonotonicFilter


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


def test_decreasing_loglik_warnings_before_any_fit_is_zero_not_an_exception():
    """An observability accessor, not a gate - reading it early must never be
    the thing that breaks a run, so "no fit has logged the warning" reads as
    0 rather than raising the way `state_signatures` does before `fit()`."""
    model = HMMRegimeModel(n_states=2)
    assert model.decreasing_loglik_warnings == 0


# --- _NonMonotonicFilter (counts hmmlearn's own warning) --------------------
#
# The previous accessor here was `HMMRegimeModel.converged`, built on
# `monitor_.converged` - which hmmlearn defines as True when EITHER the fit
# reached a fixed point OR it simply exhausted `n_iter`
# (`self.iter == self.n_iter` is the first clause). That flag cannot tell
# "converged cleanly" from "ran out of iterations", so it is gone. What
# replaces it counts the warning hmmlearn itself logs when the EM
# log-likelihood decreases between iterations - a real, narrower pathology
# that `converged` never reported either way.


def test_non_monotonic_filter_counts_a_real_hmmlearn_warning():
    """Real logger name (`hmmlearn.base`) and real message text, per the
    brief: the coupling to hmmlearn's wording IS the risk being tested, and a
    test that mocks it away would test nothing."""
    warning_filter = _NonMonotonicFilter()
    logger = logging.getLogger("hmmlearn.base")
    logger.addFilter(warning_filter)
    try:
        logger.warning(
            "Model is not converging.  Current: -123.4 is not greater than "
            "-100.0. Delta is -23.4"
        )
    finally:
        logger.removeFilter(warning_filter)

    assert warning_filter.count == 1


def test_non_monotonic_filter_suppresses_nothing(caplog):
    """`filter()` always returns True - it counts, it never silences. A
    caller's own logging configuration must still see the record."""
    warning_filter = _NonMonotonicFilter()
    logger = logging.getLogger("hmmlearn.base")
    logger.addFilter(warning_filter)
    try:
        with caplog.at_level(logging.WARNING, logger="hmmlearn.base"):
            logger.warning("Model is not converging.  Current: -1.0 is not greater than 0.0.")
    finally:
        logger.removeFilter(warning_filter)

    assert "Model is not converging" in caplog.text


def test_non_monotonic_filter_ignores_unrelated_records():
    """Only hmmlearn's specific warning is counted - an unrelated log line
    through the same logger must not inflate the count."""
    warning_filter = _NonMonotonicFilter()
    logger = logging.getLogger("hmmlearn.base")
    logger.addFilter(warning_filter)
    try:
        logger.warning("Some unrelated hmmlearn message")
    finally:
        logger.removeFilter(warning_filter)

    assert warning_filter.count == 0


def test_hmmlearn_still_emits_the_warning_text_this_filter_matches():
    """Cheap guard against hmmlearn silently changing its wording, which
    would zero `decreasing_loglik_warnings` from then on without any test
    here failing to say so - a future release could still reword the message
    in a way this substring check would not catch mid-string. Verified
    against hmmlearn 0.3.3 (`ConvergenceMonitor.report`,
    `hmmlearn/base.py`), where the emitted text starts exactly with "Model is
    not converging.". NOT covered: any hmmlearn version other than the one
    installed when this test runs, and any rewording that keeps this exact
    substring while changing behaviour around it."""
    import hmmlearn.base as hmmlearn_base

    source = inspect.getsource(hmmlearn_base)
    assert "Model is not converging" in source
