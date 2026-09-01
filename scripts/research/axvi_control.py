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

import inspect
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import yfinance as yf  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from compare_standardisation import _fused_probs, _label_and_scalar  # noqa: E402

from qat.domain.regime_engine.fusion import HysteresisGate  # noqa: E402
from qat.domain.regime_engine.hmm_core import HMMRegimeModel  # noqa: E402
from qat.domain.strategies.engine import StrategyEngine  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402

# ⚠️ READ off StrategyEngine rather than restated as 0.5. A threshold copied
# into a research script is a threshold that silently stops matching production
# the first time somebody tunes it, and this whole exercise exists because a
# harness had quietly stopped matching production.
_ELIGIBILITY_MASS: float = (
    inspect.signature(StrategyEngine.__init__).parameters["regime_eligibility_mass"].default
)

_N_STATES = 4
_Z_WINDOW = 60
_TRIALS = 30
_SEED = 20260831
# The matrix carries no dates. This is what the startup log recorded for it, and
# the alignment below REFUSES rather than reports if it cannot reproduce it.
_MATRIX_FIRST_DAY = "2025-06-23"
_MATRIX_LAST_DAY = "2026-08-26"


def _labels_for(matrix: np.ndarray, six: np.ndarray, one_gate: bool = False) -> list[str]:
    """Fit an arm and carry it through the real fusion path, bar by bar.

    ⚠️ `one_gate` DECIDES WHICH LABEL IS BEING MEASURED, and the default is the
    one production does NOT use.

    * `one_gate=False` - a fresh `HysteresisGate` per bar, so `update()` takes
      the `_current_label is None` branch and returns the argmax. `margin=0.15`
      and `min_persistence=3` never engage. **This is what every figure before
      1 September 2026 was taken on**, and it is kept as the default so those
      figures stay reproducible.
    * `one_gate=True` - ONE gate carried across the bars in order, which is what
      `RegimeEngine` does (`engine.py:97` builds it, `engine.py:386` updates it).
      A challenger must beat the incumbent by 0.15 for three consecutive bars.

    Each call builds its OWN gate. Sharing one between the baseline and an arm
    would let the baseline's history decide the arm's labels, which is not a
    control, it is a leak.
    """
    model = HMMRegimeModel(n_states=_N_STATES)
    model.fit(matrix)
    posteriors = model.predict_proba(matrix)
    sigs = model.state_signatures
    gate = HysteresisGate() if one_gate else None
    out = []
    for i in range(len(matrix)):
        # The six-column matrix for the fusion path in EVERY arm: those columns
        # are identical across arms, so the only difference is the HMM itself.
        label, _ = _label_and_scalar(posteriors[i], sigs, six[: i + 1], gate)
        out.append(label.value)
    return out


def _eligibility_for(matrix: np.ndarray, six: np.ndarray) -> list[bool]:
    """Whether `swing` would be ADMITTED to trade, bar by bar.

    ⚠️ THE OTHER CONSUMER, and nothing smooths it. `StrategyEngine.is_eligible`
    sums the fused distribution over the strategy's suitable regimes and admits
    at `>= regime_eligibility_mass` (0.5) - `strategies/engine.py:232-256`. The
    hysteresis gate is not in that path at all, so there is no `one_gate`
    parameter here and there must not be one: a gate mode would be measuring
    something this decision never reads.

    ⚠️ And the cost of being wrong here is BINARY, where the label's is graded.
    A wrong label sizes a position at 0.7 instead of 1.0; a wrong admission
    means the only promoted strategy in the system does not trade at all.

    `swing.suitable_regimes()` is read from the strategy rather than restated,
    so a change there cannot leave this measuring the old set.
    """
    model = HMMRegimeModel(n_states=_N_STATES)
    model.fit(matrix)
    posteriors = model.predict_proba(matrix)
    sigs = model.state_signatures
    suitable = SwingStrategy().suitable_regimes()
    out = []
    for i in range(len(matrix)):
        probs = _fused_probs(posteriors[i], sigs, six[: i + 1])
        # ⚠️ REFUSE rather than report zero. `RegimeFusion.compute` keys on the
        # Regime enum; `StrategyEngine._eligible_mass` keys on `regime.value`
        # because it reads an event's already-stringified dict. Get that wrong
        # here and every `.get` misses, mass is 0.0 on every bar, and uniform
        # INELIGIBILITY reads as a finding instead of as a broken lookup.
        if i == 0:
            missing = [r for r in suitable if r not in probs]
            if missing:
                raise KeyError(
                    f"fused probs are not keyed by Regime - {missing} absent from "
                    f"{sorted(str(k) for k in probs)}. Every mass would be 0.0 and "
                    "this arm would report total ineligibility as a result."
                )
        mass = sum(probs.get(regime, 0.0) for regime in suitable)
        out.append(mass >= _ELIGIBILITY_MASS)
    return out


def _pct_moved(baseline: list[str], arm: list[str]) -> float:
    return 100.0 * sum(1 for a, b in zip(baseline, arm, strict=True) if a != b) / len(baseline)


def _pct_flipped(baseline: list[bool], arm: list[bool]) -> float:
    return 100.0 * sum(1 for a, b in zip(baseline, arm, strict=True) if a != b) / len(baseline)


def _transitions(labels: list[str]) -> int:
    """How many times the label CHANGES down the series.

    ⚠️ This is the rail-bite check, not decoration. If carrying one gate across
    the bars produced the same transition count as a fresh gate per bar, the
    gate would not be engaging and every number below it would be measuring the
    same thing twice under two names. Print it, do not assume it.
    """
    # `labels[:-1]` rather than `labels`: zipping a list against its own tail
    # under strict=True is a guaranteed ValueError, because the two can never be
    # the same length. Caught on the first run.
    return sum(1 for a, b in zip(labels[:-1], labels[1:], strict=True) if a != b)


