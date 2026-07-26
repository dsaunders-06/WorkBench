"""Daily and weekly performance reports (spec M16).

Structure follows the same division of labour as the macro read: the numbers
are computed here, in code, and handed to the model as established fact for
narration only. A report whose figures came from an LLM would be a report you
could not act on.

The narrative is optional and its absence is not an error - a report with no
narrative is still a complete report. Markdown rather than a database table
because these are meant to be read by a person during a review, and an
append-only text file is trivially diffable, greppable and survivable.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from qat.domain.performance.metrics import (
    PerformanceStats,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
)
from qat.domain.performance.scorecard import StrategyScorecard
from qat.domain.performance.trades import ClosedTrade, EquityPoint

logger = logging.getLogger(__name__)

DAILY_REPORT_FILENAME = "daily_reports.md"
WEEKLY_REPORT_FILENAME = "weekly_reports.md"


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    period: str
    period_label: str
    generated_at: datetime
    stats: PerformanceStats
    opening_equity: float | None
    closing_equity: float | None
    max_drawdown_pct: float
    sharpe: float | None
    by_strategy: dict[str, PerformanceStats]
    scorecards: list[StrategyScorecard]
    blocked_counts: dict[str, int]
    narrative: str | None = None

    @property
    def equity_change(self) -> float | None:
        if self.opening_equity is None or self.closing_equity is None:
            return None
        return self.closing_equity - self.opening_equity

    @property
    def equity_change_pct(self) -> float | None:
        change = self.equity_change
        if change is None or not self.opening_equity:
            return None
        return change / self.opening_equity

    def to_markdown(self) -> str:
        lines = [
            f"## {self.period_label}",
            "",
            f"_Generated {self.generated_at:%Y-%m-%d %H:%M:%S} UTC_",
            "",
        ]

        if self.opening_equity is not None and self.closing_equity is not None:
            change = self.equity_change or 0.0
            pct = self.equity_change_pct
            pct_text = f" ({pct:+.2%})" if pct is not None else ""
            lines.append(
                f"**Equity** ${self.opening_equity:,.2f} -> ${self.closing_equity:,.2f} "
                f"({change:+,.2f}{pct_text})"
            )
        else:
            lines.append("**Equity** not sampled this period.")

        lines.append(f"**Max drawdown** {self.max_drawdown_pct:.2%}")
        if self.sharpe is not None:
            lines.append(f"**Sharpe (annualised)** {self.sharpe:.2f}")
        else:
            lines.append("**Sharpe** not enough samples to measure.")
        lines.extend(["", f"**Trades** {self.stats.summary_line()}", ""])

        if self.by_strategy:
            lines.extend(["### By strategy", ""])
            for name, stats in sorted(self.by_strategy.items()):
                lines.append(f"- **{name}** - {stats.summary_line()}")
            lines.append("")

        if self.blocked_counts:
            lines.extend(["### Autonomy decisions blocked", ""])
            for reason, count in sorted(
                self.blocked_counts.items(), key=lambda kv: (-kv[1], kv[0])
            ):
                lines.append(f"- {count}x {reason}")
            lines.append("")

        if self.scorecards:
            lines.extend(["### Promotion status", ""])
            for card in self.scorecards:
                lines.append(f"- `{card.status}` {card.summary_line()}")
            lines.append("")

        if self.narrative:
            lines.extend(["### Analyst notes", "", self.narrative, ""])

        lines.append("---")
        lines.append("")
        return "\n".join(lines)


def _within(trade: ClosedTrade, start: date, end: date) -> bool:
    closed = trade.closed_at.date()
    return start <= closed <= end


def build_report(
    period: str,
    period_label: str,
    trades: list[ClosedTrade],
    equity_points: list[EquityPoint],
    start: date,
    end: date,
    scorecards: list[StrategyScorecard] | None = None,
    blocked_counts: dict[str, int] | None = None,
    narrative: str | None = None,
) -> PerformanceReport:
    period_trades = [trade for trade in trades if _within(trade, start, end)]
    period_equity = [point for point in equity_points if start <= point.ts.date() <= end]

    by_strategy: dict[str, PerformanceStats] = {}
    for name in sorted({trade.strategy for trade in period_trades if trade.strategy}):
        by_strategy[name] = compute_stats(
            [trade for trade in period_trades if trade.strategy == name]
        )

    return PerformanceReport(
        period=period,
        period_label=period_label,
        generated_at=datetime.now(UTC),
        stats=compute_stats(period_trades),
        opening_equity=period_equity[0].equity if period_equity else None,
        closing_equity=period_equity[-1].equity if period_equity else None,
        max_drawdown_pct=max_drawdown(period_equity),
        sharpe=sharpe_ratio(period_equity),
        by_strategy=by_strategy,
        scorecards=scorecards or [],
        blocked_counts=blocked_counts or {},
        narrative=narrative,
    )


def summarise_blocked_reasons(journal_rows: list[dict[str, str]]) -> dict[str, int]:
    """Counts why autonomy declined to act, grouped by the leading clause of
    each reason.

    The blocked rows are the ones worth counting: a day with no trades because
    nothing qualified and a day with no trades because the cash floor stopped
    eleven candidates are completely different states of the world, and only
    this tells them apart.
    """
    counts: dict[str, int] = {}
    for row in journal_rows:
        if row.get("outcome", "").startswith("auto_signed"):
            continue
        reason = (row.get("reason") or "").strip()
        if not reason:
            continue
        # Group by the reason's leading clause so per-symbol detail (prices,
        # quantities) does not fragment one cause into many rows.
        key = reason.split(" (")[0].split(" - ")[0].strip()
        counts[key] = counts.get(key, 0) + 1
    return counts


class ReportWriter:
    """Appends reports to a Markdown file, newest last."""

    def __init__(self, data_dir: str | Path, filename: str) -> None:
        self.path = Path(data_dir) / filename
        self._lock = threading.Lock()

    def append(self, report: PerformanceReport) -> None:
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", encoding="utf-8") as handle:
                    if is_new:
                        handle.write(f"# {report.period.capitalize()} performance reports\n\n")
                    handle.write(report.to_markdown())
        except OSError:
            logger.exception("Could not append a %s report to %s", report.period, self.path)

    def read(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Could not read %s", self.path)
            return ""
