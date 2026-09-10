"""Grouping an appended report file into per-day entries (operator design, D).

⚠️ The file is one blob written newest-LAST, and the screen rendered the whole
thing into a scrolling box. This is the grouping that lets it show the current
week newest-first with earlier days behind a picker.
"""

from __future__ import annotations

from datetime import date

from qat.domain.performance.report_index import (
    days_available,
    for_day,
    parse_reports,
    week_of,
)

_FILE = """# Daily performance reports

## Monday 07 September 2026

_Generated 2026-09-07 06:04:00 UTC_

**Closed trades** none.

## Wednesday 09 September 2026

_Generated 2026-09-09 06:04:48 UTC_

**Closed trades** 3 closed trade(s), net $-11,924.91.

## Wednesday 09 September 2026 - REGENERATED 10 Sep 04:53, supersedes the report above

_Generated 2026-09-10 04:53:00 UTC_

**Closed trades** 2 closed trade(s), net $-7,797.75.

## Thursday 10 September 2026

_Generated 2026-09-10 06:04:09 UTC_

**Closed trades** No closed trades yet.
"""


def test_entries_come_back_newest_first() -> None:
    entries = parse_reports(_FILE)

    assert [e.day for e in entries] == [
        date(2026, 9, 10),
        date(2026, 9, 9),
        date(2026, 9, 9),
        date(2026, 9, 7),
    ]


def test_a_regenerated_day_supersedes_the_original_and_KEEPS_it() -> None:
    """⚠️ THE POINT OF THE WHOLE MODULE. 9 September has more than one report
    because `regenerate_daily` appends rather than overwrites - the original is
    the record of what was reported at the time. Hiding it would destroy the
    evidence that it was wrong."""
    ninth = for_day(parse_reports(_FILE), date(2026, 9, 9))

    assert len(ninth) == 2
    assert ninth[0].superseded is False
    assert "7,797.75" in ninth[0].body
    assert ninth[1].superseded is True
    assert "11,924.91" in ninth[1].body


def test_a_day_with_one_report_is_not_marked_superseded() -> None:
    tenth = for_day(parse_reports(_FILE), date(2026, 9, 10))

    assert len(tenth) == 1
    assert tenth[0].superseded is False


def test_the_week_is_monday_to_sunday_around_the_anchor() -> None:
    """7 September 2026 is a Monday, so all four entries sit in one week."""
    week = week_of(parse_reports(_FILE), date(2026, 9, 10))

    assert [e.day for e in week] == [
        date(2026, 9, 10),
        date(2026, 9, 9),
        date(2026, 9, 9),
        date(2026, 9, 7),
    ]


def test_a_day_outside_the_week_is_excluded() -> None:
    week = week_of(parse_reports(_FILE), date(2026, 9, 17))

    assert week == []


def test_the_picker_offers_each_day_once_newest_first() -> None:
    assert days_available(parse_reports(_FILE)) == [
        date(2026, 9, 10),
        date(2026, 9, 9),
        date(2026, 9, 7),
    ]


def test_a_weekly_label_is_kept_rather_than_filed_under_a_guessed_day() -> None:
    """⚠️ "Week of 07 Sep 2026 to 11 Sep 2026" is not a day. Forcing one would
    file it under a date nobody chose; dropping it would lose a report."""
    entries = parse_reports(
        "## Week of 07 Sep 2026 to 11 Sep 2026\n\n_Generated 2026-09-11 06:00:00 UTC_\n\nbody\n"
    )

    assert len(entries) == 1
    assert entries[0].day is None
    assert days_available(entries) == []


def test_an_empty_file_is_not_an_error() -> None:
    assert parse_reports("") == []
    assert parse_reports("   \n") == []
