"""One assembled view of realised performance (spec M23).

PerformanceStats already carried expectancy, average win, average loss and the
best and worst trade, and summary_line() dropped every one of them - so the
single most decision-relevant figure a trading system has, expected dollars per
trade, was computed on every refresh and thrown away. Win rate without it is
not just incomplete but misleading: eighty percent winners at a negative
expectancy is a losing system that feels like a winning one.

This module gathers those figures with the trade-shape and exposure metrics
into one structure, so the screen, the reports and any future export all read
the same numbers from the same place rather than each assembling their own.

Every field is optional and every one respects MIN_TRADES_FOR_STATS. A metric
computed from three trades is not an approximate metric; it is noise with a
decimal point, and the promotion gate that accepts it will promote noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from qat.domain.performance.metrics import (
    PerformanceStats,
    average_exposure,
    average_holding_period,
    compute_stats,
    max_drawdown,
    peak_exposure,
    recovery_factor,
    sharpe_ratio,
    trades_per_week,
)
from qat.domain.performance.trades import ClosedTrade, EquityPoint


def format_duration(span: timedelta | None) -> str:
    """Human units, chosen by magnitude - "0.04 days" tells nobody anything."""
    if span is None:
        return "-"
    seconds = span.total_seconds()
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5_400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172_800:
        return f"{seconds / 3_600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    stats: PerformanceStats
    max_drawdown_pct: float
    sharpe: float | None
    holding_period: timedelta | None
    trades_per_week: float | None
    recovery_factor: float | None
    average_exposure: float | None
    peak_exposure: float | None

    @property
    def win_loss_ratio(self) -> float | None:
        """Average win over average loss. Read beside the win rate or not at
        all: either number alone can describe both a good system and a bad one.
        """
        win, loss = self.stats.average_win, self.stats.average_loss
        if win is None or not loss:
            return None
        return win / abs(loss)

    def rows(self) -> list[tuple[str, str, str]]:
        """(label, value, why it matters) for display, in priority order."""
        stats = self.stats
        return [
            ("Trades", str(stats.trade_count), "Closed round-trips on record."),
            (
                "Net P&L",
                f"${stats.total_pnl:,.2f}",
                "Realised profit and loss across every closed trade.",
            ),
            (
                "Expectancy",
                _money(stats.expectancy),
                "Expected profit per trade. The number the system IS - a high win "
                "rate with a negative expectancy is a losing system that feels good.",
            ),
            (
                "Win rate",
                _percent(stats.win_rate),
                "Share of closed trades that made money. Meaningless without "
                "expectancy beside it.",
            ),
            (
                "Avg win / avg loss",
                _ratio(self.win_loss_ratio),
                "How much a winner makes against what a loser costs. The promotion "
                "gate already judges on this; until now you could not see it.",
            ),
            ("Average win", _money(stats.average_win), "Mean profit on winning trades."),
            ("Average loss", _money(stats.average_loss), "Mean loss on losing trades."),
            (
                "Best / worst",
                _pair(stats.best_trade, stats.worst_trade),
                "Largest single outcomes.",
            ),
            (
                "Average R",
                _signed(stats.average_r),
                f"Outcome per unit of risk taken, over the {stats.r_trade_count} trade(s) "
                "that had a measurable stop.",
            ),
            (
                "Profit factor",
                _ratio(stats.profit_factor),
                "Gross profit over gross loss. Above 1.0 is a system that made money.",
            ),
            (
                "Holding period",
                format_duration(self.holding_period),
                "Mean time from entry to exit. Decides whether the session and "
                "daily-loss rails bind constantly or barely at all.",
            ),
            (
                "Trades / week",
                _number(self.trades_per_week),
                "Turnover over the period actually traded - the read on whether the "
                "system is doing anything.",
            ),
            (
                "Avg exposure",
                _percent(self.average_exposure),
                "Share of equity held in positions. The missing denominator under "
                "every return figure: 2% on 10% deployed is not 2% on 95%.",
            ),
            ("Peak exposure", _percent(self.peak_exposure), "Most capital deployed at once."),
            (
                "Max drawdown",
                f"{self.max_drawdown_pct:.2%}",
                "Largest peak-to-trough fall in account value.",
            ),
            (
                "Recovery factor",
                _ratio(self.recovery_factor),
                "Net profit against the worst drawdown that produced it. Preferred to "
                "Calmar on short samples because it does not annualise.",
            ),
            (
                "Sharpe",
                _number(self.sharpe),
                "Return per unit of volatility, annualised from the equity curve.",
            ),
        ]


def build_summary(trades: list[ClosedTrade], points: list[EquityPoint]) -> PerformanceSummary:
    return PerformanceSummary(
        stats=compute_stats(trades),
        max_drawdown_pct=max_drawdown(points),
        sharpe=sharpe_ratio(points),
        holding_period=average_holding_period(trades),
        trades_per_week=trades_per_week(trades),
        recovery_factor=recovery_factor(trades, points),
        average_exposure=average_exposure(points),
        peak_exposure=peak_exposure(points),
    )


# A dash rather than a zero throughout: "not enough trades to say" and "zero"
# are different claims, and only one of them is a measurement.
def _money(value: float | None) -> str:
    return "-" if value is None else f"${value:,.2f}"


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.2f}"


def _pair(best: float | None, worst: float | None) -> str:
    if best is None or worst is None:
        return "-"
    return f"+{best:,.2f} / {worst:,.2f}"
