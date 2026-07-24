"""The ten-metric panel plus volatility and parametric VaR (spec §G, paper §5
and Appendix A). Every formula here is the paper's Appendix A formula,
applied to daily returns/equity and annualised where the formula calls for it.
"""

from __future__ import annotations

import pandas as pd

from qat.domain.backtester.results import Trade

_TRADING_DAYS_PER_YEAR = 252
_VAR_Z_SCORES = {0.95: 1.65, 0.99: 2.33}


def compute_cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25
    if years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def compute_volatility(returns: pd.Series, periods_per_year: int = _TRADING_DAYS_PER_YEAR) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * (periods_per_year**0.5))


def compute_sharpe(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> float:
    if len(returns) < 2:
        return 0.0
    annualized_vol = compute_volatility(returns, periods_per_year)
    if annualized_vol == 0:
        return 0.0
    annualized_return = float(returns.mean() * periods_per_year)
    return (annualized_return - risk_free_rate) / annualized_vol


def compute_sortino(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> float:
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0  # std() is undefined (NaN) for fewer than 2 observations
    downside_vol = float(downside.std() * (periods_per_year**0.5))
    if downside_vol == 0 or pd.isna(downside_vol):
        return 0.0
    annualized_return = float(returns.mean() * periods_per_year)
    return (annualized_return - risk_free_rate) / downside_vol


def compute_max_drawdown(equity: pd.Series) -> float:
    """Negative fraction (e.g. -0.15 for a 15% drawdown); 0.0 if never below the running peak."""
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min())


def compute_calmar(cagr: float, max_drawdown: float) -> float:
    if max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)


def compute_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return 0.0
    variance = aligned.iloc[:, 1].var()
    if variance == 0:
        return 0.0
    covariance = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
    return float(covariance / variance)


def compute_alpha(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> float:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return 0.0
    beta = compute_beta(aligned.iloc[:, 0], aligned.iloc[:, 1])
    strategy_annual = float(aligned.iloc[:, 0].mean() * periods_per_year)
    benchmark_annual = float(aligned.iloc[:, 1].mean() * periods_per_year)
    return strategy_annual - (risk_free_rate + beta * (benchmark_annual - risk_free_rate))


def compute_information_ratio(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> float:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return 0.0
    active_returns = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    tracking_error = float(active_returns.std() * (periods_per_year**0.5))
    if tracking_error == 0:
        return 0.0
    active_annual = float(active_returns.mean() * periods_per_year)
    return active_annual / tracking_error


def compute_win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def compute_profit_factor(trades: list[Trade]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_var_parametric(returns: pd.Series, confidence: float = 0.95) -> float:
    """One-period parametric VaR as a positive fraction of equity: z_alpha * sigma
    (Appendix A). Only the paper's two named confidence levels are supported."""
    if len(returns) < 2:
        return 0.0
    if confidence not in _VAR_Z_SCORES:
        raise ValueError(
            f"Unsupported confidence {confidence}; use 0.95 or 0.99 (paper Appendix A)"
        )
    return _VAR_Z_SCORES[confidence] * float(returns.std())


def compute_metrics_panel(
    equity_curve: pd.Series,
    trades: list[Trade],
    benchmark_prices: pd.Series | None = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> dict[str, float]:
    returns = equity_curve.pct_change().dropna()
    cagr = compute_cagr(equity_curve)
    max_dd = compute_max_drawdown(equity_curve)

    panel = {
        "cagr": cagr,
        "volatility": compute_volatility(returns, periods_per_year),
        "sharpe": compute_sharpe(returns, risk_free_rate, periods_per_year),
        "sortino": compute_sortino(returns, risk_free_rate, periods_per_year),
        "max_drawdown": max_dd,
        "calmar": compute_calmar(cagr, max_dd),
        "win_rate": compute_win_rate(trades),
        "profit_factor": compute_profit_factor(trades),
        "var_95": compute_var_parametric(returns, 0.95),
    }

    if benchmark_prices is not None:
        benchmark_returns = benchmark_prices.pct_change().dropna()
        panel["beta"] = compute_beta(returns, benchmark_returns)
        panel["alpha"] = compute_alpha(returns, benchmark_returns, risk_free_rate, periods_per_year)
        panel["information_ratio"] = compute_information_ratio(
            returns, benchmark_returns, periods_per_year
        )

    return panel
