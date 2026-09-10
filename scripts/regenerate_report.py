r"""Rebuild a daily report from the ledger as it stands now.

    .\.venv\Scripts\python.exe scripts/regenerate_report.py --date 2026-09-09
    .\.venv\Scripts\python.exe scripts/regenerate_report.py --date 2026-09-09 --apply

⚠️ RUN IT UNDER POWERSHELL. It builds `Settings()` and therefore reads
`%LOCALAPPDATA%\QuantAdvisoryTerminal\.env`, and it WRITES to the live data
directory. The Bash sandbox serves a frozen snapshot and does not error.

⚠️ WHY THIS EXISTS. The 9 September daily report was written at 16:04:48, before
the SEK.AX double-count was repaired at 17:18 - "3 closed trade(s), net
$-11,924.91" against a true 2 and -7,797.75. The ledger was corrected and the
report could not be, because `maybe_report` refuses a day it has already done.
A derived artefact that cannot be re-derived is a permanent error.

⚠️ IT APPENDS. The original stays as the record of what was reported at the
time; the rebuild supersedes it and says so in its own heading. Nothing is
overwritten and nothing is deleted.

Dry run by default: prints the report it WOULD append and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402
from qat.domain.performance.reporter import PerformanceReporter  # noqa: E402
from qat.domain.performance.trades import EquityCurve, TradeLedger  # noqa: E402


async def _run(day: date, apply: bool) -> int:
    settings = Settings()
    data_dir = Path(settings.data_dir)
    reporter = PerformanceReporter(
        TradeLedger(EventBus(), data_dir),
        EquityCurve(data_dir),
        settings=settings,
        data_dir=data_dir,
        check_interval_seconds=3600.0,
    )
    target = data_dir / "daily_reports.md"
    print(f"data dir : {data_dir}")
    print(f"target   : {target}")
    print(f"day      : {day:%A %d %B %Y}")
    print()

    if not apply:
        # Build it WITHOUT writing, so the operator sees the figures first.
        report = await reporter._build("daily", f"{day:%A %d %B %Y}", day, day)
        print("DRY RUN - nothing written. This is what would be APPENDED:")
        print()
        print(report.to_markdown())
        print("Re-run with -Apply equivalent: --apply")
        return 0

    report = await reporter.regenerate_daily(day)
    print("APPENDED. The original report for this day is kept above it.")
    print()
    print(report.stats.summary_line())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="the day to rebuild, YYYY-MM-DD")
    parser.add_argument(
        "--apply", action="store_true", help="actually append it; omit for a dry run"
    )
    args = parser.parse_args()
    return asyncio.run(_run(date.fromisoformat(args.date), args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
