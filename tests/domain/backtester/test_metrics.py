from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from qat.domain.backtester.metrics import (
    compute_alpha,
    compute_beta,
    compute_cagr,
    compute_calmar,
    compute_information_ratio,
    compute_max_drawdown,
    compute_metrics_panel,
    compute_profit_factor,
    compute_sharpe,
    compute_sortino,
    compute_var_parametric,
    compute_win_rate,
)
from qat.domain.backtester.results import Trade


def _dates(n: int) -> pd.DatetimeIndex:
    start = datetime(2020, 1, 1)
    return pd.DatetimeIndex([start + timedelta(days=i) for i in range(n)])


def test_cagr_doubling_over_one_year():
    dates = pd.DatetimeIndex([datetime(2020, 1, 1), datetime(2021, 1, 1)])
    equity = pd.Series([100.0, 200.0], index=dates)
    assert compute_cagr(equity) == pytest.approx(1.0, rel=0.01)


def test_cagr_flat_equity_is_zero():
    dates = pd.DatetimeIndex([datetime(2020, 1, 1), datetime(2021, 1, 1)])
    equity = pd.Series([100.0, 100.0], index=dates)
    assert compute_cagr(equity) == pytest.approx(0.0)


def test_sharpe_zero_vol_returns_zero():
    assert compute_sharpe(pd.Series([0.0, 0.0, 0.0])) == 0.0


def test_sharpe_matches_hand_computation():
    returns = pd.Series([0.01, -0.005, 0.02, 0.0, -0.01])
    expected_vol = returns.std() * (252**0.5)
    expected_sharpe = (returns.mean() * 252) / expected_vol
    assert compute_sharpe(returns) == pytest.approx(expected_sharpe)


def test_sortino_zero_when_no_downside_observations():
    no_downside = pd.Series([0.01, 0.05, 0.01, 0.08, 0.01])
    assert compute_sortino(no_downside) == 0.0


def test_sortino_nonzero_with_downside():
    with_downside = pd.Series([0.01, -0.05, 0.01, -0.08, 0.01])
    assert compute_sortino(with_downside) != 0.0


def test_sortino_with_single_downside_observation_is_zero_not_nan():
    # std() over a single observation is undefined (NaN) - must not leak into the result
    returns = pd.Series([0.01, 0.02, -0.03, 0.01, 0.02])
    result = compute_sortino(returns)
    assert result == 0.0
    assert not pd.isna(result)


def test_max_drawdown_on_known_path():
    equity = pd.Series([100.0, 120.0, 90.0, 95.0, 130.0])
    assert compute_max_drawdown(equity) == pytest.approx((90.0 - 120.0) / 120.0)


def test_calmar_uses_cagr_over_abs_max_drawdown():
    assert compute_calmar(0.20, -0.10) == pytest.approx(2.0)
    assert compute_calmar(0.20, 0.0) == 0.0


def test_beta_of_series_against_itself_is_one():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
    assert compute_beta(returns, returns) == pytest.approx(1.0)


def test_alpha_is_zero_when_strategy_equals_benchmark():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
    assert compute_alpha(returns, returns) == pytest.approx(0.0, abs=1e-9)


def test_information_ratio_is_zero_when_no_active_return():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
    assert compute_information_ratio(returns, returns) == 0.0


def test_win_rate_and_profit_factor():
    trades = [
        Trade(
            symbol="AAA",
            side="buy",
            entry_ts=datetime(2020, 1, 1),
            exit_ts=datetime(2020, 1, 2),
            entry_price=100.0,
            exit_price=110.0,
            quantity=1.0,
            pnl=10.0,
        ),
        Trade(
            symbol="AAA",
            side="buy",
            entry_ts=datetime(2020, 1, 3),
            exit_ts=datetime(2020, 1, 4),
            entry_price=100.0,
            exit_price=95.0,
            quantity=1.0,
            pnl=-5.0,
        ),
        Trade(
            symbol="AAA",
            side="buy",
            entry_ts=datetime(2020, 1, 5),
            exit_ts=datetime(2020, 1, 6),
            entry_price=100.0,
            exit_price=105.0,
            quantity=1.0,
            pnl=5.0,
        ),
    ]
    assert compute_win_rate(trades) == pytest.approx(2 / 3)
    assert compute_profit_factor(trades) == pytest.approx(15.0 / 5.0)


def test_profit_factor_with_no_losses_is_infinite():
    trades = [
        Trade(
            symbol="AAA",
            side="buy",
            entry_ts=datetime(2020, 1, 1),
            exit_ts=datetime(2020, 1, 2),
            entry_price=100.0,
            exit_price=110.0,
            quantity=1.0,
            pnl=10.0,
        )
    ]
    assert compute_profit_factor(trades) == float("inf")


def test_var_parametric_matches_z_score_formula():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
    assert compute_var_parametric(returns, 0.95) == pytest.approx(1.65 * returns.std())


def test_var_parametric_rejects_unsupported_confidence():
    returns = pd.Series([0.01, -0.02, 0.03])
    with pytest.raises(ValueError):
        compute_var_parametric(returns, 0.90)


def test_metrics_panel_includes_benchmark_relative_metrics_when_provided():
    dates = _dates(30)
    equity = pd.Series([100.0 * (1.001**i) for i in range(30)], index=dates)
    benchmark = pd.Series([100.0 * (1.0005**i) for i in range(30)], index=dates)
    panel = compute_metrics_panel(equity, [], benchmark)
    assert {"beta", "alpha", "information_ratio"} <= panel.keys()


def test_metrics_panel_without_benchmark_omits_relative_metrics():
    dates = _dates(30)
    equity = pd.Series([100.0 * (1.001**i) for i in range(30)], index=dates)
    panel = compute_metrics_panel(equity, [])
    assert "beta" not in panel
