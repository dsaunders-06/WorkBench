"""Reproduce the Phase 2C strategy-independent ASX regime proxy audit.

Raw source snapshots and their manifest live outside the repository. This module
contains the declared validation and discrepancy-resolution rules.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from qat.domain.market_calendar import is_trading_day


@dataclass(frozen=True)
class ReturnDiscrepancy:
    month: str
    primary_return_pct: float
    secondary_return_pct: float
    difference_pp: float


@dataclass(frozen=True)
class Resolution:
    choice: Literal["asx", "yahoo"]
    requires_sensitivity: bool


def _month_number(month: str) -> int:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError(f"Invalid month: {month}")
    return int(month[:4]) * 12 + int(month[5:])


def validate_monthly_spine(
    rows: Sequence[tuple[str, float]], minimum_months: int = 120
) -> list[tuple[str, float]]:
    """Require distinct, contiguous months in descending published order."""
    if len(rows) < minimum_months:
        raise ValueError("Fewer than 120 complete months")
    previous: int | None = None
    for month, value in rows:
        number = _month_number(month)
        if previous is not None and previous - number != 1:
            raise ValueError(f"Duplicate, unordered, or missing month at {month}")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid index value at {month}")
        previous = number
    return list(reversed(rows))


def last_asx_session(month: str) -> str:
    """Find the final session using the repository ASX calendar rules."""
    _month_number(month)
    year, month_number = (int(part) for part in month.split("-"))
    last_day = date(year, month_number, calendar.monthrange(year, month_number)[1])
    for offset in range(7):
        candidate = last_day - timedelta(days=offset)
        if is_trading_day("ASX", candidate):
            return candidate.isoformat()
    raise ValueError(f"No ASX session near the end of {month}")


def return_discrepancies(
    primary: Sequence[tuple[str, float]],
    secondary: Sequence[tuple[str, float]],
    threshold_pp: float = 0.1,
) -> list[ReturnDiscrepancy]:
    """Flag differences in simple monthly percentage returns, strictly above cap."""
    if [m for m, _ in primary] != [m for m, _ in secondary]:
        raise ValueError("Month spines differ")
    gaps = []
    for index in range(1, len(primary)):
        month, current = primary[index]
        _, previous = primary[index - 1]
        _, other_current = secondary[index]
        _, other_previous = secondary[index - 1]
        primary_pct = 100 * (current / previous - 1)
        secondary_pct = 100 * (other_current / other_previous - 1)
        difference = primary_pct - secondary_pct
        if abs(difference) > threshold_pp:
            gaps.append(ReturnDiscrepancy(month, primary_pct, secondary_pct, difference))
    return gaps


def resolve_discrepancy(
    *, dates_match: bool, third_supports: Literal["asx", "yahoo"] | None
) -> Resolution:
    """Apply the operator's one-off date and two-of-three rule."""
    if not dates_match:
        return Resolution("asx", False)
    if third_supports is None:
        return Resolution("asx", True)
    return Resolution(third_supports, False)


