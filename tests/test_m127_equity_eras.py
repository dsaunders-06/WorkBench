"""M127: the equity curve and the refusal log spanned a broker migration too.

M122 gave the TRADE ledger an era and stopped there. Two files were left, and
both were producing wrong numbers in a report generated on 21 August rather
than hypothetically:

* `equity_curve.csv` runs straight through the change of broker - 101,157.17 on
  18 August in an Alpaca US account, 1,003,733.21 on the 19th in an IBKR one,
  one continuous series. The weekly report read that step as *"a dramatic
  nominal equity rise ... a 896.39% increase"* and had an LLM reason about it
  as performance. That week's Sharpe and max drawdown were computed across a
  transfer.
* `risk_decisions.csv` holds the US period's refusals, and the same report
  cited *"rejected all 120 candidate orders because the book was full"* as that
  week's ASX behaviour, against a book that no longer exists.

The scoping is in `points()` rather than at each caller because there are four
callers and every one turns the list into returns, drawdown or Sharpe. A caller
that forgot would not fail - it would publish a number.
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime, timedelta

from qat.domain.evaluation.refusals import load_risk_decisions
from qat.domain.performance.trades import EquityCurve

_BASE = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)


def _curve_with_two_eras(tmp_path):
    """Alpaca samples with no market label, then IBKR ones with it - exactly
    the shape the live file has."""
    path = tmp_path / EquityCurve.FILENAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EquityCurve._FIELDS)
        writer.writeheader()
        for i in range(3):  # the Alpaca era, unlabelled as it really is
            writer.writerow(
                {
                    "ts": (_BASE + timedelta(minutes=i)).isoformat(timespec="seconds"),
                    "equity": 101_000 + i,
                    "cash": 44_000,
                    "market": "",
                }
            )
        for i in range(4):  # the IBKR era
            writer.writerow(
                {
                    "ts": (_BASE + timedelta(days=1, minutes=i)).isoformat(timespec="seconds"),
                    "equity": 1_003_700 + i,
                    "cash": 1_001_865,
                    "market": "ASX",
                }
            )
    return EquityCurve(tmp_path, market="ASX")


def test_points_returns_only_the_current_account(tmp_path, caplog) -> None:
    curve = _curve_with_two_eras(tmp_path)

    with caplog.at_level(logging.WARNING, logger="qat.domain.performance.trades"):
        points = curve.points()

    assert len(points) == 4
    assert {p.market for p in points} == {"ASX"}
    assert all(p.equity > 1_000_000 for p in points)


def test_the_exclusion_is_announced_not_silent(tmp_path, caplog) -> None:
    curve = _curve_with_two_eras(tmp_path)

    with caplog.at_level(logging.WARNING, logger="qat.domain.performance.trades"):
        curve.points()

    said = " ".join(record.getMessage() for record in caplog.records)
    assert "more than one account" in said
    assert "transfer" in said, "the step between two accounts must be named for what it is"


def test_the_896_percent_return_is_no_longer_computable(tmp_path) -> None:
    """The regression, stated as the number that was published."""
    curve = _curve_with_two_eras(tmp_path)

    points = curve.points()
    ratio = points[-1].equity / points[0].equity

    assert ratio < 1.01, "a 9.9x step across a broker change is not a return"


def test_all_points_still_exposes_the_whole_file(tmp_path) -> None:
    """Scoping is for the readers that compute performance. Migration and
    inspection still need everything - losing rows would be worse."""
    curve = _curve_with_two_eras(tmp_path)

    assert len(curve.all_points()) == 7


def test_a_single_era_file_is_untouched_and_quiet(tmp_path, caplog) -> None:
    curve = EquityCurve(tmp_path, market="ASX")
    for i in range(5):
        curve.record(1000.0 + i, 500.0)

    with caplog.at_level(logging.WARNING, logger="qat.domain.performance.trades"):
        points = curve.points()

    assert len(points) == 5
    assert not caplog.records, "the guard must be silent in the ordinary case"


def test_a_recorded_sample_carries_its_market(tmp_path) -> None:
    curve = EquityCurve(tmp_path, market="ASX")
    point = curve.record(1000.0, 500.0)

    assert point.market == "ASX"
    written = (tmp_path / EquityCurve.FILENAME).read_text(encoding="utf-8")
    assert "market" in written.splitlines()[0]
    assert "ASX" in written


# --- risk decisions -----------------------------------------------------------


def _decisions(tmp_path) -> None:
    path = tmp_path / "risk_decisions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "symbol", "reason", "market"])
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2026-08-05T04:00:00+00:00",
                "symbol": "CVS",
                "reason": "already at the 10-position limit",
                "market": "",
            }
        )
        writer.writerow(
            {
                "timestamp": "2026-08-21T04:00:00+00:00",
                "symbol": "RIO.AX",
                "reason": "cost-to-risk",
                "market": "ASX",
            }
        )


def test_refusals_can_be_scoped_to_one_market(tmp_path) -> None:
    _decisions(tmp_path)

    rows = load_risk_decisions(tmp_path, market="ASX")

    assert [row["symbol"] for row in rows] == ["RIO.AX"]


def test_an_unlabelled_refusal_is_not_claimed_by_this_account(tmp_path) -> None:
    """The safe direction: a refusal that cannot say which broker it happened
    on must not be reported as this one's."""
    _decisions(tmp_path)

    rows = load_risk_decisions(tmp_path, market="ASX")

    assert all(row["symbol"] != "CVS" for row in rows)


def test_without_a_market_filter_nothing_changes(tmp_path) -> None:
    _decisions(tmp_path)

    assert len(load_risk_decisions(tmp_path)) == 2


def test_since_and_market_compose(tmp_path) -> None:
    _decisions(tmp_path)

    rows = load_risk_decisions(tmp_path, since="2026-08-20", market="ASX")

    assert len(rows) == 1
