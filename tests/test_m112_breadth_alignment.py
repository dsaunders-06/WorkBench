"""M112: a missing DAY disqualified a whole SYMBOL, so breadth was never on.

Measured on 20 August against live ASX data, 300 daily bars each:

    benchmark STW.AX: 300 bars, 2025-06-17 .. 2026-08-20
    RIO.AX  bars=300  covers_all=False  missing=1  extra=1  first_missing=2025-06-17
    APA.AX  bars=300  covers_all=False  missing=1  extra=1  first_missing=2025-06-17
    ... every symbol identical ...
    _aligned_breadth kept 0 of 7 symbols

`fetch_daily_panel` asks for "the last 300 bars" PER SYMBOL, so each window is
sized by that symbol's own trading days. STW.AX traded one day the stocks did
not, its window starts a day earlier, and every stock is therefore missing the
benchmark's first date. The old rule was `set(wanted) <= closes.keys()` - total
coverage - so a 299-of-300 match was discarded as readily as a 0-of-300 one.

That is not an edge case with independently-sized windows, it is the normal
outcome. Breadth has been constant-zero for the whole ASX period, and the
regime HMM has been fitting a singular column throughout while logging a
warning that said so.

A missing day is not a missing symbol. A stock that did not trade still had a
price. Carry it, and drop a symbol only when it is absent for a material
fraction of the window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from qat.domain.regime_engine.engine import RegimeEngine


def _dates(n: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [start + timedelta(days=i) for i in range(n)]


def _frame(dates: list[datetime], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"ts": pd.to_datetime([d for d in dates]), "close": closes})


def test_full_coverage_still_works_unchanged() -> None:
    """The case that already worked must keep working."""
    dates = _dates(10)

    aligned = RegimeEngine._aligned_breadth(
        dates, {"AAA": _frame(dates, [float(i) for i in range(10)])}
    )

    assert aligned["AAA"] == [float(i) for i in range(10)]


def test_the_20_august_shape_is_kept_instead_of_discarded() -> None:
    """THE REGRESSION. Missing exactly the benchmark's first date - which is
    what every live ASX symbol did - must not disqualify the symbol."""
    dates = _dates(10)
    partial = dates[1:]

    aligned = RegimeEngine._aligned_breadth(
        dates, {"RIO.AX": _frame(partial, [float(i) for i in range(1, 10)])}
    )

    assert "RIO.AX" in aligned, "a symbol missing one day of 10 was thrown away"
    assert len(aligned["RIO.AX"]) == len(dates)
    # The leading gap takes the earliest price the symbol does have. It cannot
    # be carried forward from anything, and inventing a zero would put a false
    # -100% move into the first breadth reading.
    assert aligned["RIO.AX"][0] == 1.0
    assert aligned["RIO.AX"][1] == 1.0


def test_a_day_the_stock_did_not_trade_carries_its_last_close() -> None:
    """A halt or an untraded day is not missing data - the price did not cease
    to exist. Carrying it is what a breadth count means: is this name above its
    average, using the last price it had."""
    dates = _dates(6)
    traded = [dates[0], dates[1], dates[3], dates[4], dates[5]]

    aligned = RegimeEngine._aligned_breadth(
        dates, {"AAA": _frame(traded, [10.0, 11.0, 13.0, 14.0, 15.0])}
    )

    assert aligned["AAA"] == [10.0, 11.0, 11.0, 13.0, 14.0, 15.0]


def test_a_symbol_absent_for_a_material_fraction_is_still_dropped() -> None:
    """The old rule was too strict, not pointless. A symbol that barely trades
    would otherwise contribute a flat line to a breadth count and read as a
    name holding up in a falling market."""
    dates = _dates(100)
    sparse = dates[:40]

    aligned = RegimeEngine._aligned_breadth(dates, {"THIN": _frame(sparse, [1.0] * 40)})

    assert "THIN" not in aligned


def test_every_kept_series_is_exactly_as_long_as_the_benchmark() -> None:
    """RegimeFeatureBuilder counts only a symbol whose history is exactly as
    long as the benchmark's, which is the constraint the old rule was trying
    to satisfy. Satisfy it by construction instead."""
    dates = _dates(20)
    bars = {
        "FULL": _frame(dates, [1.0] * 20),
        "GAPPY": _frame(dates[:5] + dates[7:], [1.0] * 18),  # 2 of 20 missing
        "LATE": _frame(dates[2:], [1.0] * 18),  # a late listing, 2 of 20
    }

    aligned = RegimeEngine._aligned_breadth(dates, bars)

    assert set(aligned) == {"FULL", "GAPPY", "LATE"}
    assert all(len(series) == 20 for series in aligned.values())


def test_an_empty_frame_is_dropped_rather_than_crashing() -> None:
    aligned = RegimeEngine._aligned_breadth(
        _dates(5), {"NONE": pd.DataFrame({"ts": [], "close": []})}
    )

    assert aligned == {}
