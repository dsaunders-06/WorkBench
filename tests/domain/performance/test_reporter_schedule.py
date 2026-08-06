"""Report scheduling (spec M16).

The cadence gap from the original analysis: QAT was purely tick-reactive, so
nothing happened *because a day ended*. These pin that reports fire once per
close, honour the trading calendar, and survive a restart without duplicating.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.performance.reporter import PerformanceReporter
from qat.domain.performance.trades import EquityCurve, TradeLedger

_NY = ZoneInfo("America/New_York")

# Thursday 23 July 2026 - an ordinary US trading day.
MIDSESSION = datetime(2026, 7, 23, 12, 0, tzinfo=_NY)
AFTER_CLOSE = datetime(2026, 7, 23, 17, 0, tzinfo=_NY)
BEFORE_OPEN = datetime(2026, 7, 23, 6, 0, tzinfo=_NY)
FRIDAY_AFTER_CLOSE = datetime(2026, 7, 24, 17, 0, tzinfo=_NY)
SATURDAY = datetime(2026, 7, 25, 17, 0, tzinfo=_NY)
CHRISTMAS = datetime(2026, 12, 25, 17, 0, tzinfo=UTC)


def _reporter(tmp_path, now: datetime) -> PerformanceReporter:
    return PerformanceReporter(
        TradeLedger(EventBus(), tmp_path),
        EquityCurve(tmp_path),
        settings=Settings(_env_file=None),
        data_dir=tmp_path,
        check_interval_seconds=3600.0,
        clock=lambda: now,
    )


class _JournalStub:
    """Enough of DecisionJournal for a report: rows, newest last."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def entries(self, limit: int | None = None) -> list[dict[str, str]]:
        return self._rows[-limit:] if limit else list(self._rows)


@pytest.mark.asyncio
async def test_a_daily_report_counts_only_the_days_own_blocked_decisions(tmp_path):
    """M56b, and the layer the defect actually lived in.

    `summarise_blocked_reasons` was always capable of being bounded; `_build`
    never passed it a period, so a daily report inherited every blocked
    decision ever journalled. Bounding the helper alone would leave this
    passing untouched, so it is asserted here through the written report.
    """
    journal = _JournalStub(
        [
            {
                "timestamp": "2026-07-20T14:00:00+00:00",
                "outcome": "blocked",
                "reason": "kill-switch active - daily loss",
            },
            {
                "timestamp": "2026-07-23T14:00:00+00:00",
                "outcome": "blocked",
                "reason": "already at the 10-position limit",
            },
        ]
    )
    reporter = PerformanceReporter(
        TradeLedger(EventBus(), tmp_path),
        EquityCurve(tmp_path),
        settings=Settings(_env_file=None),
        data_dir=tmp_path,
        check_interval_seconds=3600.0,
        clock=lambda: AFTER_CLOSE,
        journal=journal,
    )

    assert await reporter.maybe_report() == ["daily"]
    written = (tmp_path / "daily_reports.md").read_text(encoding="utf-8")

    assert "already at the 10-position limit" in written
    # Three days earlier, and nothing to do with the day being reported.
    assert "kill-switch active" not in written


@pytest.mark.asyncio
async def test_nothing_is_reported_while_the_market_is_still_open(tmp_path):
    assert await _reporter(tmp_path, MIDSESSION).maybe_report() == []


@pytest.mark.asyncio
async def test_nothing_is_reported_before_the_open(tmp_path):
    """The day has not happened yet, so there is nothing to report on."""
    assert await _reporter(tmp_path, BEFORE_OPEN).maybe_report() == []


@pytest.mark.asyncio
async def test_a_daily_report_is_written_after_the_close(tmp_path):
    written = await _reporter(tmp_path, AFTER_CLOSE).maybe_report()
    assert written == ["daily"]
    assert (tmp_path / "daily_reports.md").exists()


@pytest.mark.asyncio
async def test_the_same_day_is_not_reported_twice(tmp_path):
    reporter = _reporter(tmp_path, AFTER_CLOSE)
    assert await reporter.maybe_report() == ["daily"]
    assert await reporter.maybe_report() == []


@pytest.mark.asyncio
async def test_a_restart_does_not_duplicate_the_days_report(tmp_path):
    """State is on disk, so a fresh process on the same evening stays quiet."""
    assert await _reporter(tmp_path, AFTER_CLOSE).maybe_report() == ["daily"]
    assert await _reporter(tmp_path, AFTER_CLOSE).maybe_report() == []


@pytest.mark.asyncio
async def test_friday_triggers_the_weekly_report_as_well(tmp_path):
    written = await _reporter(tmp_path, FRIDAY_AFTER_CLOSE).maybe_report()
    assert written == ["daily", "weekly"]
    assert (tmp_path / "weekly_reports.md").exists()


@pytest.mark.asyncio
async def test_a_midweek_close_does_not_trigger_the_weekly(tmp_path):
    assert await _reporter(tmp_path, AFTER_CLOSE).maybe_report() == ["daily"]


@pytest.mark.asyncio
async def test_nothing_is_reported_on_a_weekend(tmp_path):
    assert await _reporter(tmp_path, SATURDAY).maybe_report() == []


@pytest.mark.asyncio
async def test_nothing_is_reported_on_a_holiday(tmp_path):
    assert await _reporter(tmp_path, CHRISTMAS).maybe_report() == []


@pytest.mark.asyncio
async def test_the_weekly_moves_to_thursday_when_friday_is_a_holiday(tmp_path):
    """Christmas 2026 falls on a Friday, so Thursday 24 December is the last
    trading day of that week. A hardcoded Friday would skip the week entirely."""
    thursday = datetime(2026, 12, 24, 17, 0, tzinfo=_NY)
    written = await _reporter(tmp_path, thursday).maybe_report()
    assert "weekly" in written


@pytest.mark.asyncio
async def test_a_narrative_failure_does_not_lose_the_report(tmp_path):
    """The numbers are already complete; the narrative is decoration."""

    def _explode(report):
        raise RuntimeError("model unavailable")

    reporter = PerformanceReporter(
        TradeLedger(EventBus(), tmp_path),
        EquityCurve(tmp_path),
        settings=Settings(_env_file=None),
        data_dir=tmp_path,
        narrator=_explode,
        clock=lambda: AFTER_CLOSE,
    )

    assert await reporter.maybe_report() == ["daily"]
    assert (tmp_path / "daily_reports.md").exists()


@pytest.mark.asyncio
async def test_a_narrative_is_included_when_it_succeeds(tmp_path):
    reporter = PerformanceReporter(
        TradeLedger(EventBus(), tmp_path),
        EquityCurve(tmp_path),
        settings=Settings(_env_file=None),
        data_dir=tmp_path,
        narrator=lambda report: "Quiet session, nothing qualified.",
        clock=lambda: AFTER_CLOSE,
    )

    await reporter.maybe_report()

    text = (tmp_path / "daily_reports.md").read_text(encoding="utf-8")
    assert "Analyst notes" in text
    assert "Quiet session" in text


@pytest.mark.asyncio
async def test_the_engine_starts_and_stops_cleanly(tmp_path):
    reporter = _reporter(tmp_path, MIDSESSION)
    await reporter.start()
    await reporter.stop()
