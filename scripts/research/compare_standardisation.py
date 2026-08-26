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
    model = GaussianHMM(n_components=_N_STATES, covariance_type="diag", random_state=0, n_iter=100)
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

    # The unstandardised arm reproduces the OLD behaviour exactly, including
    # its failure mode: a KMeans initialisation dominated by vix_level's raw
    # scale can leave a state with no observations, which hmmlearn reports
    # only later and unhelpfully, as "transmat_ rows must sum to 1 (got nan)"
    # out of predict_proba. That is itself a finding worth printing, not a
    # reason for this script to crash.
    before_line: str
    try:
        before = _unscaled_posterior(matrix)
        before_line = f"  before (raw fit)      {np.round(before, 3).tolist()}"
    except Exception as exc:  # noqa: BLE001 - report the old code's own failure, don't hide it
        before_line = f"  before (raw fit)      COULD NOT FIT: {exc!r}"

    after_model = HMMRegimeModel(n_states=_N_STATES)
    after_model.fit(matrix)
    after = np.asarray(after_model.predict_proba(matrix)[-1])

    print("\nfinal-bar posterior")
    print(before_line)
    print(f"  after  (standardised) {np.round(after, 3).tolist()}")
    print(
        "\n⚠️ STATE INDICES ARE NOT COMPARABLE ACROSS FITS - hmmlearn numbers states\n"
        "   arbitrarily. Compare the SHAPE of the posterior and the label the fusion\n"
        "   layer derives from it, never the raw index."
    )


main()
