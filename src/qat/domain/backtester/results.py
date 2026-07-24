"""Backtest result types (spec §G)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    side: Literal["buy", "sell"]  # the entry direction
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    equity_curve: pd.Series  # indexed by ts
    trades: list[Trade]
    metrics: dict[str, float]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    in_sample_start: datetime
    in_sample_end: datetime
    out_sample_start: datetime
    out_sample_end: datetime
    out_sample_result: BacktestResult


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    metric_stability: dict[str, float]  # e.g. {"sharpe_mean": ..., "sharpe_std": ...}


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    final_equity_p5: float
    final_equity_p50: float
    final_equity_p95: float
    max_drawdown_p5: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    paths: pd.DataFrame  # one simulated equity path per column, for the Workbench cone chart
