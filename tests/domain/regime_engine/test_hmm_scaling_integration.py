"""The model fits on standardised features and reports raw ones."""

from __future__ import annotations

import numpy as np

from qat.domain.regime_engine.hmm_core import HMMRegimeModel


def _two_regime_matrix() -> np.ndarray:
    """Two clearly separated regimes, with one column on a VIX-like scale."""
    rng = np.random.default_rng(7)
    calm = np.column_stack(
        [
            rng.normal(0.001, 0.003, 150),  # log_return
            rng.normal(0.08, 0.01, 150),  # realized_vol
            rng.normal(14.0, 1.0, 150),  # vix_level
        ]
    )
    stressed = np.column_stack(
        [
            rng.normal(-0.002, 0.010, 150),
            rng.normal(0.20, 0.02, 150),
            rng.normal(28.0, 2.0, 150),
        ]
    )
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
    tail = model.predict_proba(matrix[-10:])[-1]  # a different window

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


def test_a_collapsed_state_fails_the_fit_by_name():
    """Structureless data cannot support four states, and must say so.

    Asking for more states than the data contains leaves one of them visited by
    no observation. hmmlearn then leaves that state's transmat_ row at zero and
    raises "transmat_ rows must sum to 1" later, from predict() - far from the
    cause and naming nothing. The fit is what failed, so the fit is what should
    say so.
    """
    import pytest

    from qat.domain.regime_engine.hmm_core import DegenerateRegimeFitError

    # NOTE: deviates from the plan's literal `rng.normal(0.0, 1.0, size=(120, 3))`
    # / seed=11. Verified by direct sweep (500 seeds) that shape never collapses
    # a state in this environment: sklearn 1.9's KMeans (n_init=10, called from
    # hmmlearn 0.3.3's _init) relocates would-be-empty clusters during Lloyd's
    # iteration, so a pure isotropic noise cloud never leaves a KMeans-seeded
    # HMM state empty, at any n_states/n_samples ratio tried. Two frozen columns
    # - mirroring `breadth` staying constant in the real fixture that DOES
    # collapse a state (see test_regime_engine.py) - reproduce the same failure
    # deterministically here. seed=6 is simply the first seed found that hits.
    rng = np.random.default_rng(6)
    noise = np.column_stack(
        [
            rng.normal(0.0, 1.0, size=(120, 3)),  # one cloud, no regimes
            np.full(120, 5.0),  # a feature that failed to load stays constant,
            np.full(120, 6.0),  # like `breadth` in the real fixture
        ]
    )

    model = HMMRegimeModel(n_states=8)  # far more states than structure
    with pytest.raises(DegenerateRegimeFitError) as excinfo:
        model.fit(noise)

    assert "state" in str(excinfo.value).lower(), excinfo.value
    assert not model.is_fitted, "a failed fit must not leave a half-built model behind"


def test_refit_logs_which_raw_column_has_the_widest_spread(caplog):
    """The dominance that went unnoticed for the life of the project.

    `_fit` already names columns that never MOVED. A column that moves far more
    than every other one is the same class of fact about the same matrix, and
    it decided where the states were initialised.
    """
    import logging

    from qat.domain.regime_engine.engine import RegimeEngine
    from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES

    rng = np.random.default_rng(3)
    matrix = np.column_stack(
        [
            rng.normal(0.0, 0.0074, 120),
            rng.normal(0.11, 0.0338, 120),
            rng.normal(17.9, 3.0991, 120),
            rng.normal(0.39, 0.3126, 120),
            rng.normal(1.69, 0.0781, 120),
            rng.normal(0.5, 0.05, 120),
        ]
    )

    # __new__ deliberately: constructing a RegimeEngine drags in a bus, a
    # feed and a benchmark, none of which _fit touches. It reads exactly THREE
    # attributes, and ALL must be set or the test fails on an AttributeError
    # that has nothing to do with what it is checking.
    #
    # ⚠️ `_features` was added by Milestone C, and this test found it: `_fit`
    # now names the widest column from the run's OWN feature list rather than
    # the module-level default, because a narrowed matrix zipped against six
    # names raised and the engine published nothing.
    engine = RegimeEngine.__new__(RegimeEngine)
    engine._hmm = HMMRegimeModel(n_states=2)
    engine._non_monotonic_fits = 0  # read when the fit logs a convergence warning
    engine._features = FEATURE_NAMES  # the six columns this matrix is built as

    with caplog.at_level(logging.INFO, logger="qat.domain.regime_engine.engine"):
        engine._fit(matrix)

    assert "vix_level" in caplog.text, caplog.text
    assert "spread" in caplog.text.lower(), caplog.text
