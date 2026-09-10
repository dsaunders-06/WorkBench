"""A wrong report must be rebuildable from the corrected ledger.

⚠️ WHY THIS EXISTS. The 9 September daily report was written at 16:04:48, BEFORE
the SEK.AX double-count was repaired at 17:18. It says "3 closed trade(s), net
$-11,924.91" against a true 2 and -7,797.75. The ledger under it was corrected;
the report was not, and there was no way to rebuild it - `maybe_report` refuses
a day it has already done, and that is the only entry point there was.

**A derived artefact that cannot be re-derived is a permanent error**, and one
was being added every day the ledger was repaired after the close.

⚠️ REGENERATION APPENDS, IT DOES NOT OVERWRITE. The original is what was
reported at the time and stays as that record; the rebuild supersedes it and
says so. Silently replacing it would destroy the evidence that the first one was
wrong - the same rule `_hold_the_model_to_the_arithmetic` follows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.performance.reporter import PerformanceReporter
from qat.domain.performance.trades import EquityCurve, TradeLedger

AFTER_CLOSE = datetime(2026, 9, 10, 17, 0, tzinfo=UTC)


def _reporter(tmp_path) -> PerformanceReporter:
    return PerformanceReporter(
        TradeLedger(EventBus(), tmp_path),
        EquityCurve(tmp_path),
        settings=Settings(_env_file=None, market="ASX"),
        data_dir=tmp_path,
        check_interval_seconds=3600.0,
        clock=lambda: AFTER_CLOSE,
    )


@pytest.mark.asyncio
async def test_a_day_already_reported_can_be_regenerated(tmp_path) -> None:
    reporter = _reporter(tmp_path)
    await reporter.regenerate_daily(date(2026, 9, 9))

    written = (tmp_path / "daily_reports.md").read_text(encoding="utf-8")

    assert "REGENERATED" in written
    assert "9 September 2026" in written


@pytest.mark.asyncio
async def test_regeneration_APPENDS_and_keeps_the_original(tmp_path) -> None:
    """⚠️ The original is the record of what was reported at the time."""
    reporter = _reporter(tmp_path)
    await reporter._write_daily(date(2026, 9, 9))
    first = (tmp_path / "daily_reports.md").read_text(encoding="utf-8")

    await reporter.regenerate_daily(date(2026, 9, 9))
    after = (tmp_path / "daily_reports.md").read_text(encoding="utf-8")

    assert after.startswith(first), "the original was rewritten rather than kept"
    assert len(after) > len(first)
    assert after.count("9 September 2026") == 2


@pytest.mark.asyncio
async def test_regeneration_does_not_disturb_the_schedule(tmp_path) -> None:
    """⚠️ It must not mark the day as done, nor un-mark it.

    `maybe_report` is gated on `last_daily`. If regenerating wrote that key, a
    rebuild of an OLD day would suppress TODAY's scheduled report; if it cleared
    it, the scheduler would write the day again on the next poll.
    """
    reporter = _reporter(tmp_path)
    before = reporter._load_state()

    await reporter.regenerate_daily(date(2026, 9, 9))

    assert reporter._load_state() == before
