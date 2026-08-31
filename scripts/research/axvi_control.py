r"""Is ^AXVI's effect the FEATURE, or just a seventh column? Run the control.

    .\.venv\Scripts\python.exe scripts\research\axvi_control.py

READ ONLY. Writes nothing.

## The question this exists to settle

`compare_axvi_feature.py` measured that adding ^AXVI's z-score moves the regime
label on **23.0% of bars, always toward more defensive**. That number is now
marked SUSPECT and must not be quoted again until re-taken - and the plan itself
names the reason:

> The matrix already carries `realized_vol` and `vix_level`. Adding `asx_vix_z`
> makes **three of seven columns volatility measures**, and under
> `covariance_type="diag"` the model treats columns as independent - so
> correlated columns double-count. A systematic shift toward defensive labels is
> exactly what that would look like.

So the 23% has two possible causes and the original run cannot separate them:

* **SIGNAL** - ^AXVI carries Australian volatility information the six-column
  matrix lacks; or
* **ARTEFACT** - a seventh column of roughly the right shape perturbs a
  four-state HMM by about that much no matter what is in it.

## The control

Three arms beyond the baseline, all seven columns wide, differing only in what
the seventh column contains:

* **real**      - ^AXVI's z-score, aligned as production would align it
* **shuffled**  - the SAME values, permuted. Identical distribution, identical
  mean and variance, **time structure destroyed**. If this moves the label as
  much as `real`, the 23% is not information.
* **noise**     - Gaussian matched to ^AXVI's mean and standard deviation. A
  second control with the same moments but not even the same values.

Several permutations per control, because one lucky shuffle proves nothing.

⚠️ **This is Milestone C's lesson applied before the build, not after.** There,
four ablation results were worthless because both arms were identical and
"NOT EXERCISED" was truthful about the arms and meaningless about the feature. A
control is what caught it. One extra arm here can reject a feature before two
data sources and a transform policy are built for it.

⚠️ **AND THE METHOD WARNING FROM THE ORIGINAL GATE APPLIES.** A three-day
calendar slip once understated this effect NINEFOLD - 2.7% against a true 23.0%
- because `dropna()` on the intersection of two calendars changed the
trading-day set while keeping the row count. ^AXVI is aligned onto STW.AX's own
calendar with a forward-fill, which is what `load_macro_history`'s as-of join
does in production, and the date range is PRINTED so it can be checked against
the startup log before any number here is believed.
"""

import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import yfinance as yf  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from compare_standardisation import _label_and_scalar  # noqa: E402

from qat.domain.regime_engine.hmm_core import HMMRegimeModel  # noqa: E402

_N_STATES = 4
_Z_WINDOW = 60
_TRIALS = 30
_SEED = 20260831
# The matrix carries no dates. This is what the startup log recorded for it, and
# the alignment below REFUSES rather than reports if it cannot reproduce it.
_MATRIX_FIRST_DAY = "2025-06-23"
_MATRIX_LAST_DAY = "2026-08-26"


def _labels_for(matrix: np.ndarray, six: np.ndarray) -> list[str]:
    """Fit an arm and carry it through the real fusion path, bar by bar."""
    model = HMMRegimeModel(n_states=_N_STATES)
    model.fit(matrix)
    posteriors = model.predict_proba(matrix)
    sigs = model.state_signatures
    out = []
    for i in range(len(matrix)):
        # The six-column matrix for the fusion path in EVERY arm: those columns
        # are identical across arms, so the only difference is the HMM itself.
        label, _ = _label_and_scalar(posteriors[i], sigs, six[: i + 1])
        out.append(label.value)
    return out


def _pct_moved(baseline: list[str], arm: list[str]) -> float:
    return 100.0 * sum(1 for a, b in zip(baseline, arm, strict=True) if a != b) / len(baseline)


