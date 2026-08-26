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
