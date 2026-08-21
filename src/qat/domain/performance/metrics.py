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

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean, pstdev

from qat.domain.performance.trades import ClosedTrade, EquityPoint

logger = logging.getLogger(__name__)

# Below this, per-trade statistics are not reported at all.
MIN_TRADES_FOR_STATS = 5
# A rate needs elapsed time as well as a count. Below a day of trading history
# a weekly figure is an extrapolation from noise.
MIN_SPAN_DAYS_FOR_RATE = 1.0
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
    # What the trading cost, and what share of the gross result it took (M28).
    # Subtracting costs without showing them answers "how did we do" while
    # hiding the one lever that is fully under the operator's control:
    # trade less often, or trade bigger.
    total_costs: float = 0.0
    gross_pnl: float = 0.0

    @property
    def cost_drag(self) -> float | None:
        """Costs as a share of the gross result.

        None when gross is not positive - there is no meaningful ratio between
        a fee and a loss, and reporting one invites the wrong conclusion.
        """
        if self.gross_pnl <= 0:
            return None
        return self.total_costs / self.gross_pnl

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
        if self.total_costs > 0:
            drag = self.cost_drag
            parts.append(
                f"costs ${self.total_costs:,.2f}"
                + (f" ({drag:.0%} of gross)" if drag is not None else "")
            )
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
            total_costs=0.0,
            gross_pnl=0.0,
        )

    # M122. Every figure below is a SUM or a mean over net_pnl, which is only
    # meaningful if every row is in one currency. The ledger carried no
    # currency until M122, so a total could silently add USD to AUD and read
    # as a number. Said once, loudly, rather than returning a plausible lie -
    # and not raised, because a report that crashes on a mixed file tells the
    # operator less than one that computes and warns.
    currencies = {trade.currency for trade in trades if trade.currency is not None}
    if len(currencies) > 1:
        logger.error(
            "MIXED-CURRENCY TOTALS: %d closed trades span %s. Every money figure "
            "below adds them together and is therefore meaningless. Scope the "
            "trades to one market before reading these numbers.",
            len(trades),
            ", ".join(sorted(currencies)),
        )

    # Net, every one of them (M28). Expectancy, profit factor and average R
    # are what the promotion gate reads, and a gross figure would promote a
    # strategy on money the account never kept.
    pnls = [trade.net_pnl for trade in trades]
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
        total_costs=sum(trade.costs for trade in trades),
        gross_pnl=sum(trade.gross_pnl for trade in trades),
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


# --- trade shape (spec M23) ---------------------------------------------------
#
# Everything below derives from data already on disk. The point of the group is
# that a return figure alone does not describe a strategy: two systems with the
# same net P&L, one holding for hours at 90% invested and the other for weeks at
# 5%, are not the same system and should not be compared as though they were.


def average_holding_period(trades: list[ClosedTrade]) -> timedelta | None:
    """Mean time from entry to exit across closed round-trips.

    Load-bearing here rather than merely interesting: the autonomy rails are
    session-phase aware and the daily-loss rail resets each morning. A strategy
    holding for hours meets those rails constantly; one holding for weeks
    barely notices them. Without this figure there is no way to tell which of
    those two systems is running.
    """
    if len(trades) < MIN_TRADES_FOR_STATS:
        return None
    spans = [
        (trade.closed_at - trade.opened_at).total_seconds()
        for trade in trades
        if trade.closed_at >= trade.opened_at
    ]
    if not spans:
        return None
    return timedelta(seconds=fmean(spans))


def trades_per_week(trades: list[ClosedTrade]) -> float | None:
    """Closed trades per calendar week over the period actually traded.

    Measured against elapsed time rather than a count, so a burst of activity
    in one afternoon does not read the same as steady daily turnover. Mostly a
    diagnostic during testing: it is the number that answers "is the system
    doing anything at all", which the abstention rules made a real question.
    """
    if len(trades) < MIN_TRADES_FOR_STATS:
        return None
    closes = sorted(trade.closed_at for trade in trades)
    span_days = (closes[-1] - closes[0]).total_seconds() / 86_400.0
    # A weekly rate extrapolated from minutes is arithmetic, not measurement:
    # eight trades closed seconds apart divides out to hundreds of millions per
    # week. Guarding only against a zero span let that through.
    if span_days < MIN_SPAN_DAYS_FOR_RATE:
        return None
    return len(trades) / (span_days / 7.0)


def recovery_factor(trades: list[ClosedTrade], points: list[EquityPoint]) -> float | None:
    """Net profit divided by the worst drawdown that produced it.

    Preferred to Calmar on short samples because it does not annualise: a
    fortnight of paper trading annualised is a number with no meaning, whereas
    "made three times what it risked losing at the worst point" survives a
    small sample intact.
    """
    if len(trades) < MIN_TRADES_FOR_STATS:
        return None
    drawdown = max_drawdown(points)
    if drawdown <= 0:
        return None
    peak_equity = max((point.equity for point in points), default=0.0)
    if peak_equity <= 0:
        return None
    net = sum(trade.net_pnl for trade in trades)
    return net / (drawdown * peak_equity)


def average_exposure(points: list[EquityPoint]) -> float | None:
    """Mean share of equity held in positions rather than cash.

    The missing denominator under every return figure the app shows: two
    percent on ten percent deployed and two percent on ninety-five percent
    deployed are different results. Also the direct read on whether the
    no-leverage cash rule is throttling the strategy - a system that wants more
    exposure than the rule permits will sit pinned near its ceiling.
    """
    ratios = _exposure_ratios(points)
    return fmean(ratios) if ratios else None


def peak_exposure(points: list[EquityPoint]) -> float | None:
    ratios = _exposure_ratios(points)
    return max(ratios) if ratios else None


def _exposure_ratios(points: list[EquityPoint]) -> list[float]:
    # Clamped at zero: a cash balance above equity is arithmetically possible
    # mid-settlement and means "nothing invested", not negative exposure.
    return [
        max(0.0, (point.equity - point.cash) / point.equity) for point in points if point.equity > 0
    ]