def _run_eligibility(six: np.ndarray, column: np.ndarray) -> None:
    """Task 2 - the ADMISSION path, which no gate smooths.

    Same three arms, same seed, same window. The only change is what is read off
    each bar: `swing` admitted or not, instead of the sticky label.
    """
    rule = f"mass >= {_ELIGIBILITY_MASS}, NO smoothing"
    print(f"\n{'=' * 62}\nELIGIBILITY of `swing` ({rule})\n{'=' * 62}")

    baseline = _eligibility_for(six, six)
    eligible_share = 100.0 * sum(baseline) / len(baseline)
    flips = _transitions([str(b) for b in baseline])
    print(f"baseline eligible on         : {eligible_share:.1f}% of bars")
    print(f"baseline admission flips     : {flips} over {len(baseline)} bars")
    print()

    real = _pct_flipped(baseline, _eligibility_for(np.column_stack([six, column]), six))

    rng = np.random.default_rng(_SEED)
    shuffled = [
        _pct_flipped(
            baseline, _eligibility_for(np.column_stack([six, rng.permutation(column)]), six)
        )
        for _ in range(_TRIALS)
    ]
    noise = [
        _pct_flipped(
            baseline,
            _eligibility_for(
                np.column_stack([six, rng.normal(column.mean(), column.std(), size=len(column))]),
                six,
            ),
        )
        for _ in range(_TRIALS)
    ]

    print(f"{'arm':<34}{'admission flipped':>20}")
    print("-" * 54)
    print(f"{'real ^AXVI z-score':<34}{real:>19.1f}%")
    print(
        f"{'shuffled (same values, no time)':<34}"
        f"{np.median(shuffled):>19.1f}%   [{min(shuffled):.1f} - {max(shuffled):.1f}]"
    )
    print(
        f"{'gaussian noise (same moments)':<34}"
        f"{np.median(noise):>19.1f}%   [{min(noise):.1f} - {max(noise):.1f}]"
    )
    controls = shuffled + noise
    at_least = sum(1 for value in controls if value >= real - 1e-9)
    print(
        f"\ncontrols reaching the real arm : {at_least} of {len(controls)} "
        f"({100.0 * at_least / len(controls):.0f}%)"
    )
    print(
        "\n⚠️ HOW TO READ THIS BLOCK, decided BEFORE running it:\n"
        "   Compare the control MEDIAN and MAXIMUM here against the ONE-GATE\n"
        "   label block above (median 11.8%, max 85.3%).\n"
        "   * If admission flips MATERIALLY MORE than the smoothed label, the\n"
        "     exposure is in strategy ADMISSION rather than in sizing, and any\n"
        "     future work belongs there rather than on the label.\n"
        "   * If it flips comparably or less, one number covers both and the\n"
        "     label figures already describe the risk.\n"
        "   ⚠️ Admission is BINARY - a flip means the only promoted strategy in\n"
        "   the system does not trade, where a label flip only resizes."
    )


def _run_arms(six: np.ndarray, column: np.ndarray, one_gate: bool) -> None:
    """One full control, under one gate discipline.

    ⚠️ THE RNG IS RE-SEEDED PER MODE, deliberately. Both modes must see the
    SAME thirty permutations and the same thirty noise draws, or the difference
    between them confounds the gate with a different set of random columns -
    which is the one thing this comparison exists to isolate.
    """
    heading = (
        "ONE GATE across bars (what RegimeEngine does)"
        if one_gate
        else ("FRESH gate per bar (every figure before 1 Sep 2026)")
    )
    print(f"\n{'=' * 62}\n{heading}\n{'=' * 62}")

    baseline = _labels_for(six, six, one_gate)
    real = _pct_moved(baseline, _labels_for(np.column_stack([six, column]), six, one_gate))

    rng = np.random.default_rng(_SEED)
    shuffled = [
        _pct_moved(
            baseline, _labels_for(np.column_stack([six, rng.permutation(column)]), six, one_gate)
        )
        for _ in range(_TRIALS)
    ]
    noise = [
        _pct_moved(
            baseline,
            _labels_for(
                np.column_stack([six, rng.normal(column.mean(), column.std(), size=len(column))]),
                six,
                one_gate,
            ),
        )
        for _ in range(_TRIALS)
    ]

    print(f"baseline label transitions : {_transitions(baseline)} over {len(baseline)} bars")
    print()
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

    for one_gate in (False, True):
        _run_arms(six, column, one_gate)

    _run_eligibility(six, column)

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
    print(
        "\n⚠️ AND HOW TO READ THE TWO BLOCKS, decided 1 September BEFORE running:\n"
        "   The FRESH-gate block is the control on this change, not a result. It\n"
        "   must reproduce the 31 August figures - real 23.0%, both controls\n"
        "   17.3% median, 18 of 60 reaching the real arm. If it does not, the\n"
        "   edit broke the instrument and NOTHING in the ONE-GATE block means\n"
        "   anything.\n"
        "\n   Then, on the ONE-GATE block only:\n"
        "   * If the control SPREAD collapses to a narrow band, '0% to 85.3%'\n"
        "     was a property of a per-bar gate, not of the HMM, and the finding\n"
        "     must be RE-RECORDED at its true size - not quietly dropped.\n"
        "   * If the spread survives, the finding stands as written and bears\n"
        "     directly on position sizing.\n"
        "\n   ⚠️ Neither outcome reopens Milestone B. Every arm is treated\n"
        "   identically within a block, so the between-arm comparison that gave\n"
        "   p = 0.30 is untouched either way."
    )


if __name__ == "__main__":
    main()
