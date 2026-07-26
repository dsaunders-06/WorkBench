"""The deterministic macro read must be exactly that - deterministic.

These tests pin the classification ladder to constructed series rather than to
recorded numbers, so a change to the thresholds fails loudly instead of
quietly reclassifying live markets.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.domain.macro_analysis.signal import (
    MIN_BARS_FOR_MACRO_SIGNAL,
    compute_macro_signal,
)


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _steady_uptrend(n: int = 120, daily: float = 0.002) -> list[float]:
    return [100.0 * (1 + daily) ** i for i in range(n)]


def _steady_decline(n: int = 120, step: float = 0.5) -> list[float]:
    return [100.0 - step * i for i in range(n)]


def _oscillate(closes: list[float], amplitude: float = 0.03) -> list[float]:
    """Adds a large alternating shock so realized volatility is unambiguously
    elevated, without changing the underlying trend direction."""
    return [c * (1 + amplitude if i % 2 == 0 else 1 - amplitude) for i, c in enumerate(closes)]


def test_returns_none_below_the_minimum_history():
    bars = _bars(_steady_uptrend(n=MIN_BARS_FOR_MACRO_SIGNAL - 1))
    assert compute_macro_signal(bars) is None


def test_returns_a_signal_at_the_minimum_history():
    bars = _bars(_steady_uptrend(n=MIN_BARS_FOR_MACRO_SIGNAL))
    assert compute_macro_signal(bars) is not None


def test_returns_none_without_a_close_column():
    bars = pd.DataFrame({"price": _steady_uptrend()})
    assert compute_macro_signal(bars) is None


def test_calm_uptrend_reads_risk_on():
    signal = compute_macro_signal(_bars(_steady_uptrend()))
    assert signal is not None
    assert signal.suggested_regime == "risk_on"
    assert signal.below_trend is False
    assert signal.elevated_volatility is False
    assert signal.pct_above_trend > 0


def test_calm_decline_reads_caution_not_risk_off():
    """Below trend but orderly - the volatility half of the risk_off test is
    what separates a drift lower from a disorderly one."""
    signal = compute_macro_signal(_bars(_steady_decline()))
    assert signal is not None
    assert signal.below_trend is True
    assert signal.elevated_volatility is False
    assert signal.suggested_regime == "caution"


def test_volatile_uptrend_reads_caution():
    signal = compute_macro_signal(_bars(_oscillate(_steady_uptrend(n=121))))
    assert signal is not None
    assert signal.elevated_volatility is True
    assert signal.below_trend is False
    assert signal.suggested_regime == "caution"


def test_volatile_decline_reads_risk_off():
    signal = compute_macro_signal(_bars(_oscillate(_steady_decline(n=121))))
    assert signal is not None
    assert signal.below_trend is True
    assert signal.elevated_volatility is True
    assert signal.suggested_regime == "risk_off"


def test_barely_above_trend_reads_neutral_not_risk_on():
    """A shallow uptrend clears 'not below trend' but not the risk_on bar."""
    signal = compute_macro_signal(_bars(_steady_uptrend(daily=0.0002)))
    assert signal is not None
    assert signal.below_trend is False
    assert signal.elevated_volatility is False
    assert 0 < signal.pct_above_trend <= 2.0
    assert signal.suggested_regime == "neutral"


def test_drawdown_from_recent_high_is_measured():
    closes = _steady_uptrend(n=120)
    closes[-1] = closes[-1] * 0.9  # a sharp final drop below the recent high
    signal = compute_macro_signal(_bars(closes))
    assert signal is not None
    assert signal.drawdown_from_recent_high_pct > 5.0


def test_the_same_bars_always_produce_the_same_read():
    bars = _bars(_steady_uptrend())
    first = compute_macro_signal(bars)
    second = compute_macro_signal(bars)
    assert first == second


def test_macro_series_is_carried_through_untouched():
    series = {"VIXCLS": 18.4, "T10Y3M": -0.35}
    signal = compute_macro_signal(_bars(_steady_uptrend()), macro_series=series)
    assert signal is not None
    assert signal.macro_series == series


def test_vol_threshold_is_configurable():
    """The same bars either side of the threshold classify differently - proof
    the threshold is actually load-bearing rather than decorative."""
    bars = _bars(_steady_uptrend())
    calm = compute_macro_signal(bars, vol_high_annualized_pct=100.0)
    strict = compute_macro_signal(bars, vol_high_annualized_pct=0.0)
    assert calm is not None and strict is not None
    assert calm.elevated_volatility is False
    assert strict.elevated_volatility is True
    assert strict.suggested_regime == "caution"


@pytest.mark.parametrize("regime", ["risk_on", "neutral", "caution", "risk_off"])
def test_every_regime_has_a_display_name_and_exposure_hint(regime):
    from qat.domain.macro_analysis.signal import (
        MACRO_REGIME_DISPLAY,
        MACRO_REGIME_EXPOSURE_HINT,
    )

    assert regime in MACRO_REGIME_DISPLAY
    assert 0.0 < MACRO_REGIME_EXPOSURE_HINT[regime] <= 1.0
