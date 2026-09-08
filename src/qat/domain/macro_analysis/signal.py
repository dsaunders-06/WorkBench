"""The deterministic half of the macro read (spec M13).

Computed in code from the benchmark's own daily bars before any LLM is
involved, and carried into the AI prompt as an established starting point
rather than a question. Ported in substance from the original ShareTrader
app's compute_deterministic_regime_signal
(C:\\ShareTrader\\claude_market_dashboard.py) - same three measurements and
the same classification ladder - restated here as a typed, pure function so
it can be unit-tested without a GUI, a network call, or a model.

Why these three measurements: realized volatility answers "how disorderly is
this market", trend position answers "which side of its own trend is it on",
and drawdown-from-recent-high answers "how far off the boil is it" - the
last being the one that distinguishes an orderly pullback from a market
already well into a decline while still nominally above trend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

MacroRegime = Literal["risk_on", "neutral", "caution", "risk_off"]

MACRO_REGIMES: tuple[MacroRegime, ...] = ("risk_on", "neutral", "caution", "risk_off")

MACRO_REGIME_DISPLAY: dict[str, str] = {
    "risk_on": "Risk-On",
    "neutral": "Neutral",
    "caution": "Caution",
    "risk_off": "Risk-Off",
}

# Exposure multiplier the deterministic read alone justifies. Advisory: this is
# surfaced to the operator and fed to the AI as context, and is deliberately
# NOT applied to RiskEngine.regime_scalar automatically - the HMM RegimeEngine
# owns that value, and having two independent things write the same scalar
# would make the applied exposure impossible to attribute to either.
MACRO_REGIME_EXPOSURE_HINT: dict[str, float] = {
    "risk_on": 1.0,
    "neutral": 0.85,
    "caution": 0.6,
    "risk_off": 0.3,
}

RiskMandate = Literal["conservative", "moderate", "aggressive"]

# `SB` - the RISK SCALING UNIT the 7-regime matrix scales its exposure
# shifts by. Operator definition, 8 September 2026:
#
#   "The baseline multiplier used to scale exposure shifts. Total portfolio
#    swings are dynamic and CAN EXCEED this value during extreme market stress
#    to ensure adequate downside protection."
#
# ⚠️ NOT A CAP, AND THE NAME SAYS SO NOW. An earlier version of this called it a
# "safety buffer" that "caps the maximum exposure change at +/- SB", and the
# arithmetic never kept that promise: `((RV - HV) / HV) * SB` is unbounded above
# in a BEAR regime, RECOVERY adds a flat 0.05 on top, SHOCK is a flat 0.10 and
# RECESSION halves the baseline outright. On a moderate mandate a bear market
# with RV at three times HV computes a 40% cut.
#
# That behaviour is INTENDED - a downside response that stopped at the buffer
# would under-protect in exactly the conditions it exists for - so the
# definition changed rather than the maths. `MANDATE_SAFETY_BUFFER` and
# `safety_buffer_for` were renamed with it: a constant named "buffer" re-teaches
# the misconception every time someone reads it.
#
# What SB DOES set is RESPONSIVENESS: how hard the portfolio leans into a given
# deviation from normal volatility. Higher unit, larger swing for the same
# signal.
MANDATE_SCALING_UNIT: dict[str, float] = {
    # Wealth preservation, or a highly regulated client account.
    "conservative": 0.10,
    # The balanced baseline.
    "moderate": 0.20,
    # Absolute-return mandates using heavy leverage or large cash swings.
    "aggressive": 0.35,
}


def scaling_unit_for(mandate: str) -> float:
    """The risk scaling unit `SB` for a named mandate.

    ⚠️ Raises on an unknown name rather than falling back. A default here would
    run the account on a responsiveness nobody chose and say nothing about it.
    """
    return MANDATE_SCALING_UNIT[mandate]


TermStructure = Literal["normal", "flat", "inverted"]
SpreadState = Literal["normal", "widening", "distressed"]
VolDirection = Literal["rising", "falling", "steady"]

# ⚠️ CONVENTIONAL, NOT MEASURED. An inverted curve below zero is definitional;
# the spread boundaries below are judgement calls from common usage, NOT
# validated against this account's history. Named so they can be argued with,
# and listed as open in the design spec. "The number we are using, stated out
# loud" - not "the right number".
#
# The CURVE ceiling used to be one of them and no longer is.

# How flat an upward-sloping curve must be to count as flat rather than normal.
#
# ⚠️ MEASURED, 8 September 2026, FRED readings since 2000 - and the measurement
# is that the number does not travel between markets. 0.50 is the American
# convention and sits at the 14.2nd percentile of upward-sloping `T10Y3M`
# readings: the flattest sixth of normal curves, which is a defensible warning
# band. Applied to Australia it calls 22.3% of history flat against America's
# 12.0%, because THE AUSTRALIAN TERM PREMIUM IS SIMPLY SMALLER - median +0.40
# against +1.49, and upward-sloping quartiles of +0.35/+0.70/+1.05 against
# +0.87/+1.76/+2.60.
US_CURVE_FLAT_CEILING_PCT = 0.50

# The same percentile of the Australian distribution: +0.215.
#
# ⚠️ THE READING THIS EXISTS FOR. The live Australian curve on 1 June 2026 was
# +0.371 - the FORTY-NINTH percentile of its own history, an utterly ordinary
# curve - and the American ceiling calls it flat, which in this vocabulary is a
# warning state.
#
# ⚠️ AND NAMING IT IS NOT FEEDING IT, exactly as with `^AXVI` in
# `regime_engine/feature_matrix.py`. `compute_macro_signal` still classifies
# `T10Y3M`, because the Australian rate series on FRED (IRLTLT01AUM156N,
# IR3TIB01AUM156N) are MONTHLY and were stale to 1 June when this was measured -
# 99 days old, against a matrix meant to describe today. This constant is the
# answer waiting for a daily Australian curve, not a switch to throw.
AU_CURVE_FLAT_CEILING_PCT = 0.215
# Moody's Baa over the 10-year. The live reading on 7 September 2026 was 1.57.
_SPREAD_WIDENING_PCT = 2.5
_SPREAD_DISTRESSED_PCT = 3.5
# The document's own SHOCK trigger.
_VIX_SHOCK_LEVEL = 25.0
# How much realised vol must move between adjacent windows to count as a trend
# rather than sampling noise.
_VOL_DIRECTION_TOLERANCE = 0.15


def classify_term_structure(
    slope_pct: float | None, *, ceiling_pct: float = US_CURVE_FLAT_CEILING_PCT
) -> TermStructure | None:
    """The yield curve as a state rather than a number.

    ⚠️ `None` when the series is absent, never "normal". A missing reading must
    not read as a healthy curve - that is the fabricated-all-clear shape.

    ⚠️ THE CEILING IS THE CALLER'S, because it belongs to the SERIES rather than
    to the concept. A flat curve in America is +0.50 and in Australia +0.215,
    and the constant used to be baked in here - so an Australian curve at its
    own median read as a warning. The default remains the American figure
    because `T10Y3M` remains what is actually fetched.
    """
    if slope_pct is None:
        return None
    if slope_pct < 0.0:
        return "inverted"
    if slope_pct <= ceiling_pct:
        return "flat"
    return "normal"


def classify_spreads(baa10y: float | None) -> SpreadState | None:
    """Credit spreads as a state.

    ⚠️ THIS IS WHAT SEPARATES BEAR FROM RECESSION in the 7-regime matrix - they
    differ only by "distressed spreads". Reading an absent series as calm would
    silently pick the milder of the two, so absent is `None`.
    """
    if baa10y is None:
        return None
    if baa10y >= _SPREAD_DISTRESSED_PCT:
        return "distressed"
    if baa10y >= _SPREAD_WIDENING_PCT:
        return "widening"
    return "normal"


_TRADING_DAYS_PER_YEAR = 252
_VOL_LOOKBACK_DAYS = 20

# The window `HV` is measured over - one trading year.
#
# ⚠️ A BASELINE, NOT A THRESHOLD. `_VOL_HIGH_ANNUALIZED_PCT` below is the line
# above which volatility counts as elevated; this is the level volatility
# normally sits at, which is a different question and the one the 7-regime
# matrix asks. Every formula in that matrix divides by it - see
# `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.
#
# ⚠️ MEASURED, NOT CONFIGURED. The source document supplies HV as a constant
# (15.0%). Measuring it from the same bars the rest of this signal uses keeps it
# true of THIS market rather than of whichever one the constant came from.
BASELINE_VOL_WINDOW_DAYS = 252
# ⚠️ THE BASELINE EXCLUDES THE WINDOW IT IS COMPARED AGAINST, and that is a
# correction to the first version of this rather than a refinement.
#
# Measured while building it: a fixture of one calm year (about 6% annualised)
# followed by thirty violent days read HV = 24.67%, because the spike sat inside
# the baseline window and dominated its variance. The bias always runs the same
# way - RV rises and HV rises with it - so `((RV - HV) / HV)` UNDERSTATES the
# cut exactly when a shock is under way, which is when the matrix is supposed to
# de-risk hardest. Ending the baseline where the realised window begins is what
# makes "how does now compare with normal" an honest question.
MIN_BARS_FOR_BASELINE_VOL = BASELINE_VOL_WINDOW_DAYS + _VOL_LOOKBACK_DAYS + 1
_VOL_HIGH_ANNUALIZED_PCT = 25.0
_TREND_WINDOW_DAYS = 50
_RECENT_HIGH_WINDOW_DAYS = 20
_RISK_ON_TREND_PCT = 2.0

# The trend window plus enough extra bars for the first SMA value to be a real
# average rather than a partial one.
MIN_BARS_FOR_MACRO_SIGNAL = _TREND_WINDOW_DAYS + 5


@dataclass(frozen=True, slots=True)
class MacroSignal:
    """A deterministic market-conditions read. Every field is computed, never
    modelled - this object is the same for the same bars, always."""

    realized_vol_annualized_pct: float
    # Whether realised volatility is CLIMBING or SUBSIDING - a derivative, not a
    # level. RECOVERY requires it and nothing computed it: a level alone cannot
    # tell a market coming out of a shock from one going into it.
    #
    # ⚠️ `None` when there is not enough history for two comparable windows. One
    # window is not a smaller comparison.
    vol_direction: VolDirection | None
    # The document's SHOCK trigger. ⚠️ `None`, never `False`, when VIXCLS is
    # absent: `False` claims the market was checked and found calm, which is a
    # different fact from not having looked.
    vix_shock: bool | None
    term_structure: TermStructure | None
    spreads: SpreadState | None
    # `HV` - what volatility normally is, over BASELINE_VOL_WINDOW_DAYS.
    #
    # ⚠️ OPTIONAL, AND THAT IS LOAD-BEARING. This needs 253 bars where the
    # signal itself needs 55. Making it a requirement would silently stop the
    # whole deterministic read on any market with under a year of history -
    # callers treat a `None` signal as "skip this cycle", so the cost would be
    # the entire macro read rather than one field.
    #
    # ⚠️ `None`, NEVER `0.0`. A zero baseline is not a smaller baseline: it is a
    # division by zero in every formula that consumes it, and it reads as a
    # measurement that was taken. The rule `BookRisk` already follows.
    baseline_vol_annualized_pct: float | None
    pct_above_trend: float
    drawdown_from_recent_high_pct: float
    suggested_regime: MacroRegime
    elevated_volatility: bool
    below_trend: bool
    macro_series: dict[str, float] = field(default_factory=dict)

    @property
    def display_regime(self) -> str:
        return MACRO_REGIME_DISPLAY[self.suggested_regime]

    @property
    def exposure_hint(self) -> float:
        return MACRO_REGIME_EXPOSURE_HINT[self.suggested_regime]

    def to_dict(self) -> dict[str, float | str | bool]:
        """⚠️ This is the ONLY part of the signal that reaches the model, so a
        field left out here is a field the model does not have (item 62).

        `exposure_hint` was missing, and the Regime Monitor renders it one line
        above the model's own proposed scalar - so on 27 August the operator
        read `Exposure hint 1.00` above `Proposed exposure scalar: 0.40` from a
        model that had never been shown the 1.00. Two numbers invited into
        comparison, one of them uninformed.
        """
        return {
            "realized_vol_annualized_pct": round(self.realized_vol_annualized_pct, 2),
            "pct_above_trend": round(self.pct_above_trend, 2),
            "drawdown_from_recent_high_pct": round(self.drawdown_from_recent_high_pct, 2),
            "suggested_regime": self.suggested_regime,
            "elevated_volatility": self.elevated_volatility,
            "below_trend": self.below_trend,
            "exposure_hint": self.exposure_hint,
        }

    def conditions_line(self) -> str:
        """The Phase 1 classifiers, in one line, for a human to read.

        ⚠️ THIS EXISTS BECAUSE NOTHING READ THEM. `term_structure`,
        `spreads`, `vol_direction`, `vix_shock` and `baseline_vol_annualized_pct`
        were all computed and all invisible: `summary_line` predates them, the
        matrix consults only `spreads`, and no screen showed any of it. A
        classifier nobody reads is decoration, and a threshold calibrated for a
        classifier nobody reads is decoration twice over.

        ⚠️ AN UNMEASURED INPUT SAYS SO. "not measured" rather than a healthy
        default, for the same reason `classify_term_structure` returns `None`
        instead of "normal" - a gap must not read as an all-clear.
        """
        hv = (
            f"{self.baseline_vol_annualized_pct:.1f}%"
            if self.baseline_vol_annualized_pct is not None
            else "not measured"
        )
        vix = (
            "not measured"
            if self.vix_shock is None
            else ("SHOCK" if self.vix_shock else "no shock")
        )
        return (
            f"Realised vol {self.realized_vol_annualized_pct:.1f}% against a baseline "
            f"(HV) of {hv}; volatility {self.vol_direction}; VIX {vix}; "
            f"curve {self.term_structure or 'not measured'}; "
            f"spreads {self.spreads or 'not measured'}."
        )

    def summary_line(self) -> str:
        return (
            f"{self.display_regime}: realized volatility "
            f"{self.realized_vol_annualized_pct:.1f}% annualized, "
            f"{self.pct_above_trend:+.1f}% vs its {_TREND_WINDOW_DAYS}-day average, "
            f"{self.drawdown_from_recent_high_pct:.1f}% below its "
            f"{_RECENT_HIGH_WINDOW_DAYS}-bar high."
        )


def compute_macro_signal(
    bars: pd.DataFrame,
    macro_series: dict[str, float] | None = None,
    vol_high_annualized_pct: float = _VOL_HIGH_ANNUALIZED_PCT,
) -> MacroSignal | None:
    """Returns None when there is not enough history to measure honestly.

    Returning None rather than a degraded guess is deliberate: a volatility
    figure computed from eight bars is not a less-precise version of the real
    one, it is a different and misleading number, and the callers treat None
    as "skip this cycle" rather than "assume neutral".
    """
    if bars is None or len(bars) < MIN_BARS_FOR_MACRO_SIGNAL:
        return None
    if "close" not in bars:
        return None

    close = bars["close"].astype(float)

    daily_returns = close.pct_change().dropna()
    recent_returns = daily_returns.tail(_VOL_LOOKBACK_DAYS)
    if recent_returns.empty:
        return None
    realized_vol_annualized_pct = float(recent_returns.std() * (_TRADING_DAYS_PER_YEAR**0.5) * 100)
    if pd.isna(realized_vol_annualized_pct):
        return None

    baseline_vol_annualized_pct: float | None = None
    if len(close) >= MIN_BARS_FOR_BASELINE_VOL:
        # Ends where the realised window begins - see BASELINE_VOL_WINDOW_DAYS.
        baseline_returns = daily_returns.iloc[
            -(BASELINE_VOL_WINDOW_DAYS + _VOL_LOOKBACK_DAYS) : -_VOL_LOOKBACK_DAYS
        ]
        candidate = float(baseline_returns.std() * (_TRADING_DAYS_PER_YEAR**0.5) * 100)
        # A NaN here is not a small baseline - it is no baseline, and letting it
        # through would put a nan into every formula downstream.
        if not pd.isna(candidate) and candidate > 0:
            baseline_vol_annualized_pct = candidate

    # Direction: this window against the one before it. Needs two full windows
    # plus a return, and says nothing when it cannot have them.
    vol_direction: VolDirection | None = None
    if len(daily_returns) >= _VOL_LOOKBACK_DAYS * 2:
        prior = daily_returns.iloc[-_VOL_LOOKBACK_DAYS * 2 : -_VOL_LOOKBACK_DAYS]
        prior_vol = float(prior.std() * (_TRADING_DAYS_PER_YEAR**0.5) * 100)
        if not pd.isna(prior_vol) and prior_vol > 0:
            change = (realized_vol_annualized_pct - prior_vol) / prior_vol
            if change > _VOL_DIRECTION_TOLERANCE:
                vol_direction = "rising"
            elif change < -_VOL_DIRECTION_TOLERANCE:
                vol_direction = "falling"
            else:
                vol_direction = "steady"

    series = dict(macro_series or {})
    vix = series.get("VIXCLS")
    vix_shock = None if vix is None else bool(vix > _VIX_SHOCK_LEVEL)

    trend = close.rolling(window=_TREND_WINDOW_DAYS).mean()
    latest_close = float(close.iloc[-1])
    latest_trend = float(trend.iloc[-1])
    if pd.isna(latest_trend) or latest_trend <= 0:
        return None
    pct_above_trend = (latest_close - latest_trend) / latest_trend * 100

    recent_high = float(close.tail(_RECENT_HIGH_WINDOW_DAYS).max())
    drawdown_from_recent_high_pct = (
        (recent_high - latest_close) / recent_high * 100 if recent_high > 0 else 0.0
    )

    elevated_volatility = realized_vol_annualized_pct >= vol_high_annualized_pct
    below_trend = pct_above_trend < 0

    if below_trend and elevated_volatility:
        suggested_regime: MacroRegime = "risk_off"
    elif below_trend or elevated_volatility:
        suggested_regime = "caution"
    elif pct_above_trend > _RISK_ON_TREND_PCT:
        suggested_regime = "risk_on"
    else:
        suggested_regime = "neutral"

    return MacroSignal(
        realized_vol_annualized_pct=realized_vol_annualized_pct,
        vol_direction=vol_direction,
        vix_shock=vix_shock,
        term_structure=classify_term_structure(series.get("T10Y3M")),
        spreads=classify_spreads(series.get("BAA10Y")),
        baseline_vol_annualized_pct=baseline_vol_annualized_pct,
        pct_above_trend=pct_above_trend,
        drawdown_from_recent_high_pct=drawdown_from_recent_high_pct,
        suggested_regime=suggested_regime,
        elevated_volatility=elevated_volatility,
        below_trend=below_trend,
        macro_series=series,
    )
