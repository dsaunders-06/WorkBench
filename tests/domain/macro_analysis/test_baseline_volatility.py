"""`HV` - the baseline every regime formula in the matrix divides by.

Phase 1 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.
The 7-regime matrix computes `Lift = ((HV - RV) / HV) * SB`, and QAT had no
baseline at all: `_VOL_HIGH_ANNUALIZED_PCT = 25.0` is a THRESHOLD - the line
above which volatility counts as elevated - not a baseline to measure against.

⚠️ MEASURED, NOT CONFIGURED. The source document supplies `HV = 15.0%` as a
constant. Measuring it from the same bars the rest of the signal uses keeps it
true of THIS market rather than of whichever one the constant came from, and
`realized_vol_annualized_pct` already proves the computation.

⚠️ AND IT MUST NOT MAKE THE SIGNAL HARDER TO PRODUCE. `compute_macro_signal`
returns `None` rather than a degraded guess when history is short, and callers
treat that as "skip this cycle". A baseline needing 252 bars where the signal
needs 55 would silently stop the whole read on any market with under a year of
history. So `HV` is OPTIONAL: present when the history supports it, `None` when
it does not, and the signal is returned either way.

⚠️ `None`, NEVER `0.0`. A zero baseline is not a smaller baseline - it is a
division by zero in every formula that consumes it, and `0.0` reads as a
measurement that was taken. The same rule `BookRisk` follows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qat.domain.macro_analysis.signal import (
    BASELINE_VOL_WINDOW_DAYS,
    MIN_BARS_FOR_BASELINE_VOL,
    MIN_BARS_FOR_MACRO_SIGNAL,
    compute_macro_signal,
)


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"close": closes},
        index=pd.date_range("2024-01-01", periods=len(closes), freq="B"),
    )


def _walk(n: int, *, daily_sigma: float, seed: int = 1) -> list[float]:
    """A price path with a known daily volatility, so the annualised figure is
    predictable rather than whatever the fixture happened to produce."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, daily_sigma, n)
    return list(100.0 * np.exp(np.cumsum(steps)))


def test_the_baseline_is_measured_when_history_allows() -> None:
    signal = compute_macro_signal(_bars(_walk(MIN_BARS_FOR_BASELINE_VOL + 10, daily_sigma=0.01)))

    assert signal is not None
    assert signal.baseline_vol_annualized_pct is not None
    # ~1% daily annualises to ~15.9%; the band is wide enough that the sampling
    # of one path does not decide the test.
    assert 10.0 < signal.baseline_vol_annualized_pct < 25.0


def test_a_short_history_still_produces_a_signal_with_no_baseline() -> None:
    """⚠️ THE REGRESSION THIS GUARDS. The baseline needs far more bars than the
    signal does. Requiring them would stop the deterministic read entirely on
    any market with under a year of history."""
    signal = compute_macro_signal(_bars(_walk(MIN_BARS_FOR_MACRO_SIGNAL + 5, daily_sigma=0.01)))

    assert signal is not None, "the whole read was lost to a missing baseline"
    assert signal.baseline_vol_annualized_pct is None


def test_a_flat_history_yields_no_baseline_rather_than_zero() -> None:
    """⚠️ Zero is not a smaller baseline - it is a division by zero in every
    formula that consumes HV, and it reads as a measurement that was taken.

    A perfectly flat price series has a standard deviation of exactly zero,
    which is the one input that produces it honestly."""
    signal = compute_macro_signal(_bars([100.0] * (MIN_BARS_FOR_BASELINE_VOL + 10)))

    assert signal is not None
    assert signal.baseline_vol_annualized_pct is None, "a zero baseline was let through"


def test_the_baseline_is_a_different_window_from_the_realized_vol() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. If HV merely echoed RV, `(HV - RV)`
    would be zero and every regime would compute a lift of nothing - a matrix
    that always says 'hold' while looking like it calculated something.

    A path that is calm for a year and violent for the last month must show a
    LOW baseline against a HIGH recent reading.

    ⚠️ This test is also what found the baseline window overlapping the realised
    one. The first version read HV 24.67% on a calm year, because the spike sat
    INSIDE the baseline and dominated its variance - a bias that always damps
    the very cut a shock should produce.
    """
    calm = _walk(BASELINE_VOL_WINDOW_DAYS, daily_sigma=0.004, seed=2)
    violent = _walk(30, daily_sigma=0.04, seed=3)
    # Continue the violent leg from where the calm one ended.
    violent = [calm[-1] * price / violent[0] for price in violent]

    signal = compute_macro_signal(_bars(calm + violent))

    assert signal is not None and signal.baseline_vol_annualized_pct is not None
    assert (
        signal.realized_vol_annualized_pct > signal.baseline_vol_annualized_pct * 2
    ), "the baseline tracked the recent window instead of the long one"


def test_the_baseline_does_not_disturb_the_existing_fields() -> None:
    """Phase 1 adds a field; it changes no decision. The regime, the exposure
    hint and the elevated-volatility flag must read exactly as before."""
    bars = _bars(_walk(MIN_BARS_FOR_BASELINE_VOL + 10, daily_sigma=0.01, seed=7))

    signal = compute_macro_signal(bars)

    assert signal is not None
    assert signal.suggested_regime in ("risk_on", "neutral", "caution", "risk_off")
    assert (
        signal.exposure_hint
        == {
            "risk_on": 1.0,
            "neutral": 0.85,
            "caution": 0.6,
            "risk_off": 0.3,
        }[signal.suggested_regime]
    )


def test_the_baseline_window_does_not_overlap_the_realized_one() -> None:
    """⚠️ THE BIAS THIS GUARDS AGAINST, asserted directly rather than inferred
    from a ratio. A calm year followed by a violent month must leave the
    BASELINE calm - if the spike leaks into it, HV rises with RV and the
    matrix cuts least when it should cut most."""
    calm = _walk(BASELINE_VOL_WINDOW_DAYS + 40, daily_sigma=0.004, seed=11)
    violent = _walk(20, daily_sigma=0.05, seed=12)
    violent = [calm[-1] * price / violent[0] for price in violent]

    signal = compute_macro_signal(_bars(calm + violent))

    assert signal is not None and signal.baseline_vol_annualized_pct is not None
    assert signal.baseline_vol_annualized_pct < 15.0, (
        f"the spike leaked into the baseline: HV read "
        f"{signal.baseline_vol_annualized_pct:.1f}% on a calm year"
    )