def _verify_snapshots(raw_dir: Path) -> list[dict[str, object]]:
    manifest = json.loads((raw_dir / "source-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        digest = hashlib.sha256((raw_dir / str(entry["file"])).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {entry['file']}")
    return manifest


def _asx_rows(raw_dir: Path) -> list[tuple[str, float]]:
    from bs4 import BeautifulSoup

    rows = []
    sources = (
        ("asx-historical-market-statistics.html", 2026, 11),
        ("asx-historical-market-statistics-archive.html", 2015, 6),
    )
    for filename, first_year, count in sources:
        html = (raw_dir / filename).read_text(encoding="utf-8")
        tables = BeautifulSoup(html, "html.parser").select("table")[:count]
        if len(tables) != count:
            raise ValueError(f"Missing ASX year table in {filename}")
        for offset, table in enumerate(tables):
            year = first_year - offset
            months = []
            for row in table.select("tr")[1:]:
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                month = {
                    "Jan": 1,
                    "Feb": 2,
                    "Mar": 3,
                    "Apr": 4,
                    "May": 5,
                    "Jun": 6,
                    "Jul": 7,
                    "Aug": 8,
                    "Sep": 9,
                    "Oct": 10,
                    "Nov": 11,
                    "Dec": 12,
                }[cells[0][:3]]
                months.append(month)
                rows.append((f"{year:04d}-{month:02d}", float(cells[2].replace(",", ""))))
            expected = list(range(8, 0, -1)) if year == 2026 else list(range(12, 0, -1))
            if months != expected:
                raise ValueError(f"Incomplete or unordered ASX year {year}")
    chronological = validate_monthly_spine(rows)
    if chronological[0][0] != "2010-01" or chronological[-1][0] != "2026-08":
        raise ValueError("Unexpected ASX source range")
    return chronological


def _rba_rows(raw_dir: Path) -> list[tuple[str, float]]:
    from pypdf import PdfReader

    pdf = raw_dir / "rba-f18-discontinued-2024.pdf"
    text = PdfReader(str(pdf)).pages[0].extract_text(extraction_mode="layout")
    abbreviations = {
        name: index
        for index, name in enumerate(
            ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
        )
    }
    rows = []
    year = None
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"20\d\d", stripped):
            year = int(stripped)
        month = re.match(r"^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s", line)
        if month and year is not None and year >= 2021:
            values = re.findall(r"\d+\.\d+", line)
            if len(values) != 10:
                raise ValueError(f"Malformed RBA F18 row: {line}")
            rows.append((f"{year:04d}-{abbreviations[month.group(1)]:02d}", float(values[-1])))
    if len(rows) != 37 or rows[0][0] != "2021-05" or rows[-1][0] != "2024-05":
        raise ValueError("Unexpected RBA F18 monthly range")
    return rows


