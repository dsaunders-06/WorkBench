"""The CSV disagreed with the application and nothing said so.

⚠️ FOUND THE HARD WAY, 7 September 2026. The live ledger held a LOV.AX row with
2,843 shares, `gross_pnl` of 12,021.91 and `net_pnl` BLANK - written by the
26 August repair script rather than by `as_row`, which always writes the
computed value.

The application was never wrong. `net_pnl` is a computed property, so in memory
that row reads 12,021.91 and every rail behaved correctly. Only the FILE was
wrong - and the file is what a person opens to check performance by hand.

⚠️ WHAT READING IT COST. Taking the blank as zero turned a +$13,558 winner into
a +$1,535 one, which moved the measured payoff ratio from 2.32 to 0.87 and the
Kelly fraction from positive to negative - a conclusion reported to the operator
before the object was checked against the file. The derived columns are written
for readers and read back by nothing, which is precisely how they drift with no
symptom.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime

from qat.domain.performance.trades import _FIELDS, ClosedTrade, audit_closed_trades


def _trade(**overrides) -> ClosedTrade:
    base = dict(
        symbol="LOV.AX",
        strategy="swing",
        quantity=2843.0,
        entry_price=24.2214,
        exit_price=28.45,
        stop_price=21.92,
        opened_at=datetime(2026, 8, 25, tzinfo=UTC),
        closed_at=datetime(2026, 8, 26, tzinfo=UTC),
        market="ASX",
    )
    base.update(overrides)
    return ClosedTrade(**base)


def _write(path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_a_healthy_file_reports_nothing(tmp_path) -> None:
    path = tmp_path / "closed_trades.csv"
    _write(path, [_trade().as_row()])

    assert audit_closed_trades(path) == []


def test_a_BLANK_derived_column_is_reported(tmp_path) -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR - the real LOV.AX row."""
    row = _trade().as_row()
    row["net_pnl"] = ""
    path = tmp_path / "closed_trades.csv"
    _write(path, [row])

    findings = audit_closed_trades(path)

    assert len(findings) == 1
    assert "net_pnl" in findings[0] and "BLANK" in findings[0]
    assert "12021.91" in findings[0], "the finding must NAME the value that is missing"


def test_a_disagreeing_value_is_reported(tmp_path) -> None:
    """A wrong number is worse than a missing one - it looks like an answer."""
    row = _trade().as_row()
    row["net_pnl"] = "1535.00"
    path = tmp_path / "closed_trades.csv"
    _write(path, [row])

    assert any("net_pnl" in f and "1535" in f for f in audit_closed_trades(path))


def test_rounding_alone_is_not_a_discrepancy(tmp_path) -> None:
    """⚠️ `as_row` rounds. A check that flagged its own rounding would produce
    a finding on every row and be switched off within a day."""
    path = tmp_path / "closed_trades.csv"
    _write(path, [_trade(quantity=333.0).as_row()])

    assert audit_closed_trades(path) == []


def test_an_R_that_cannot_be_computed_is_not_demanded(tmp_path) -> None:
    """A trade with no stop has no R, and blank is the honest record of that."""
    row = _trade(stop_price=None).as_row()
    path = tmp_path / "closed_trades.csv"
    _write(path, [row])

    assert audit_closed_trades(path) == []


def test_an_unparseable_row_is_reported_rather_than_skipped(tmp_path) -> None:
    """⚠️ `_load_closed` drops a row it cannot parse SILENTLY, so it is absent
    from every metric with nothing to show for it. Unreadable is a discrepancy."""
    row = _trade().as_row()
    row["entry_price"] = "not-a-number"
    path = tmp_path / "closed_trades.csv"
    _write(path, [row])

    findings = audit_closed_trades(path)

    assert findings and "invisible to the app" in findings[0]


def test_a_missing_file_is_not_an_error(tmp_path) -> None:
    """A fresh install has no ledger, and that is not a discrepancy."""
    assert audit_closed_trades(tmp_path / "nothing.csv") == []
