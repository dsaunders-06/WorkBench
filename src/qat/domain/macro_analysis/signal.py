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

_TRADING_DAYS_PER_YEAR = 252
_VOL_LOOKBACK_DAYS = 20
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
        return {
            "realized_vol_annualized_pct": round(self.realized_vol_annualized_pct, 2),
            "pct_above_trend": round(self.pct_above_trend, 2),
            "drawdown_from_recent_high_pct": round(self.drawdown_from_recent_high_pct, 2),
            "suggested_regime": self.suggested_regime,
            "elevated_volatility": self.elevated_volatility,
            "below_trend": self.below_trend,
        }

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
        pct_above_trend=pct_above_trend,
        drawdown_from_recent_high_pct=drawdown_from_recent_high_pct,
        suggested_regime=suggested_regime,
        elevated_volatility=elevated_volatility,
        below_trend=below_trend,
        macro_series=dict(macro_series or {}),
    )
