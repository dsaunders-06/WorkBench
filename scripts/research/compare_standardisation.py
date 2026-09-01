"""The regime posterior with and without standardisation, on identical data.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\compare_standardisation.py

**RUN THROUGH POWERSHELL, NEVER BASH.** The Bash sandbox serves a frozen
snapshot of the data directory and does not error.

READ ONLY. It writes nothing: no data directory, no ledger, no cache.

The raw posterior alone demonstrates nothing about the deploy: hmmlearn
numbers states arbitrarily, so a different index between two fits is
expected and uninformative on its own (see the closing warning below). What
the operator and the sizer actually see is the NAMED regime label and the
EXPOSURE SCALAR the fusion layer derives from it, so this script carries
each arm's posterior through the application's own fusion path -
`RegimeFusion.compute` + `HysteresisGate` + `exposure_scalar_for`
(`qat.domain.regime_engine.fusion`), the same path `RegimeEngine` calls in
`engine.py` - using each arm's OWN `state_signatures`, since those are what
turn an arbitrary state index into "bull" or "bear" in the first place.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))

from hmmlearn.hmm import GaussianHMM  # noqa: E402

from qat.domain.regime import Regime  # noqa: E402
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES  # noqa: E402
from qat.domain.regime_engine.fusion import (  # noqa: E402
    HysteresisGate,
    RegimeFusion,
    exposure_scalar_for,
)
from qat.domain.regime_engine.hmm_core import HMMRegimeModel, StateSignature  # noqa: E402
from qat.domain.regime_engine.scaling import ColumnStandardiser  # noqa: E402

_N_STATES = 4

# Same columns HMMRegimeModel._characterize_states reads a state's signature
# from, and the same columns engine.py reads the fusion inputs from off the
# latest feature row. Not re-declared as new constants: imported/mirrored so
# a future rename of these columns cannot make this script silently compare
# the wrong pair.
_VIX_COL = 2
_YIELD_CURVE_COL = 3


class _IdentityScaler:
    """Stand-in for ColumnStandardiser, for the raw arm only.

    HMMRegimeModel._characterize_states calls `self._scaler.transform(...)`
    before `model.predict(...)`, because a fitted model must see inputs in
    the units it was fitted on. The 'before' GaussianHMM below is fitted on
    the RAW matrix - reproducing the old, unstandardised behaviour exactly -
    so its own characterisation must skip scaling too, or the states it
    predicts would not match the states it was actually fitted with.
    """

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        return matrix


def _unscaled_fit(matrix: np.ndarray) -> tuple[np.ndarray, dict[int, StateSignature]]:
    """The OLD behaviour, reproduced exactly: hmmlearn fitted on the raw
    matrix. Its states are then characterised the same way HMMRegimeModel
    does its own - by reusing HMMRegimeModel._characterize_states itself,
    not a second copy of that mapping - so this arm's states are put in the
    same real-units terms (mean_return, mean_vol) as the standardised arm's,
    and are therefore just as meaningful going into the fusion layer.
    """
    model = GaussianHMM(n_components=_N_STATES, covariance_type="diag", random_state=0, n_iter=100)
    model.fit(matrix)
    posterior: np.ndarray = model.predict_proba(matrix)[-1]

    # A bare wrapper, never fit(): only borrowing _characterize_states, which
    # needs self._model and self._scaler set to describe THIS (raw) fit.
    wrapper = HMMRegimeModel(n_states=_N_STATES)
    wrapper._model = model
    wrapper._scaler = _IdentityScaler()  # type: ignore[assignment]
    signatures = wrapper._characterize_states(matrix)
    return posterior, signatures


def _label_and_scalar(
    posterior: np.ndarray,
    signatures: dict[int, StateSignature],
    matrix: np.ndarray,
    gate: HysteresisGate | None = None,
) -> tuple[Regime, float]:
    """Mirrors the posterior -> probs -> label -> scalar path in
    engine.py's `_on_market_data` (RegimeFusion.compute, then
    HysteresisGate.update, then exposure_scalar_for), using the SAME fusion
    and hysteresis classes the live engine does - not a reimplementation.

    `regime_matrix.npy` carries only the columns the HMM fits on, not raw
    closes, so there is no real price/sma_200 to pass. This uses the same
    "not enough SMA history yet" values `RegimeEngine._current_sma` itself
    falls back to below 200 closes (sma_200=0.0, price=0.0), under which
    `is_bull_blocked` and the recovery `near_reclaim` check are both no-ops -
    exactly as they are early in a real session. yield_curve_slope_prev is
    set equal to the latest reading (zero curve-steepening), since only one
    macro snapshot is saved per arm. Both arms receive identical treatment
    here, so none of this can be the source of any difference between them -
    only the HMM posterior and state_signatures can be.
    """
    latest_row = matrix[-1]
    vix_level = float(latest_row[_VIX_COL])
    yield_curve_slope = float(latest_row[_YIELD_CURVE_COL])

    probs = RegimeFusion().compute(
        posterior=posterior.tolist(),
        signatures=signatures,
        yield_curve_slope=yield_curve_slope,
        yield_curve_slope_prev=yield_curve_slope,
        vix_level=vix_level,
        price=0.0,
        sma_200=0.0,
        sma_200_prev=0.0,
    )
    # ⚠️ `gate` IS THE DIFFERENCE BETWEEN THIS AND PRODUCTION, and the default
    # is the wrong one ON PURPOSE. A fresh gate per call takes the
    # `_current_label is None` branch and returns the argmax immediately, so
    # `margin=0.15` and `min_persistence=3` NEVER ENGAGE. The live engine builds
    # ONE gate in `RegimeEngine.__init__` (engine.py:97) and keeps it for the
    # session (engine.py:386).
    #
    # The default is preserved rather than corrected so that every figure taken
    # through this function before 1 September 2026 stays reproducible - the old
    # numbers are the control on this change. A caller wanting production's path
    # passes ONE gate and reuses it across bars, in order.
    label = (gate if gate is not None else HysteresisGate()).update(probs)
    scalar = exposure_scalar_for(label)
    return label, scalar


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

    # The unstandardised arm reproduces the OLD behaviour exactly, including
    # its failure mode: a KMeans initialisation dominated by vix_level's raw
    # scale can leave a state with no observations, which hmmlearn reports
    # only later and unhelpfully, as "transmat_ rows must sum to 1 (got nan)"
    # out of predict_proba. That is itself a finding worth printing, not a
    # reason for this script to crash.
    before_line: str
    before_label: Regime | None = None
    before_scalar: float | None = None
    try:
        before, before_signatures = _unscaled_fit(matrix)
        before_line = f"  before (raw fit)      {np.round(before, 3).tolist()}"
        before_label, before_scalar = _label_and_scalar(before, before_signatures, matrix)
    except Exception as exc:  # noqa: BLE001 - report the old code's own failure, don't hide it
        before_line = f"  before (raw fit)      COULD NOT FIT: {exc!r}"

    after_model = HMMRegimeModel(n_states=_N_STATES)
    after_model.fit(matrix)
    after = np.asarray(after_model.predict_proba(matrix)[-1])
    after_label, after_scalar = _label_and_scalar(after, after_model.state_signatures, matrix)

    print("\nfinal-bar posterior")
    print(before_line)
    print(f"  after  (standardised) {np.round(after, 3).tolist()}")

    print("\nfinal-bar LABEL + EXPOSURE SCALAR (fusion path, each arm's own state_signatures)")
    if before_label is not None and before_scalar is not None:
        print(f"  before (raw fit)      label={before_label.value:<10} scalar={before_scalar:.2f}")
    else:
        print("  before (raw fit)      N/A - raw fit did not succeed, see above")
    print(f"  after  (standardised) label={after_label.value:<10} scalar={after_scalar:.2f}")

    print(
        "\n⚠️ STATE INDICES ARE NOT COMPARABLE ACROSS FITS - hmmlearn numbers states\n"
        "   arbitrarily. Compare the SHAPE of the posterior and the label the fusion\n"
        "   layer derives from it, never the raw index.\n"
        "   The LABEL + SCALAR comparison above is the one that actually matters: it is\n"
        "   what the sizer consumes, and a changed label with no stated reason is not\n"
        "   an improvement."
    )


# ⚠️ GUARDED 1 September 2026. This was a bare `main()`, so `axvi_control.py` -
# which imports `_label_and_scalar` from here - re-ran this entire report, two
# HMM fits included, every time it started. Harmless to either script's numbers
# and actively confusing to read: the standardisation report interleaved with
# the control's own output, and on a failure the traceback landed in the middle
# of it. Running this file directly is unchanged.
if __name__ == "__main__":
    main()
