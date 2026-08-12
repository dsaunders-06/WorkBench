"""Scheduled report generation at market close (spec M16).

The cadence problem the gap analysis identified: QAT was purely tick-reactive,
so nothing happened *because a day ended*. This engine is the daily/weekly
counterpart to the original app's close-triggered chain, hung off
MarketCalendar rather than a bare wall-clock timer so holidays and early
closes are honoured.

Reports fire once per close, tracked by date in a state file, so a restart
part-way through an evening does not produce a second copy of the same day.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from qat.config import Settings
from qat.domain import market_calendar as mc
from qat.domain.evaluation.approvals import summarise_approvals
from qat.domain.evaluation.refusals import load_risk_decisions, summarise_refusals
from qat.domain.performance.reports import (
    DAILY_REPORT_FILENAME,
    WEEKLY_REPORT_FILENAME,
    PerformanceReport,
    ReportWriter,
    build_report,
    summarise_blocked_reasons,
)
from qat.domain.performance.scorecard import build_all_scorecards
from qat.domain.performance.trades import EquityCurve, TradeLedger


class JournalLike(Protocol):
    """The slice of DecisionJournal used here - just the blocked-decision
    rows a report counts."""

    def entries(self, limit: int | None = ...) -> list[dict[str, str]]: ...


logger = logging.getLogger(__name__)

STATE_FILENAME = "report_state.json"


class PerformanceReporter:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "performance-reporter"

    def __init__(
        self,
        ledger: TradeLedger,
        equity_curve: EquityCurve,
        settings: Settings | None = None,
        data_dir: str | Path | None = None,
        journal: JournalLike | None = None,
        narrator: Callable[[PerformanceReport], object] | None = None,
        check_interval_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
        pending_actions: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.ledger = ledger
        self.equity_curve = equity_curve
        # A callable, so the report reads the CURRENT pending actions at the
        # moment it is written rather than whatever was true when this was
        # constructed - the reporter outlives many sweeps (M39).
        self.pending_actions = pending_actions
        self.settings = settings or Settings()
        directory = Path(data_dir or self.settings.data_dir)
        self.daily_writer = ReportWriter(directory, DAILY_REPORT_FILENAME)
        self.weekly_writer = ReportWriter(directory, WEEKLY_REPORT_FILENAME)
        self.state_path = directory / STATE_FILENAME
        self.journal = journal
        self.narrator = narrator
        self.check_interval_seconds = check_interval_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.check_interval_seconds)
            try:
                await self.maybe_report()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a failed report must not end the loop
                logger.exception("Report generation failed; continuing")

    async def maybe_report(self) -> list[str]:
        """Generates any report that is now due. Returns the periods written.

        Due means: the market whose calendar we follow has closed for a day we
        have not yet reported on. Checked rather than scheduled, so a restart
        at any point in the evening still produces the day's report exactly
        once.
        """
        now = self.clock()
        market: mc.Market = "ASX" if self.settings.market == "ASX" else "US"
        session = mc.session_for(market, now)
        today = session.local_time.date()

        if not mc.is_trading_day(market, today):
            return []
        if session.is_open or session.closed_reason == "before open":
            return []  # the day is not over yet

        written: list[str] = []
        state = self._load_state()

        if state.get("last_daily") != today.isoformat():
            await self._write_daily(today)
            state["last_daily"] = today.isoformat()
            written.append("daily")

        # Weekly runs on the last trading day of the week, identified by asking
        # the calendar rather than assuming Friday - a Friday holiday moves it
        # to Thursday, and a hardcoded weekday would skip that week entirely.
        if self._is_last_trading_day_of_week(market, today):
            week_start = today - timedelta(days=today.weekday())
            if state.get("last_weekly") != week_start.isoformat():
                await self._write_weekly(week_start, today)
                state["last_weekly"] = week_start.isoformat()
                written.append("weekly")

        if written:
            self._save_state(state)
        return written

    @staticmethod
    def _is_last_trading_day_of_week(market: mc.Market, day: date) -> bool:
        """True when no later weekday in this same week is a trading day."""
        for offset in range(1, 7 - day.weekday()):
            candidate = day + timedelta(days=offset)
            if candidate.weekday() >= 5:
                break
            if mc.is_trading_day(market, candidate):
                return False
        return True

    async def _write_daily(self, day: date) -> PerformanceReport:
        report = await self._build("daily", f"{day:%A %d %B %Y}", day, day)
        self.daily_writer.append(report)
        logger.info("Daily report written for %s: %s", day, report.stats.summary_line())
        return report

    async def _write_weekly(self, start: date, end: date) -> PerformanceReport:
        report = await self._build(
            "weekly", f"Week of {start:%d %b %Y} to {end:%d %b %Y}", start, end
        )
        self.weekly_writer.append(report)
        logger.info("Weekly report written for week of %s", start)
        return report

    async def _build(self, period: str, label: str, start: date, end: date) -> PerformanceReport:
        blocked = {}
        if self.journal is not None:
            # Bounded to the reported period, like everything else here (M56b).
            # Unbounded, a clean day inherited every kill-switch and every
            # unprotected position the journal had ever recorded - the 6 August
            # daily reported a kill-switch that fired on the 4th and 434
            # unprotected positions from days it did not cover.
            blocked = summarise_blocked_reasons(
                self.journal.entries(), since=start.isoformat(), until=end.isoformat()
            )

        # Why orders did NOT happen, over the reported period (M51).
        #
        # The rest of this report counts outcomes. At a ten-position cap the
        # behaviour lives in the refusals: on 5 August the book refused 540
        # candidates and took five, and none of that appeared anywhere.
        decisions = load_risk_decisions(self.settings.data_dir, since=start.isoformat())
        refusals = summarise_refusals(decisions)
        # The same rows read from the other side: not what was blocked, but how
        # close what passed came to being blocked.
        approvals = summarise_approvals(decisions, self.settings)

        trades = self.ledger.closed_trades()
        scorecards = build_all_scorecards(
            {name: self.ledger.closed_trades(name) for name in self.ledger.strategies()},
            self.settings,
        )

        report = build_report(
            period=period,
            period_label=label,
            trades=trades,
            equity_points=self.equity_curve.points(),
            start=start,
            end=end,
            scorecards=scorecards,
            blocked_counts=blocked,
            open_lots=self.ledger.open_lots(),
            refusals=refusals,
            approvals=approvals,
            pending_actions=self.pending_actions() if self.pending_actions else (),
        )

        # The narrative is optional and its failure is not the report's
        # failure - the numbers above are already complete and correct.
        if self.narrator is not None:
            try:
                narrative = self.narrator(report)
                if asyncio.iscoroutine(narrative):
                    narrative = await narrative
                if narrative:
                    report = _with_narrative(report, str(narrative))
            except Exception:  # noqa: BLE001 - report still stands without it
                logger.warning("Could not generate a report narrative", exc_info=True)

        return report

    def _load_state(self) -> dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            logger.warning("Could not read %s - starting fresh", self.state_path, exc_info=True)
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not persist report state to %s", self.state_path)


def _with_narrative(report: PerformanceReport, narrative: str) -> PerformanceReport:
    """The same report, plus its narrative (M57b).

    `replace`, not a hand-written constructor call. This listed every field
    explicitly and the list stopped at `blocked_counts`, so `refusals`,
    `approvals`, `opened` and `held` - all four added after it, all four with
    defaults - reverted to those defaults the instant a narrative succeeded.

    It hid for six reports because the narrator was failing on a context-size
    cap, so this line never ran. M56b shrank the report, the narrator returned,
    and the 7 August daily silently lost both M51 evaluation sections and its
    held positions. A frozen dataclass that grows fields will outlive any
    constructor call that names them one by one.
    """
    return replace(report, narrative=narrative)
