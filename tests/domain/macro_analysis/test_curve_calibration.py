"""The flat-curve ceiling was borrowed from a market this account does not trade.

`_CURVE_FLAT_CEILING_PCT` was 0.5, and its own comment said what it was:
*"CONVENTIONAL, NOT MEASURED... a judgement call from common usage, NOT
validated against this account's history."* Spec open question 8 listed it. It
is now measured, and the measurement says the borrowed number does not travel.

**Measured 8 September 2026, FRED, readings since 2000.**

| | US `T10Y3M` | AU 10y - 3m |
|---|---|---|
| median (all) | +1.49 | +0.40 |
| median (upward-sloping) | +1.76 | +0.70 |
| upward-sloping quartiles | +0.87 / +1.76 / +2.60 | +0.35 / +0.70 / +1.05 |
| share the 0.50 ceiling calls flat | 12.0% | 22.3% |

⚠️ **THE AUSTRALIAN TERM PREMIUM IS SIMPLY SMALLER.** An AU curve at +0.371 -
the live reading on 1 June 2026 - sits at the FORTY-NINTH percentile of its own
history. It is an utterly ordinary Australian curve, and the US-calibrated
ceiling calls it flat, which in this vocabulary is a warning state. Nearly a
quarter of Australian history would read as a warning.

Translated by percentile instead: 0.50 is the 14.2nd percentile of
upward-sloping US curves, and the same percentile of the Australian
distribution is **+0.215**. That is the calibrated Australian ceiling.

⚠️ **AND NAMING IT IS NOT FEEDING IT**, the same shape as `^AXVI`. The series
actually classified is `T10Y3M`, the US curve, because the Australian rate
series on FRED are MONTHLY and were stale to 1 June when this was measured -
99 days, against a matrix that wants to describe today. The ceiling is now
chosen by the CALLER for the series it holds, so the calibration is a decision
rather than a constant, and the Australian figure is recorded for the day a
daily Australian curve exists.
"""

from __future__ import annotations

from qat.domain.macro_analysis.signal import (
    AU_CURVE_FLAT_CEILING_PCT,
    US_CURVE_FLAT_CEILING_PCT,
    classify_term_structure,
)


def test_the_us_ceiling_is_the_one_measured() -> None:
    assert US_CURVE_FLAT_CEILING_PCT == 0.50


def test_the_australian_ceiling_is_less_than_half_the_american_one() -> None:
    """⚠️ THE FINDING. Not a tweak - the Australian term premium is smaller
    enough that the borrowed number changes the answer across a quarter of
    Australian history."""
    assert AU_CURVE_FLAT_CEILING_PCT == 0.215
    assert AU_CURVE_FLAT_CEILING_PCT < US_CURVE_FLAT_CEILING_PCT / 2


def test_an_ordinary_australian_curve_is_not_flat_under_the_australian_ceiling() -> None:
    """+0.371 was the live AU reading on 1 June 2026 and sits at the 49th
    percentile of Australian history - the middle of the distribution."""
    assert classify_term_structure(0.371, ceiling_pct=AU_CURVE_FLAT_CEILING_PCT) == "normal"


def test_that_same_curve_reads_flat_under_the_american_ceiling() -> None:
    """⚠️ The defect, pinned. Delete the parameter and this is what the matrix
    goes back to saying about an ordinary Australian curve."""
    assert classify_term_structure(0.371, ceiling_pct=US_CURVE_FLAT_CEILING_PCT) == "flat"


def test_the_default_is_still_the_series_that_is_actually_fed() -> None:
    """⚠️ Unchanged on purpose. `T10Y3M` is what `compute_macro_signal` reads,
    because the Australian series on FRED are monthly and were 99 days stale
    when this was measured. Swapping the default without a daily Australian
    curve would calibrate a number nothing supplies."""
    assert classify_term_structure(0.371) == "flat"


def test_an_inverted_curve_is_inverted_under_either_calibration() -> None:
    """Below zero is definitional, not conventional - the one boundary here
    that was never a judgement call."""
    for ceiling in (US_CURVE_FLAT_CEILING_PCT, AU_CURVE_FLAT_CEILING_PCT):
        assert classify_term_structure(-0.10, ceiling_pct=ceiling) == "inverted"


def test_a_missing_reading_is_still_never_healthy() -> None:
    assert classify_term_structure(None, ceiling_pct=AU_CURVE_FLAT_CEILING_PCT) is None


def test_the_boundary_itself_counts_as_flat() -> None:
    """Which side the boundary falls on is a choice, and an untested one drifts."""
    assert classify_term_structure(0.215, ceiling_pct=AU_CURVE_FLAT_CEILING_PCT) == "flat"
    assert classify_term_structure(0.216, ceiling_pct=AU_CURVE_FLAT_CEILING_PCT) == "normal"


def _signal(**overrides):
    from qat.domain.macro_analysis.signal import MacroSignal

    payload = {
        "realized_vol_annualized_pct": 8.74,
        "vol_direction": "steady",
        "vix_shock": False,
        "term_structure": "flat",
        "spreads": "normal",
        "baseline_vol_annualized_pct": 15.0,
        "pct_above_trend": 1.0,
        "drawdown_from_recent_high_pct": 1.0,
        "suggested_regime": "neutral",
        "elevated_volatility": False,
        "below_trend": False,
    }
    payload.update(overrides)
    return MacroSignal(**payload)


def test_the_conditions_line_carries_every_phase_one_classifier() -> None:
    """⚠️ THE OTHER HALF OF THIS ITEM. Calibrating a threshold for a classifier
    nothing reads is decoration twice over - `term_structure` was computed and
    consumed by no screen, no prompt and no rule in the matrix."""
    line = _signal().conditions_line()

    assert "curve flat" in line
    assert "spreads normal" in line
    assert "volatility steady" in line
    assert "VIX no shock" in line
    assert "15.0%" in line, "the baseline every matrix formula divides by is not shown"


def test_an_unmeasured_input_says_so_rather_than_reading_as_healthy() -> None:
    """⚠️ The fabricated-all-clear shape. A blank where the curve should be
    reads as a normal curve to anyone glancing at the panel."""
    line = _signal(
        term_structure=None, spreads=None, baseline_vol_annualized_pct=None
    ).conditions_line()

    assert "curve not measured" in line
    assert "spreads not measured" in line
    assert "baseline (HV) of not measured" in line
    assert "normal" not in line
