"""Performance measurement and the promotion gate (spec M16).

The evidence layer. Everything before this milestone could tell you what the
system decided; nothing could tell you whether it worked - and "promote a
strategy to unattended trading once it is fine tuned" is unanswerable without
that.

* trades.py - realised round-trips matched FIFO from fills, plus the equity
  curve. The only source of truth about outcomes.
* metrics.py - plain arithmetic over those trades. Returns None rather than a
  placeholder whenever the sample is too thin to support a statistic.
* scorecard.py - the promotion gate: falsifiable criteria a strategy must meet
  on realised trades before it is eligible to trade unattended.
* reports.py / reporter.py - daily and weekly reports, generated at market
  close, with the figures computed in code and any AI narrative layered on top.
"""

from qat.domain.performance.metrics import (
    MIN_TRADES_FOR_STATS,
    PerformanceStats,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
)
from qat.domain.performance.reporter import PerformanceReporter
from qat.domain.performance.reports import (
    PerformanceReport,
    ReportWriter,
    build_report,
    summarise_blocked_reasons,
)
from qat.domain.performance.scorecard import (
    PromotionCriterion,
    StrategyScorecard,
    build_all_scorecards,
    build_scorecard,
)
from qat.domain.performance.trades import (
    ClosedTrade,
    EquityCurve,
    EquityPoint,
    OpenLot,
    TradeLedger,
)

__all__ = [
    "MIN_TRADES_FOR_STATS",
    "ClosedTrade",
    "EquityCurve",
    "EquityPoint",
    "OpenLot",
    "PerformanceReport",
    "PerformanceReporter",
    "PerformanceStats",
    "PromotionCriterion",
    "ReportWriter",
    "StrategyScorecard",
    "TradeLedger",
    "build_all_scorecards",
    "build_report",
    "build_scorecard",
    "compute_stats",
    "max_drawdown",
    "sharpe_ratio",
    "summarise_blocked_reasons",
]
