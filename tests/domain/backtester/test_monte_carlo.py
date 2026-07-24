from __future__ import annotations

from datetime import datetime, timedelta

from qat.domain.backtester.monte_carlo import run_monte_carlo
from qat.domain.backtester.results import Trade


def _trades(pnls: list[float]) -> list[Trade]:
    return [
        Trade(
            symbol="AAA",
            side="buy",
            entry_ts=datetime(2020, 1, 1) + timedelta(days=i),
            exit_ts=datetime(2020, 1, 2) + timedelta(days=i),
            entry_price=100.0,
            exit_price=100.0 + pnl,
            quantity=1.0,
            pnl=pnl,
        )
        for i, pnl in enumerate(pnls)
    ]


def test_same_seed_is_deterministic():
    trades = _trades([100.0, -50.0, 80.0, -30.0, 60.0])

    result_a = run_monte_carlo(trades, starting_equity=10_000.0, n_simulations=200, seed=1)
    result_b = run_monte_carlo(trades, starting_equity=10_000.0, n_simulations=200, seed=1)

    assert result_a.final_equity_p50 == result_b.final_equity_p50
    assert result_a.paths.equals(result_b.paths)


def test_percentiles_are_ordered():
    trades = _trades([100.0, -50.0, 80.0, -30.0, 60.0, -70.0, 40.0])

    result = run_monte_carlo(trades, starting_equity=10_000.0, n_simulations=500, seed=2)

    assert result.final_equity_p5 <= result.final_equity_p50 <= result.final_equity_p95
    assert result.max_drawdown_p5 <= result.max_drawdown_p50 <= result.max_drawdown_p95


def test_no_trades_returns_flat_result():
    result = run_monte_carlo([], starting_equity=10_000.0)

    assert result.final_equity_p5 == 10_000.0
    assert result.final_equity_p50 == 10_000.0
    assert result.final_equity_p95 == 10_000.0
    assert result.max_drawdown_p50 == 0.0


def test_paths_dataframe_has_one_column_per_simulation():
    trades = _trades([10.0, -5.0])

    result = run_monte_carlo(trades, starting_equity=10_000.0, n_simulations=25, seed=3)

    assert result.paths.shape[1] == 25
