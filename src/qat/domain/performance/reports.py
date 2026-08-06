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
import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from qat.domain.evaluation.approvals import ApprovalSummary, format_approval_section
from qat.domain.evaluation.refusals import RefusalSummary, format_refusal_section
from qat.domain.performance.metrics import (
    PerformanceStats,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
)
from qat.domain.performance.scorecard import StrategyScorecard
from qat.domain.performance.summary import PerformanceSummary, build_summary
from qat.domain.performance.trades import ClosedTrade, EquityPoint, OpenLot

logger = logging.getLogger(__name__)

DAILY_REPORT_FILENAME = "daily_reports.md"
WEEKLY_REPORT_FILENAME = "weekly_reports.md"


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """A position the period opened, or one still held at the end of it."""

    symbol: str
    strategy: str | None
    quantity: float
    entry_price: float
    opened_at: datetime

    @property
    def notional(self) -> float:
        return self.quantity * self.entry_price


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
    # The trade-shape and exposure figures (M23), carried so the post-close
    # review reads the same numbers as the screen rather than a subset.
    summary: PerformanceSummary | None
    scorecards: list[StrategyScorecard]
    blocked_counts: dict[str, int]
    # Why orders did not happen (M51). Optional, so every existing caller and
    # test keeps working - and None means "the analysis was not asked for",
    # which is a different statement from "there were no refusals".
    refusals: RefusalSummary | None = None
    # And how close the ones that DID happen came to not happening (M51).
    approvals: ApprovalSummary | None = None
    # Positions opened in the period, and what is held at the end of it (M31c).
    # Every figure above is built from CLOSED trades, so a day with six entries
    # and no exits read exactly like a day when nothing happened at all - which
    # is precisely what 31 July looked like in the report for the first session
    # this system ever traded in.
    opened: tuple[OpenPosition, ...] = ()
    held: tuple[OpenPosition, ...] = ()
    narrative: str | None = None

    @property
    def committed_today(self) -> float:
        return sum(p.notional for p in self.opened)

    @property
    def committed_total(self) -> float:
        return sum(p.notional for p in self.held)

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

    def _position_lines(self) -> list[str]:
        """Positions opened this period, and what is held at the end of it."""
        if not self.opened and not self.held:
            return ["**Positions** none opened, none held.", ""]

        lines: list[str] = []
        if self.opened:
            lines.append(
                f"**Opened** {len(self.opened)} position(s), "
                f"${self.committed_today:,.2f} committed"
            )
            for pos in sorted(self.opened, key=lambda p: p.opened_at):
                lines.append(
                    f"- {pos.symbol} x{pos.quantity:g} @ ${pos.entry_price:,.2f} "
                    f"= ${pos.notional:,.2f} ({pos.strategy or 'unattributed'})"
                )
        else:
            lines.append("**Opened** none this period.")

        if self.held:
            oldest = min(pos.opened_at for pos in self.held)
            lines.append("")
            lines.append(
                f"**Still held** {len(self.held)} position(s), "
                f"${self.committed_total:,.2f} at cost, oldest opened "
                f"{oldest:%d %b %Y}"
            )
        lines.append("")
        return lines

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
        lines.extend(["", f"**Closed trades** {self.stats.summary_line()}", ""])

        # Stated before the closed-trade metrics, because on any day that
        # opened positions this is the activity - and everything below is
        # built from closed trades, so without it a day with six entries and
        # no exits reads exactly like a day when nothing happened.
        lines.extend(self._position_lines())

        if self.summary is not None:
            lines.extend(["### Metrics", ""])
            # Skipping the two already stated above rather than repeating them.
            for label, value, _why in self.summary.rows():
                if label in ("Trades", "Net P&L"):
                    continue
                lines.append(f"- **{label}** {value}")
            lines.append("")

        if self.by_strategy:
            lines.extend(["### By strategy", ""])
            for name, stats in sorted(self.by_strategy.items()):
                lines.append(f"- **{name}** - {stats.summary_line()}")
            lines.append("")

        # Ahead of the autonomy block, because it answers the larger question.
        # "Autonomy declined" says the gate held; this says whether anything
        # ever reached the gate, and at a full book that is the difference
        # between a quiet market and a strangled strategy.
        if self.refusals is not None:
            lines.append(format_refusal_section(self.refusals))

        # Immediately after, because the two are one question asked from both
        # sides: what was blocked, and what nearly was.
        if self.approvals is not None:
            lines.append(format_approval_section(self.approvals))

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
    open_lots: list[OpenLot] | None = None,
    narrative: str | None = None,
    refusals: RefusalSummary | None = None,
    approvals: ApprovalSummary | None = None,
) -> PerformanceReport:
    lots = open_lots or []
    held = tuple(
        OpenPosition(
            symbol=lot.symbol,
            strategy=lot.strategy,
            quantity=lot.quantity,
            entry_price=lot.price,
            opened_at=lot.opened_at,
        )
        for lot in lots
    )
    opened = tuple(pos for pos in held if start <= pos.opened_at.date() <= end)

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
        summary=build_summary(period_trades, period_equity),
        opening_equity=period_equity[0].equity if period_equity else None,
        closing_equity=period_equity[-1].equity if period_equity else None,
        max_drawdown_pct=max_drawdown(period_equity),
        sharpe=sharpe_ratio(period_equity),
        by_strategy=by_strategy,
        scorecards=scorecards or [],
        blocked_counts=blocked_counts or {},
        refusals=refusals,
        approvals=approvals,
        opened=opened,
        held=held,
        narrative=narrative,
    )


# Amounts a reason quotes as evidence, rather than as the name of a rail. Both
# are anchored ($ before, % after) so a bare integer like the "10" in
# "10-position limit" keeps its number - that one names the rail, and reads
# wrong as "N-position limit".
_QUOTED_AMOUNT = re.compile(r"\$[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?%")


def summarise_blocked_reasons(
    journal_rows: list[dict[str, str]],
    since: str | None = None,
    until: str | None = None,
) -> dict[str, int]:
    """Counts why autonomy declined to act, grouped by the leading clause of
    each reason.

    The blocked rows are the ones worth counting: a day with no trades because
    nothing qualified and a day with no trades because the cash floor stopped
    eleven candidates are completely different states of the world, and only
    this tells them apart.

    `since` and `until` are inclusive ISO dates bounding which rows count, and
    they are opt-in: a caller that passes neither gets the whole journal, as
    every caller did before M56b. A caller that passes them gets only rows it
    can prove fall in the period - a row with no readable timestamp is dropped
    rather than assumed current, because assuming current is exactly the bug.
    """
    counts: dict[str, int] = {}
    bounded = since is not None or until is not None
    for row in journal_rows:
        if row.get("outcome", "").startswith("auto_signed"):
            continue
        if bounded:
            day = (row.get("timestamp") or "")[:10]
            if len(day) != 10:
                continue
            if since is not None and day < since:
                continue
            if until is not None and day > until:
                continue
        reason = (row.get("reason") or "").strip()
        if not reason:
            continue
        # Group by the reason's leading clause so per-symbol detail (prices,
        # quantities) does not fragment one cause into many rows.
        key = reason.split(" (")[0].split(" - ")[0].strip()
        # The leading clause alone was not enough. A reason that quotes its
        # measurement before any bracket - "Round-trip cost $18.24 is 13.2% of
        # the $138.38 at risk" - produced a separate row per candidate: 90 keys
        # for one rail, 8,907 characters of report, and a narrative that could
        # not be generated because the result blew its context cap.
        key = _QUOTED_AMOUNT.sub("N", key)
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
