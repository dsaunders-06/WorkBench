"""A restart must not rewrite the day (spec M26).

EquityCurve wrote every sample to CSV and never read one back, so points()
only ever held the current process's history. The first live session was
restarted mid-morning, after the account had gone flat, and the daily report
duly announced the day as "100,660.56 -> 100,660.56, +0.00%, average exposure
0.0%". The real day ran 100,462.97 -> 100,660.56 at 17% average exposure with
a 30.67% peak. Nothing miscalculated; the report simply could not see the
morning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.domain.performance.trades import EquityCurve


def test_a_restart_keeps_the_earlier_samples(tmp_path) -> None:
    morning = EquityCurve(tmp_path)
    start = datetime(2026, 7, 27, 13, 30, tzinfo=UTC)
    morning.record(equity=100_462.97, cash=71_137.61, ts=start)
    morning.record(equity=100_736.63, cash=71_137.61, ts=start + timedelta(minutes=1))

    afternoon = EquityCurve(tmp_path)  # the restart
    afternoon.record(equity=100_660.56, cash=100_660.56, ts=start + timedelta(hours=2))

    points = afternoon.points()
    assert len(points) == 3, "the morning was lost"
    assert points[0].equity == 100_462.97
    assert points[-1].equity == 100_660.56


def test_exposure_survives_the_restart(tmp_path) -> None:
    """The figure that read 0.0% for a day that peaked above 30%."""
    from qat.domain.performance.metrics import average_exposure, peak_exposure

    curve = EquityCurve(tmp_path)
    start = datetime(2026, 7, 27, 13, 30, tzinfo=UTC)
    # `position_value` is recorded explicitly since M133: exposure is the market
    # value HELD, not `equity - cash`, and the round-trip under test now has to
    # carry it through the file as well.
    curve.record(equity=100_000.0, cash=70_000.0, ts=start, position_value=30_000.0)
    curve.record(
        equity=100_000.0,
        cash=90_000.0,
        ts=start + timedelta(minutes=1),
        position_value=10_000.0,
    )

    reopened = EquityCurve(tmp_path)
    reopened.record(
        equity=100_000.0,
        cash=100_000.0,
        ts=start + timedelta(minutes=2),
        position_value=0.0,
    )  # flat

    points = reopened.points()
    assert peak_exposure(points) == 0.30
    assert average_exposure(points) is not None
    assert average_exposure(points) > 0.0, "a restart made the day look uninvested"


def test_no_file_yet_is_simply_an_empty_curve(tmp_path) -> None:
    assert EquityCurve(tmp_path).points() == []


def test_one_damaged_row_does_not_discard_the_rest(tmp_path) -> None:
    """Losing history is bad; refusing to start because of it is worse."""
    curve = EquityCurve(tmp_path)
    curve.record(equity=100.0, cash=50.0, ts=datetime(2026, 7, 27, tzinfo=UTC))
    with curve.path.open("a", encoding="utf-8") as handle:
        handle.write("not-a-timestamp,,\n")
    curve.record(equity=200.0, cash=60.0, ts=datetime(2026, 7, 27, 1, tzinfo=UTC))

    points = EquityCurve(curve.path.parent).points()

    assert [point.equity for point in points] == [100.0, 200.0]
