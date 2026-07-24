"""Monte-Carlo trade-sequence resampling: bootstrap the realised trade
returns to produce a P5-P50-P95 outcome cone (spec §G, shown in the
Workbench). "P5" consistently means the pessimistic tail for each metric -
the lowest final equity and the deepest (most negative) drawdown.
"""

from __future__ import annotations

import random

import pandas as pd

from qat.domain.backtester.results import MonteCarloResult, Trade


def run_monte_carlo(
    trades: list[Trade],
    starting_equity: float,
    n_simulations: int = 1000,
    seed: int = 0,
) -> MonteCarloResult:
    trade_returns = [t.pnl / starting_equity for t in trades]

    if not trade_returns:
        flat = pd.DataFrame({"path_0": [starting_equity]})
        return MonteCarloResult(
            final_equity_p5=starting_equity,
            final_equity_p50=starting_equity,
            final_equity_p95=starting_equity,
            max_drawdown_p5=0.0,
            max_drawdown_p50=0.0,
            max_drawdown_p95=0.0,
            paths=flat,
        )

    rng = random.Random(seed)  # nosec B311 - deterministic simulation seed, not crypto
    n_trades = len(trade_returns)
    final_equities: list[float] = []
    max_drawdowns: list[float] = []
    path_columns: dict[str, list[float]] = {}

    for sim in range(n_simulations):
        equity = starting_equity
        path = [equity]
        peak = equity
        max_dd = 0.0
        for _ in range(n_trades):
            equity *= 1.0 + rng.choice(trade_returns)
            path.append(equity)
            peak = max(peak, equity)
            if peak > 0:
                max_dd = min(max_dd, (equity - peak) / peak)
        final_equities.append(equity)
        max_drawdowns.append(max_dd)
        path_columns[f"path_{sim}"] = path

    final_series = pd.Series(final_equities)
    dd_series = pd.Series(max_drawdowns)

    return MonteCarloResult(
        final_equity_p5=float(final_series.quantile(0.05)),
        final_equity_p50=float(final_series.quantile(0.50)),
        final_equity_p95=float(final_series.quantile(0.95)),
        max_drawdown_p5=float(dd_series.quantile(0.05)),
        max_drawdown_p50=float(dd_series.quantile(0.50)),
        max_drawdown_p95=float(dd_series.quantile(0.95)),
        paths=pd.DataFrame(path_columns),
    )
