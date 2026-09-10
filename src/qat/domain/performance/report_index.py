"""Split an appended report file into per-day entries, newest first.

⚠️ **THE FILE IS ONE BLOB AND THE SCREEN TREATED IT AS ONE.**
`ReportWriter.append` writes newest LAST and `performance.py` rendered the whole
text into a read-only box, so the newest report was at the BOTTOM of an
ever-growing scroll. Operator design, 10 September 2026: show the CURRENT WEEK
newest-to-oldest, and reach earlier days with a date picker.

⚠️ **A DAY CAN HAVE MORE THAN ONE REPORT, and that is not corruption.**
`regenerate_daily` appends rather than overwrites, deliberately - the original
is the record of what was reported at the time and the rebuild supersedes it.
9 September has THREE: the original, one corrected for the SEK double-count, and
one corrected again for the entry-price precision. So this groups by day, marks
all but the newest as superseded, and keeps them reachable. **Hiding them would
destroy the evidence that the first was wrong**, which is the whole reason
regeneration appends.

Pure and free of Qt so the grouping is testable without a screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

# "## Thursday 10 September 2026"
# "## Wednesday 09 September 2026 - REGENERATED 10 Sep 04:53, supersedes ..."
_HEADING = re.compile(r"^## (?P<label>.+?)\s*$", re.MULTILINE)
_GENERATED = re.compile(r"^_Generated (?P<ts>[\d-]+ [\d:]+) UTC_\s*$", re.MULTILINE)
_DATE_LABEL = "%A %d %B %Y"


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """One report, with the day it covers and whether something newer replaced it."""

    day: date | None
    label: str
    generated_at: datetime | None
    body: str
    superseded: bool = False

    @property
    def is_regeneration(self) -> bool:
        return "REGENERATED" in self.label


def _day_from(label: str) -> date | None:
    """The day a label covers, or None when it is not a daily label.

    ⚠️ Weekly labels ("Week of 07 Sep 2026 to 11 Sep 2026") deliberately return
    None rather than a guess. A weekly report is not a day and forcing one would
    file it under a date nobody chose.
    """
    head = label.split(" - ", 1)[0].strip()
    try:
        return datetime.strptime(head, _DATE_LABEL).date()
    except ValueError:
        return None


def _generated_from(body: str) -> datetime | None:
    match = _GENERATED.search(body)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_reports(text: str) -> list[ReportEntry]:
    """Every report in the file, NEWEST FIRST, superseded ones marked.

    Order is by the day covered, then by when it was generated - not by position
    in the file. A regeneration written today for a day last week belongs with
    that day, not at the top.
    """
    if not text.strip():
        return []

    headings = list(_HEADING.finditer(text))
    entries: list[ReportEntry] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[heading.start() : end].rstrip()
        label = heading.group("label")
        entries.append(
            ReportEntry(
                day=_day_from(label),
                label=label,
                generated_at=_generated_from(body),
                body=body,
            )
        )

    # Mark every entry for a day that has a newer one for the same day.
    newest: dict[date, datetime] = {}
    for entry in entries:
        if entry.day is None or entry.generated_at is None:
            continue
        current = newest.get(entry.day)
        if current is None or entry.generated_at > current:
            newest[entry.day] = entry.generated_at

    marked = [
        ReportEntry(
            day=e.day,
            label=e.label,
            generated_at=e.generated_at,
            body=e.body,
            superseded=(
                e.day is not None and e.generated_at is not None and newest[e.day] > e.generated_at
            ),
        )
        for e in entries
    ]

    # ⚠️ Undated entries keep their file order at the END rather than being
    # dropped - a weekly report, or a heading this cannot parse, is still
    # something the operator may need to read.
    dated = [e for e in marked if e.day is not None]
    undated = [e for e in marked if e.day is None]
    dated.sort(key=lambda e: (e.day, e.generated_at or datetime.min), reverse=True)
    return dated + undated


def days_available(entries: list[ReportEntry]) -> list[date]:
    """Every day with at least one report, newest first - what a picker offers."""
    seen: dict[date, None] = {}
    for entry in entries:
        if entry.day is not None:
            seen.setdefault(entry.day, None)
    return sorted(seen, reverse=True)


def week_of(entries: list[ReportEntry], anchor: date) -> list[ReportEntry]:
    """The Monday-to-Sunday week containing `anchor`, newest first."""
    start = anchor.fromordinal(anchor.toordinal() - anchor.weekday())
    end = start.fromordinal(start.toordinal() + 6)
    return [e for e in entries if e.day is not None and start <= e.day <= end]


def for_day(entries: list[ReportEntry], day: date) -> list[ReportEntry]:
    """Every report for one day, newest first - including superseded ones."""
    return [e for e in entries if e.day == day]