def main() -> None:
    six = np.load(ROOT / "scripts" / "research" / "regime_matrix.npy")
    print(f"saved matrix: {six.shape[0]} bars x {six.shape[1]} features")

    px = yf.download(
        ["STW.AX", "^AXVI"], period="4y", interval="1d", auto_adjust=True, progress=False
    )["Close"]
    stw = px["STW.AX"].dropna()
    axvi = px["^AXVI"].reindex(stw.index).ffill()
    z = (axvi - axvi.rolling(_Z_WINDOW).mean()) / axvi.rolling(_Z_WINDOW).std()
    z = z.dropna()

    if len(z) < len(six):
        print(f"REFUSED: only {len(z)} aligned ^AXVI bars for {len(six)} matrix rows")
        return

    # ⚠️ SLICE BY DATE, NEVER BY POSITION. `z.iloc[-300:]` takes the last 300
    # bars of a series that grows every day, so run after the matrix was saved it
    # silently ends TODAY rather than on the matrix's last day. Measured
    # 31 August: it aligned 2025-06-26 -> 2026-08-31 against a matrix ending
    # 2026-08-26 - a three-trading-day offset, which is the SAME failure as the
    # original calendar slip in a new form, and exactly what the printed guard
    # below exists to catch.
    z = z[z.index <= _MATRIX_LAST_DAY]
    z_tail = z.iloc[-len(six) :]
    first, last = str(z_tail.index[0].date()), str(z_tail.index[-1].date())
    print(f"^AXVI aligned : {len(z_tail)} bars, {first} -> {last}")
    print(f"   startup log recorded the matrix as {_MATRIX_FIRST_DAY} -> {_MATRIX_LAST_DAY}")
    if first != _MATRIX_FIRST_DAY or last != _MATRIX_LAST_DAY:
        print("\n   ⚠️ REFUSED: the reconstructed range does not match the log, so the")
        print("      arms are NOT on the same days and every number below would be")
        print("      measured on misaligned rows - the ninefold-understatement")
        print("      failure. Fix the alignment; do not read past this line.")
        return
    print()

    column = z_tail.to_numpy(dtype=float)
    baseline = _labels_for(six, six)

    real = _pct_moved(baseline, _labels_for(np.column_stack([six, column]), six))

    rng = np.random.default_rng(_SEED)
    shuffled = [
        _pct_moved(baseline, _labels_for(np.column_stack([six, rng.permutation(column)]), six))
        for _ in range(_TRIALS)
    ]
    noise = [
        _pct_moved(
            baseline,
            _labels_for(
                np.column_stack([six, rng.normal(column.mean(), column.std(), size=len(column))]),
                six,
            ),
        )
        for _ in range(_TRIALS)
    ]

    print(f"{'arm':<34}{'label moved':>14}")
    print("-" * 48)
    print(f"{'real ^AXVI z-score':<34}{real:>13.1f}%")
    print(
        f"{'shuffled (same values, no time)':<34}"
        f"{np.median(shuffled):>13.1f}%   [{min(shuffled):.1f} - {max(shuffled):.1f}]"
    )
    print(
        f"{'gaussian noise (same moments)':<34}"
        f"{np.median(noise):>13.1f}%   [{min(noise):.1f} - {max(noise):.1f}]"
    )

    # ⚠️ The comparison that matters is NOT median against median. The controls
    # span a wide range, so the question is how often a MEANINGLESS column moves
    # the label at least as much as the real one - an empirical p-value.
    #
    # The HMM fit is deterministic (`random_state=0` passed to GaussianHMM), so
    # this spread is the seventh column's CONTENT and not fit noise. That is what
    # makes the controls interpretable at all.
    controls = shuffled + noise
    at_least = sum(1 for value in controls if value >= real - 1e-9)
    print(
        f"\ncontrols reaching the real arm : {at_least} of {len(controls)} "
        f"({100.0 * at_least / len(controls):.0f}%)"
    )

    print(
        "\n⚠️ HOW TO READ THIS, decided before the numbers were seen:\n"
        "   If `real` is NOT clearly above BOTH controls, the 23% was the model\n"
        "   reacting to a seventh column rather than to Australian volatility -\n"
        "   and Milestone B should be REJECTED rather than built. The plan's own\n"
        "   worry is that three of seven columns become volatility measures under\n"
        "   covariance_type='diag', and that is exactly what the controls test.\n"
        "\n   ⚠️ ONE WINDOW ONLY. Milestone C showed every column except vix_level\n"
        "   swings three- to fourfold with the window, so a single window settles\n"
        "   the SIGNAL-vs-ARTEFACT question and nothing about stability."
    )


if __name__ == "__main__":
    main()