def _daily_closes(raw_dir: Path) -> list[tuple[str, float]]:
    with (raw_dir / "yfinance-AXJO-daily-close-2010-2026-08.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = [(row["date"], float(row["close"])) for row in csv.DictReader(handle)]
    if len(rows) != 4205 or rows[0][0] != "2010-01-04" or rows[-1][0] != "2026-08-31":
        raise ValueError("Unexpected Yahoo daily range")
    if any(left[0] >= right[0] for left, right in zip(rows, rows[1:], strict=False)):
        raise ValueError("Yahoo daily dates are not ordered")
    return rows


def _monthly_closes(daily: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    months = {}
    for day, close in daily:
        months[day[:7]] = close
    return sorted(months.items())


def _acf(series: Sequence[float]) -> list[float]:
    import pandas as pd

    values = pd.Series(series, dtype="float64")
    return [float(values.autocorr(lag=lag)) for lag in range(1, 13)]


def _half_life(first_acf: float) -> float | None:
    if 0 < first_acf < 1:
        return math.log(0.5) / math.log(first_acf)
    return None


def _metrics(
    monthly: Sequence[tuple[str, float]], daily: Sequence[tuple[str, float]]
) -> dict[str, dict[str, object]]:
    import numpy as np
    import pandas as pd

    prices = np.asarray([value for _, value in monthly], dtype=float)
    returns = np.diff(np.log(prices))
    daily_dates = pd.to_datetime([date for date, _ in daily])
    daily_prices = pd.Series([value for _, value in daily], index=daily_dates)
    daily_log_returns = np.log(daily_prices).diff()
    vol = (daily_log_returns.pow(2).resample("ME").mean() * 252).pow(0.5).iloc[1:]
    if len(returns) != 199 or len(vol) != 199:
        raise ValueError("Unexpected market proxy observation count")
    metrics = {}
    for name, values in (
        ("monthly_log_return", returns),
        ("absolute_monthly_log_return", np.abs(returns)),
        ("annualized_realized_volatility", vol.to_numpy()),
    ):
        acf = _acf(values)
        metrics[name] = {
            "observations": len(values),
            "acf_lags_1_to_12": acf,
            "ar1_half_life_months": _half_life(acf[0]),
        }
    return metrics


def select_operator_levels(
    asx: dict[str, float], yahoo: dict[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    """Apply the approved July substitution and retain ASX as sensitivity."""
    primary = asx.copy()
    primary["2014-07"] = round(yahoo["2014-07"], 1)
    primary["2023-09"] = yahoo["2023-09"]
    sensitivity = primary.copy()
    sensitivity["2014-07"] = asx["2014-07"]
    return primary, sensitivity


def validate_selected_returns(
    selected: dict[str, float], yahoo: dict[str, float], rba: dict[str, float]
) -> None:
    """Refuse a post-amendment primary that still breaches either return check."""
    shared_yahoo = set(selected) & set(yahoo)
    shared_rba = set(selected) & set(rba)
    yahoo_gaps = return_discrepancies(
        sorted((month, selected[month]) for month in shared_yahoo),
        sorted((month, yahoo[month]) for month in shared_yahoo),
    )
    rba_gaps = return_discrepancies(
        sorted((month, selected[month]) for month in shared_rba),
        sorted((month, rba[month]) for month in shared_rba),
    )
    if yahoo_gaps or rba_gaps:
        raise ValueError("operator-selected primary still breaches the return gate")


def analyze(raw_dir: Path) -> dict[str, object]:
    _verify_snapshots(raw_dir)
    asx = _asx_rows(raw_dir)
    rba = _rba_rows(raw_dir)
    daily = _daily_closes(raw_dir)
    yahoo = _monthly_closes(daily)
    gaps = return_discrepancies(asx, yahoo)
    if {gap.month for gap in gaps} != {"2014-07", "2014-08", "2023-09", "2023-10"}:
        raise ValueError("Unexpected ASX/Yahoo return discrepancy set")
    asx_map = dict(asx)
    yahoo_map = dict(yahoo)
    rba_months = set(dict(rba))
    asx_overlap = [(month, value) for month, value in asx if month in rba_months]
    yahoo_overlap = [(month, value) for month, value in yahoo if month in rba_months]
    rba_asx = return_discrepancies(asx_overlap, rba)
    rba_yahoo = return_discrepancies(yahoo_overlap, rba)
    if {gap.month for gap in rba_asx} != {"2023-09", "2023-10"} or rba_yahoo:
        raise ValueError("RBA cross-check changed")
    daily_map = dict(daily)
    july_session = last_asx_session("2014-07")
    september_session = last_asx_session("2023-09")
    july_yahoo_date = max(day for day, _ in daily if day.startswith("2014-07"))
    september_yahoo_date = max(day for day, _ in daily if day.startswith("2023-09"))
    if daily_map[july_yahoo_date] != yahoo_map["2014-07"]:
        raise ValueError("July Yahoo close-date mismatch")
    if daily_map[september_yahoo_date] != yahoo_map["2023-09"]:
        raise ValueError("September Yahoo close-date mismatch")
    september = resolve_discrepancy(
        dates_match=september_yahoo_date == september_session, third_supports="yahoo"
    )
    pre_amendment_july_fallback = resolve_discrepancy(
        dates_match=july_yahoo_date == july_session, third_supports=None
    )
    if (
        september.choice != "yahoo"
        or pre_amendment_july_fallback.choice != "asx"
        or not pre_amendment_july_fallback.requires_sensitivity
    ):
        raise ValueError("Operator resolution rule failed")
    selected, sensitivity = select_operator_levels(asx_map, yahoo_map)
    validate_selected_returns(selected, yahoo_map, dict(rba))
    return {
        "asx_months": len(asx),
        "asx_range": [asx[0][0], asx[-1][0]],
        "rba_months": len(rba),
        "daily_bars": len(daily),
        "return_discrepancies_asx_yahoo": [gap.__dict__ for gap in gaps],
        "return_discrepancies_asx_rba": [gap.__dict__ for gap in rba_asx],
        "selected": _metrics(sorted(selected.items()), daily),
        "july_asx_sensitivity": _metrics(sorted(sensitivity.items()), daily),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.raw_dir), indent=2))


if __name__ == "__main__":
    main()
