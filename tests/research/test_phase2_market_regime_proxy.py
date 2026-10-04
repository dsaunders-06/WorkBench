from __future__ import annotations

import pytest

from scripts.research.phase2_market_regime_proxy import (
    last_asx_session,
    resolve_discrepancy,
    return_discrepancies,
    validate_monthly_spine,
)


def _rows(count: int = 120) -> list[tuple[str, float]]:
    year, month = 2025, 12
    rows = []
    for offset in range(count):
        rows.append((f"{year:04d}-{month:02d}", 100.0 + offset))
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return rows


def test_monthly_spine_accepts_complete_descending_history() -> None:
    rows = _rows()
    assert validate_monthly_spine(rows)[0] == ("2016-01", 219.0)
    assert validate_monthly_spine(rows)[-1] == ("2025-12", 100.0)


@pytest.mark.parametrize("change", ["duplicate", "order", "gap"])
def test_monthly_spine_rejects_duplicate_out_of_order_or_gap(change: str) -> None:
    rows = _rows()
    if change == "duplicate":
        rows.insert(5, rows[5])
    elif change == "order":
        rows[5], rows[6] = rows[6], rows[5]
    else:
        rows.pop(5)
    with pytest.raises(ValueError):
        validate_monthly_spine(rows)


def test_return_discrepancies_apply_strict_point_one_percentage_point_gate() -> None:
    primary = [("2025-01", 100.0), ("2025-02", 110.0), ("2025-03", 120.0)]
    other = [("2025-01", 100.0), ("2025-02", 109.5), ("2025-03", 119.5)]
    gaps = return_discrepancies(primary, other, threshold_pp=0.1)
    assert [gap.month for gap in gaps] == ["2025-02"]
    assert gaps[0].difference_pp == pytest.approx(0.5)


def test_discrepancy_resolution_date_mismatch_keeps_asx() -> None:
    decision = resolve_discrepancy(dates_match=False, third_supports="yahoo")
    assert decision.choice == "asx"
    assert not decision.requires_sensitivity


def test_discrepancy_resolution_two_of_three_selects_yahoo() -> None:
    decision = resolve_discrepancy(dates_match=True, third_supports="yahoo")
    assert decision.choice == "yahoo"
    assert not decision.requires_sensitivity


def test_discrepancy_resolution_without_third_keeps_asx_and_requires_sensitivity() -> None:
    decision = resolve_discrepancy(dates_match=True, third_supports=None)
    assert decision.choice == "asx"
    assert decision.requires_sensitivity


def test_disputed_months_end_on_repository_asx_sessions() -> None:
    assert last_asx_session("2014-07") == "2014-07-31"
    assert last_asx_session("2023-09") == "2023-09-29"
