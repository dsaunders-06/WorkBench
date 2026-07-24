from __future__ import annotations

import pytest

from qat.domain.risk_engine.sizing import KellyVolTargetSizer


def test_takes_the_minimum_of_kelly_and_cap():
    sizer = KellyVolTargetSizer(kelly_fraction=0.5, risk_fraction=0.01, atr_stop_multiple=2.5)
    equity, price, atr = 100_000.0, 50.0, 2.0

    shares = sizer.size(equity, price, atr, win_rate=0.9, win_loss_ratio=3.0)

    cap_shares = (0.01 * equity) / (2.5 * atr)
    assert shares == cap_shares


def test_weak_edge_produces_smaller_kelly_shares_than_cap():
    sizer = KellyVolTargetSizer(kelly_fraction=0.5, risk_fraction=0.5, atr_stop_multiple=2.5)
    equity, price, atr = 100_000.0, 50.0, 2.0

    shares = sizer.size(equity, price, atr, win_rate=0.55, win_loss_ratio=1.5)

    kelly_f = 0.5 * (0.55 - 0.45 / 1.5)
    expected_kelly_shares = (kelly_f * equity) / price
    assert shares == pytest.approx(expected_kelly_shares)


def test_no_edge_returns_zero():
    sizer = KellyVolTargetSizer(kelly_fraction=0.5, risk_fraction=0.01, atr_stop_multiple=2.5)
    assert sizer.size(100_000.0, 50.0, 2.0, win_rate=0.3, win_loss_ratio=1.0) == 0.0


def test_zero_equity_returns_zero():
    sizer = KellyVolTargetSizer()
    assert sizer.size(0.0, 50.0, 2.0, win_rate=0.6, win_loss_ratio=2.0) == 0.0


def test_zero_atr_returns_zero():
    sizer = KellyVolTargetSizer()
    assert sizer.size(100_000.0, 50.0, 0.0, win_rate=0.6, win_loss_ratio=2.0) == 0.0
