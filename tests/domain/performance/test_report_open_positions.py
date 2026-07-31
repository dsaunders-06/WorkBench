"""A report must show a day that opened positions (M31c).

Every metric in a report is built from CLOSED trades, so 31 July - the first
session this system ever traded in, six entries and $36,000 committed - read
exactly like a day when nothing happened.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from qat.domain.performance.reports import build_report
from qat.domain.performance.trades import OpenLot

_DAY = date(2026, 7, 31)


def _lot(symbol: str, qty: float, price: float, day: int = 31) -> OpenLot:
    return OpenLot(
        symbol=symbol,
        quantity=qty,
        price=price,
        stop_price=price * 0.92,
        strategy="swing",
        opened_at=datetime(2026, 7, day, 14, 30, tzinfo=UTC),
    )


def _report(lots: list[OpenLot]):
    return build_report(
        period="daily",
        period_label="Friday 31 July 2026",
        trades=[],
        equity_points=[],
        start=_DAY,
        end=_DAY,
        open_lots=lots,
    )


def test_a_day_that_opened_positions_says_so():
    report = _report([_lot("CSCO", 44, 114.38), _lot("UNP", 17, 290.64)])

    assert len(report.opened) == 2
    assert report.committed_today == 44 * 114.38 + 17 * 290.64

    markdown = report.to_markdown()
    assert "**Opened** 2 position(s)" in markdown
    assert "CSCO x44" in markdown
    assert "swing" in markdown


def test_a_position_opened_earlier_is_held_but_not_opened_today():
    """The distinction the report has to make: what this period did, against
    what it is carrying."""
    report = _report([_lot("CSCO", 44, 114.38, day=29), _lot("UNP", 17, 290.64)])

    assert [p.symbol for p in report.opened] == ["UNP"]
    assert len(report.held) == 2

    markdown = report.to_markdown()
    assert "**Opened** 1 position(s)" in markdown
    assert "**Still held** 2 position(s)" in markdown


def test_a_genuinely_quiet_day_still_reads_as_quiet():
    report = _report([])

    assert report.opened == () and report.held == ()
    assert "**Positions** none opened, none held." in report.to_markdown()
