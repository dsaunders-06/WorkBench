"""Per-strategy promotion gate (spec M16, Phase 6).

Up to now `autonomous_strategies` was a free-text Settings list: whatever an
operator typed was cleared to trade unattended. That is a statement of intent
with no evidence behind it, and "fine tuned" needs to mean something
falsifiable before a strategy runs on its own.

This turns promotion into a claim that can be checked. A strategy is eligible
only when it has traded enough to have a distribution at all, has actually made
money, has an average R above a floor, and has not been the source of a
drawdown beyond tolerance. Every criterion is arithmetic on realised trades -
there is no model in this decision, and no way to argue with it.

The gate **advises**; it does not silently rewrite settings. An operator can
promote a strategy the gate has not cleared - it is their account - but the
Settings screen and the scorecard both show them doing it. Automatically
promoting on the strategy's own numbers would be the system grading its own
homework and then acting on the grade.
"""

from __future__ import annotations

from dataclasses import dataclass

from qat.config import Settings
from qat.domain.performance.metrics import MIN_TRADES_FOR_STATS, PerformanceStats, compute_stats
from qat.domain.performance.trades import ClosedTrade


@dataclass(frozen=True, slots=True)
class PromotionCriterion:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class StrategyScorecard:
    strategy: str
    stats: PerformanceStats
    criteria: list[PromotionCriterion]
    currently_promoted: bool

    @property
    def eligible(self) -> bool:
        return bool(self.criteria) and all(c.passed for c in self.criteria)

    @property
    def failing(self) -> list[PromotionCriterion]:
        return [c for c in self.criteria if not c.passed]

    @property
    def status(self) -> str:
        """Four states, because 'promoted' and 'eligible' are independent and
        the disagreements are the interesting cases."""
        if self.currently_promoted and self.eligible:
            return "promoted"
        if self.currently_promoted and not self.eligible:
            return "promoted-below-bar"
        if self.eligible:
            return "eligible"
        return "not-eligible"

    def summary_line(self) -> str:
        if self.status == "promoted-below-bar":
            reasons = "; ".join(c.detail for c in self.failing)
            return f"{self.strategy}: trading unattended but no longer meets the bar - {reasons}"
        if self.eligible:
            return f"{self.strategy}: meets the promotion bar. {self.stats.summary_line()}"
        reasons = "; ".join(c.detail for c in self.failing)
        return f"{self.strategy}: not eligible - {reasons}"


def build_scorecard(
    strategy: str,
    trades: list[ClosedTrade],
    settings: Settings | None = None,
) -> StrategyScorecard:
    settings = settings or Settings()
    stats = compute_stats(trades)
    promoted = strategy in settings.autonomous_strategies_tuple

    min_trades = max(settings.promotion_min_trades, MIN_TRADES_FOR_STATS)
    criteria = [
        PromotionCriterion(
            "sample size",
            stats.trade_count >= min_trades,
            f"{stats.trade_count} closed trades, {min_trades} required",
        ),
        PromotionCriterion(
            "profitable",
            stats.total_pnl > 0,
            f"net P&L ${stats.total_pnl:,.2f} must be positive",
        ),
        PromotionCriterion(
            "average R",
            stats.average_r is not None and stats.average_r >= settings.promotion_min_average_r,
            _average_r_detail(stats, settings),
        ),
        PromotionCriterion(
            "win rate",
            stats.win_rate is not None and stats.win_rate >= settings.promotion_min_win_rate,
            (
                f"{stats.win_rate:.0%} win rate, {settings.promotion_min_win_rate:.0%} required"
                if stats.win_rate is not None
                else "not enough trades to compute a win rate"
            ),
        ),
        PromotionCriterion(
            "worst trade",
            _worst_trade_within_tolerance(stats, settings),
            _worst_trade_detail(stats, settings),
        ),
    ]

    return StrategyScorecard(
        strategy=strategy, stats=stats, criteria=criteria, currently_promoted=promoted
    )


def _average_r_detail(stats: PerformanceStats, settings: Settings) -> str:
    """Three different reasons average R can be absent, reported as three
    different messages.

    Collapsing them misleads: telling an operator "no trades with a measurable
    stop" when every trade has one, and the real problem is a four-trade
    sample, sends them looking for a bug that is not there.
    """
    if stats.average_r is not None:
        return (
            f"average {stats.average_r:+.2f}R, "
            f"{settings.promotion_min_average_r:+.2f}R required"
        )
    if stats.trade_count == 0:
        return "no closed trades yet"
    if stats.r_trade_count == 0:
        return f"none of the {stats.trade_count} closed trades had a measurable stop"
    return (
        f"only {stats.trade_count} closed trades - too few to average R "
        f"({MIN_TRADES_FOR_STATS} needed)"
    )


def _worst_trade_within_tolerance(stats: PerformanceStats, settings: Settings) -> bool:
    """A good average hides a single catastrophic trade. This is the check that
    stops a strategy being promoted on an average that one outlier could
    reverse."""
    if stats.worst_trade is None or stats.average_win is None:
        return False
    if stats.worst_trade >= 0:
        return True
    return abs(stats.worst_trade) <= stats.average_win * settings.promotion_max_loss_to_avg_win


def _worst_trade_detail(stats: PerformanceStats, settings: Settings) -> str:
    if stats.worst_trade is None:
        return "no trades yet"
    if stats.average_win is None:
        return "no winning trades to compare the worst loss against"
    limit = stats.average_win * settings.promotion_max_loss_to_avg_win
    return (
        f"worst loss ${abs(min(stats.worst_trade, 0.0)):,.2f} against a "
        f"${limit:,.2f} tolerance ({settings.promotion_max_loss_to_avg_win:g}x average win)"
    )


def build_all_scorecards(
    trades_by_strategy: dict[str, list[ClosedTrade]],
    settings: Settings | None = None,
) -> list[StrategyScorecard]:
    """Scorecards for every strategy with trades, plus any promoted strategy
    that has none - a strategy trading unattended with no track record is the
    single most important row to surface, and it would otherwise be invisible
    precisely because it has no data."""
    settings = settings or Settings()
    names = set(trades_by_strategy) | set(settings.autonomous_strategies_tuple)
    return sorted(
        (build_scorecard(name, trades_by_strategy.get(name, []), settings) for name in names),
        key=lambda card: card.strategy,
    )
