"""Milestone B's GATE, run BEFORE building any of it.

Does adding ^AXVI as a seventh feature actually change the LABEL the sizer
consumes? If it does not, the honest answer is to reject the feature and record
the numbers - not to build two data sources and a transform policy first.

Both arms are fitted with the real HMMRegimeModel (so both are standardised,
Milestone A's behaviour) and carried through the real fusion path -
RegimeFusion.compute + HysteresisGate + exposure_scalar_for - reusing
compare_standardisation.py's own helper rather than reimplementing it.

⚠️ Compared ACROSS THE WINDOW, not just on the final bar. A feature that moves
the label on one day in three hundred is not worth a sizing risk.

READ ONLY. Writes nothing.

## ⚠️ THREE DEFECTS FIXED 1 SEPTEMBER 2026, and the first invalidated the headline

1. **The HysteresisGate never engaged.** `_label_and_scalar` built a FRESH gate
   on every call, which takes the `_current_label is None` branch and returns
   the argmax, so `margin=0.15` and `min_persistence=3` did nothing. The
   docstring above claimed the real fusion path and got two thirds of it. The
   live engine builds ONE gate (`engine.py:97`) and keeps it (`engine.py:386`).
   **The 23.0% this script produced was an unsmoothed argmax.**

2. **It sliced by POSITION and refused nothing.** `z.iloc[-len(six):]` takes the
   last 300 bars of a series that grows every day, so run after the matrix was
   saved it silently ends TODAY. It printed the expected range beside the
   reconstructed one and then never compared them - an instrument that shows you
   the evidence of its own failure and reports anyway. `axvi_control.py` was
   given a date slice and a REFUSAL on 31 August; this one was not, and the note
   recording that said in as many words that this script "would be wrong run
   today".

3. **A bare `main()` at module level**, so importing anything from here ran the
   whole comparison.

⚠️ **Milestone B is REJECTED and none of this reopens it.** `axvi_control.py`
settled that with controls the same day: p = 0.30 on the full window, and on
production's gate p = 0.38. This script measures one arm against one baseline
with no control at all, and a single number from it never could have decided
anything.
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

from qat.domain.regime_engine.fusion import HysteresisGate  # noqa: E402
from qat.domain.regime_engine.hmm_core import HMMRegimeModel  # noqa: E402

_N_STATES = 4
_Z_WINDOW = 60
# The matrix carries no dates. This is what the startup log recorded for it, and
# the alignment REFUSES rather than reports if it cannot reproduce it.
_MATRIX_FIRST_DAY = "2025-06-23"
_MATRIX_LAST_DAY = "2026-08-26"


def main() -> None:
    six = np.load(ROOT / "scripts" / "research" / "regime_matrix.npy")
    print(f"saved matrix: {six.shape[0]} bars x {six.shape[1]} features")

    # Align ^AXVI to the SAME trading days the matrix was built on. The matrix
    # carries no dates, so alignment is reconstructed from STW.AX's own
    # calendar and checked against the range the startup log recorded
    # (2025-06-23 -> 2026-08-26). If the reconstruction does not land on the
    # same length and range, the comparison is not on identical days and is
    # refused rather than reported.
    # ⚠️ Align onto STW.AX's OWN calendar with a forward-fill, which is what
    # load_macro_history's as-of join does in production. Intersecting the two
    # calendars with dropna() changes the trading-day set - measured: it moved
    # the window start from 2025-06-23 to 2025-06-20 while keeping 300 bars,
    # which means rows were paired with the wrong day's ^AXVI.
    px = yf.download(
        ["STW.AX", "^AXVI"], period="4y", interval="1d", auto_adjust=True, progress=False
    )["Close"]
    stw = px["STW.AX"].dropna()
    axvi_on_stw = px["^AXVI"].reindex(stw.index).ffill()
    z = (axvi_on_stw - axvi_on_stw.rolling(_Z_WINDOW).mean()) / axvi_on_stw.rolling(_Z_WINDOW).std()
    z = z.dropna()

    if len(z) < len(six):
        print(f"REFUSED: only {len(z)} aligned ^AXVI bars for {len(six)} matrix rows")
        return

    # ⚠️ SLICE BY DATE, NEVER BY POSITION. `z.iloc[-300:]` takes the last 300
    # bars of a series that grows every day, so run after the matrix was saved
    # it silently ends TODAY. This script printed the expected range beside the
    # reconstructed one and then compared nothing - it would have shown you the
    # evidence of its own failure and reported the number anyway.
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

    seven = np.column_stack([six, z_tail.to_numpy(dtype=float)])

    labels = {}
    for name, matrix in (("six (today)", six), ("seven (+^AXVI z)", seven)):
        model = HMMRegimeModel(n_states=_N_STATES)
        model.fit(matrix)
        posteriors = model.predict_proba(matrix)
        sigs = model.state_signatures
        # The fusion path needs vix_level and yield_curve_slope off each row;
        # _label_and_scalar reads them from the matrix it is given, so pass the
        # SIX-column matrix for both arms - those two columns are identical in
        # both and this keeps the only difference the HMM itself.
        # ⚠️ ONE GATE for the arm, carried across the bars in order, because that
        # is what RegimeEngine does. A fresh gate per bar - what this script did
        # until 1 September - returns the argmax and never engages margin=0.15
        # or min_persistence=3. Each ARM gets its own gate: sharing one between
        # the six- and seven-column arms would let one arm's history decide the
        # other's labels.
        gate = HysteresisGate()
        out = []
        for i in range(len(matrix)):
            lbl, sc = _label_and_scalar(posteriors[i], sigs, six[: i + 1], gate)
            out.append((lbl, sc))
        labels[name] = out
        print(f"{name:<20} final: label={out[-1][0].value:<10} scalar={out[-1][1]:.2f}")

    a = labels["six (today)"]
    b = labels["seven (+^AXVI z)"]
    differ = [i for i in range(len(a)) if a[i][0] != b[i][0]]
    scalar_differ = [i for i in range(len(a)) if abs(a[i][1] - b[i][1]) > 1e-9]

    print(
        f"\nbars where the LABEL differs   : {len(differ)} of {len(a)} "
        f"({100*len(differ)/len(a):.1f}%)"
    )
    print(
        f"bars where the SCALAR differs  : {len(scalar_differ)} of {len(a)} "
        f"({100*len(scalar_differ)/len(a):.1f}%)"
    )

    if differ:
        print("\nfirst few differences (bar index: six -> seven):")
        for i in differ[:8]:
            print(
                f"   {i:>4}: {a[i][0].value:<10} ({a[i][1]:.2f})  ->  "
                f"{b[i][0].value:<10} ({b[i][1]:.2f})"
            )
    else:
        print("\n⚠️ THE LABEL NEVER MOVES. On this window ^AXVI adds nothing the six")
        print("   existing features do not already carry. The honest answer is to")
        print("   REJECT the feature and record these numbers.")


# ⚠️ GUARDED 1 September 2026. This was a bare `main()`, so importing anything
# from here ran the whole comparison as a side effect.
if __name__ == "__main__":
    main()
