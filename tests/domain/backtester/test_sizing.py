from __future__ import annotations

from qat.config import Settings
from qat.domain.backtester.sizing import FixedFractionalSizer


def test_matches_appendix_a_formula():
    sizer = FixedFractionalSizer(risk_fraction=0.01, atr_stop_multiple=2.5)
    equity, price, atr = 100_000.0, 50.0, 2.0

    shares = sizer.size(equity, price, atr)

    assert shares == (0.01 * equity) / (2.5 * atr)


def test_defaults_come_from_settings_when_not_overridden():
    settings = Settings(_env_file=None)
    sizer = FixedFractionalSizer(settings=settings)

    assert sizer.risk_fraction == settings.per_trade_risk_pct
    assert sizer.atr_stop_multiple == settings.atr_stop_multiple


def test_zero_atr_returns_zero_shares():
    sizer = FixedFractionalSizer(risk_fraction=0.01, atr_stop_multiple=2.5)
    assert sizer.size(100_000.0, 50.0, 0.0) == 0.0


def test_zero_equity_returns_zero_shares():
    sizer = FixedFractionalSizer(risk_fraction=0.01, atr_stop_multiple=2.5)
    assert sizer.size(0.0, 50.0, 2.0) == 0.0
