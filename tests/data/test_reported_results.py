"""Reported company results, not just ratios (item 48).

`FundamentalSnapshot` carried only derived metrics - ROE, ROIC, EPS growth,
yields, debt-to-equity. No revenue, no profit, no EBITDA, no reported EPS. So
the AI advisory context could reason about a P/E but never about "revenue up
8%, profit down 3%", and no screen could show a company's actual results.

The data was already in hand and discarded. `yfinance_fundamentals` fetches the
full income statement and takes only EBIT (for `ev_to_ebit`) and the tax rate
(for ROIC). For TNE.AX that frame carries FOUR years of periods with EBITDA,
EBIT, Net Income and Diluted EPS in it.

These figures are reported results, so they are carried RAW with their period
end-date. A growth number without the period it covers is not checkable, and
this application has been bitten repeatedly by figures that could not be traced
to what produced them.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from qat.data.yfinance_fundamentals import reported_results


def _frame() -> pd.DataFrame:
    """Two annual periods, newest first - yfinance's own column order."""
    return pd.DataFrame(
        {
            pd.Timestamp("2025-09-30"): {
                "Total Revenue": 550_000_000.0,
                "Net Income": 120_000_000.0,
                "EBITDA": 180_000_000.0,
                "Diluted EPS": 0.36,
            },
            pd.Timestamp("2024-09-30"): {
                "Total Revenue": 500_000_000.0,
                "Net Income": 100_000_000.0,
                "EBITDA": 160_000_000.0,
                "Diluted EPS": 0.30,
            },
        }
    )


def test_the_latest_reported_figures_are_carried():
    r = reported_results(_frame())
    assert r.revenue == 550_000_000.0
    assert r.net_income == 120_000_000.0
    assert r.ebitda == 180_000_000.0
    assert r.diluted_eps == 0.36


def test_the_period_end_is_carried_with_them():
    """A figure whose period is unknown cannot be checked against anything."""
    assert reported_results(_frame()).period_end == date(2025, 9, 30)


def test_growth_is_measured_against_the_PRIOR_period():
    r = reported_results(_frame())
    assert r.revenue_growth is not None and abs(r.revenue_growth - 0.10) < 1e-9
    assert r.net_income_growth is not None and abs(r.net_income_growth - 0.20) < 1e-9


def test_a_single_period_yields_figures_but_NO_growth():
    """Growth needs two periods. Inventing one from a single column would be
    the fabricated-figure failure this codebase keeps finding."""
    single = _frame().iloc[:, [0]]
    r = reported_results(single)
    assert r.revenue == 550_000_000.0
    assert r.revenue_growth is None
    assert r.net_income_growth is None


def test_a_missing_row_is_None_not_zero():
    """A row the vendor did not answer must not read as a company earning
    nothing."""
    frame = _frame().drop(index="EBITDA")
    r = reported_results(frame)
    assert r.ebitda is None
    assert r.revenue == 550_000_000.0


def test_an_empty_or_absent_frame_answers_nothing():
    assert reported_results(None).revenue is None
    assert reported_results(pd.DataFrame()).period_end is None


def test_a_zero_prior_does_not_divide():
    frame = _frame()
    frame.iloc[:, 1] = 0.0
    r = reported_results(frame)
    assert r.revenue_growth is None
