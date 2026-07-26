"""Performance metrics from realised trades (spec M16).

Deliberately plain arithmetic on closed round-trips. No model is involved in
producing a single number here - the AI's role in reporting is to narrate
figures that were already computed, never to compute or estimate them.

Every metric returns None rather than a placeholder when the input is too thin
to support it. A Sharpe ratio from three trades is not a rough Sharpe ratio, it
is noise wearing a number's clothes, and a promotion gate that accepts it will
promote noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev

from qat.domain.performance.trades import ClosedTrade, EquityPoint

# Below this, per-trade statistics are not reported at all.
MIN_TRADES_FOR_STATS = 5
_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PerformanceStats:
    trade_count: int
    win_count: int
    loss_count: int
    total_pnl: float
    win_rate: float | None
    average_win: float | None
    average_loss: float | None
    profit_factor: float | None
    expectancy: float | None
    average_r: float | None
    r_trade_count: int
    best_trade: float | None
    worst_trade: float | None

    @property
    def has_enough_history(self) -> bool:
        return self.trade_count >= MIN_TRADES_FOR_STATS

    def summary_line(self) -> str:
        if not self.trade_count:
            return "No closed trades yet."
        parts = [f"{self.trade_count} closed trade(s)", f"net ${self.total_pnl:,.2f}"]
        if self.win_rate is not None:
            parts.append(f"{self.win_rate:.0%} win rate")
        if self.average_r is not None:
            parts.append(f"avg {self.average_r:+.2f}R over {self.r_trade_count} stopped trades")
        if self.profit_factor is not None:
            parts.append(f"profit factor {self.profit_factor:.2f}")
        return ", ".join(parts) + "."


def compute_stats(trades: list[ClosedTrade]) -> PerformanceStats:
    if not trades:
        return PerformanceStats(
            trade_count=0,
            win_count=0,
            loss_count=0,
            total_pnl=0.0,
            win_rate=None,
            average_win=None,
            average_loss=None,
            profit_factor=None,
            expectancy=None,
            average_r=None,
            r_trade_count=0,
            best_trade=None,
            worst_trade=None,
        )

    pnls = [trade.pnl for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    # Only trades with a known stop have an R. Counting the others as 0R would
    # drag the mean toward zero for a reason that has nothing to do with
    # performance.
    r_values = [trade.r_multiple for trade in trades if trade.r_multiple is not None]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    enough = len(trades) >= MIN_TRADES_FOR_STATS

    return PerformanceStats(
        trade_count=len(trades),
        win_count=len(wins),
        loss_count=len(losses),
        total_pnl=sum(pnls),
        win_rate=(len(wins) / len(trades)) if enough else None,
        average_win=fmean(wins) if wins else None,
        average_loss=fmean(losses) if losses else None,
        # Infinite profit factor is not a real result - a strategy with no
        # losses yet simply has not had one.
        profit_factor=(gross_profit / gross_loss) if (enough and gross_loss > 0) else None,
        expectancy=fmean(pnls) if enough else None,
        average_r=fmean(r_values) if (enough and r_values) else None,
        r_trade_count=len(r_values),
        best_trade=max(pnls),
        worst_trade=min(pnls),
    )


def max_drawdown(points: list[EquityPoint]) -> float:
    """Largest peak-to-trough fall in the equity curve, as a positive fraction."""
    if len(points) < 2:
        return 0.0
    peak = points[0].equity
    worst = 0.0
    for point in points:
        peak = max(peak, point.equity)
        if peak > 0:
            worst = max(worst, (peak - point.equity) / peak)
    return worst


def equity_returns(points: list[EquityPoint]) -> list[float]:
    returns = []
    for previous, current in zip(points, points[1:], strict=False):
        if previous.equity > 0:
            returns.append((current.equity - previous.equity) / previous.equity)
    return returns


def sharpe_ratio(
    points: list[EquityPoint], periods_per_year: int = _TRADING_DAYS_PER_YEAR
) -> float | None:
    """Annualised Sharpe on the equity curve, or None when unmeasurable.

    Returns None on a flat curve rather than dividing by a zero standard
    deviation - and None, not infinity, because "no variance yet" is an absence
    of evidence rather than a perfect risk-adjusted return.
    """
    returns = equity_returns(points)
    if len(returns) < MIN_TRADES_FOR_STATS:
        return None
    deviation = pstdev(returns)
    if deviation <= 0:
        return None
    return (fmean(returns) / deviation) * math.sqrt(periods_per_year)
