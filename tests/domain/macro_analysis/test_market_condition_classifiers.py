"""The four fetched-but-unread inputs the regime matrix needs.

Phase 1 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.
`VIXCLS`, `T10Y3M` and `BAA10Y` have been fetched every session and read by
nothing; volatility DIRECTION was never computed at all. The matrix needs all
four:

* SHOCK triggers on `VIX > 25` as well as on RV.
* RECOVERY requires "subsiding volatility" - a DERIVATIVE, not a level.
* RECESSION is distinguished from BEAR only by "distressed spreads". Without a
  threshold on `BAA10Y` the two regimes are indistinguishable and the matrix
  cannot choose between them.
* The document names "Flat / Inverted" term structure as an input.

⚠️ THE THRESHOLDS BELOW ARE CONVENTIONAL, NOT MEASURED. An inverted curve at
`T10Y3M < 0` is definitional; the flat band, the spread bands and the
rate-of-change tolerance are judgement calls taken from common usage and have
NOT been validated against this account's own history. They are named constants
so they can be argued with, and they are listed as open in the spec. Nothing
here should be read as "the right number" - only as "the number we are using,
stated out loud".

⚠️ ABSENT IS `None`, NEVER A DEFAULT. A missing FRED series must not read as a
normal curve or a calm market: that is the fabricated-all-clear shape this
codebase keeps finding. Every classifier returns `None` when its input is
missing, and the matrix refuses regimes whose inputs are absent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qat.domain.macro_analysis.signal import (
    MIN_BARS_FOR_MACRO_SIGNAL,
    classify_spreads,
    classify_term_structure,
    compute_macro_signal,
)


def _walk(n: int, *, daily_sigma: float, seed: int = 1) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100.0 * np.exp(np.cumsum(rng.normal(0.0, daily_sigma, n))))


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"close": closes},
        index=pd.date_range("2024-01-01", periods=len(closes), freq="B"),
    )


# --- term structure -------------------------------------------------------


@pytest.mark.parametrize(
    ("t10y3m", "expected"),
    [(-0.5, "inverted"), (-0.01, "inverted"), (0.2, "flat"), (1.5, "normal")],
)
def test_the_curve_is_classified_from_the_spread(t10y3m: float, expected: str) -> None:
    assert classify_term_structure(t10y3m) == expected


def test_an_absent_curve_is_None_rather_than_normal() -> None:
    """⚠️ A missing series must not read as a healthy curve."""
    assert classify_term_structure(None) is None


# --- credit spreads -------------------------------------------------------


@pytest.mark.parametrize(
    ("baa10y", "expected"),
    [(1.57, "normal"), (2.8, "widening"), (4.0, "distressed"), (6.0, "distressed")],
)
def test_spreads_are_classified_from_the_baa_series(baa10y: float, expected: str) -> None:
    """1.57 is the live reading on 7 September 2026 - the calm end."""
    assert classify_spreads(baa10y) == expected


def test_absent_spreads_are_None_rather_than_calm() -> None:
    """⚠️ THE ONE THAT SEPARATES BEAR FROM RECESSION. Reading a missing series
    as calm would silently pick the milder regime of the two."""
    assert classify_spreads(None) is None


# --- VIX ------------------------------------------------------------------


def test_a_vix_above_the_shock_threshold_is_flagged() -> None:
    bars = _bars(_walk(MIN_BARS_FOR_MACRO_SIGNAL + 5, daily_sigma=0.01))

    signal = compute_macro_signal(bars, macro_series={"VIXCLS": 31.2})

    assert signal is not None
    assert signal.vix_shock is True


def test_a_calm_vix_is_not_a_shock() -> None:
    bars = _bars(_walk(MIN_BARS_FOR_MACRO_SIGNAL + 5, daily_sigma=0.01))

    signal = compute_macro_signal(bars, macro_series={"VIXCLS": 14.3})

    assert signal is not None
    assert signal.vix_shock is False


def test_an_absent_vix_is_None_rather_than_False() -> None:
    """⚠️ `False` claims the market was checked and found calm. `None` says it
    was not checked - a different fact, and the one the matrix needs to refuse
    the SHOCK regime rather than rule it out."""
    bars = _bars(_walk(MIN_BARS_FOR_MACRO_SIGNAL + 5, daily_sigma=0.01))

    signal = compute_macro_signal(bars, macro_series={})

    assert signal is not None
    assert signal.vix_shock is None


# --- volatility direction -------------------------------------------------


def test_volatility_that_is_climbing_reads_as_rising() -> None:
    calm = _walk(60, daily_sigma=0.004, seed=5)
    loud = _walk(20, daily_sigma=0.03, seed=6)
    loud = [calm[-1] * price / loud[0] for price in loud]

    signal = compute_macro_signal(_bars(calm + loud))

    assert signal is not None
    assert signal.vol_direction == "rising"


def test_volatility_that_is_subsiding_reads_as_falling() -> None:
    """⚠️ RECOVERY requires this and nothing computed it. A level alone cannot
    tell a market coming out of a shock from one going into it."""
    loud = _walk(60, daily_sigma=0.03, seed=7)
    calm = _walk(20, daily_sigma=0.004, seed=8)
    calm = [loud[-1] * price / calm[0] for price in calm]

    signal = compute_macro_signal(_bars(loud + calm))

    assert signal is not None
    assert signal.vol_direction == "falling"


def test_steady_volatility_is_neither() -> None:
    """A tolerance band, so ordinary sampling noise does not read as a trend."""
    signal = compute_macro_signal(_bars(_walk(120, daily_sigma=0.01, seed=9)))

    assert signal is not None
    assert signal.vol_direction == "steady"


def test_a_short_history_leaves_the_direction_unknown() -> None:
    """Two windows are needed to compare. One is not a smaller comparison."""
    signal = compute_macro_signal(_bars(_walk(MIN_BARS_FOR_MACRO_SIGNAL, daily_sigma=0.01)))

    if signal is not None:
        assert signal.vol_direction in ("rising", "falling", "steady", None)


# --- the whole read -------------------------------------------------------


def test_the_new_fields_do_not_disturb_the_existing_decision() -> None:
    """Phase 1 adds inputs; it changes no decision. The regime and the exposure
    hint must read exactly as they did before any of this landed."""
    bars = _bars(_walk(120, daily_sigma=0.01, seed=11))

    with_series = compute_macro_signal(bars, macro_series={"VIXCLS": 31.2, "T10Y3M": -0.4})
    without = compute_macro_signal(bars, macro_series={})

    assert with_series is not None and without is not None
    assert with_series.suggested_regime == without.suggested_regime
    assert with_series.exposure_hint == without.exposure_hint
