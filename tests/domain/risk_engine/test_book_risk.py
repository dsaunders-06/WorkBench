"""compute_book_risk must say None, never 0.0, about a book it cannot measure.

`compute_historical_var` and `compute_expected_shortfall` both return 0.0 when
given fewer than two return observations - a sentinel for "not enough data",
not a claim that risk is zero. The live book-risk sampler that will call this
module runs on a timer, independent of any risk decision, so it will
routinely see empty books, one-symbol books, and books with too little
overlapping history. Every one of those must come back as `None` with a note
explaining why, because a live path that let 0.0 leak through would tell the
advisory "no tail risk" about something nobody had actually measured.

These cases are deliberately the ones a naive implementation gets wrong:
nothing held, one observation, a book too thin for VaR but not for
concentration (with a real sector grouping, not sector_pct aliased to
single_name_pct), zero equity, NaN equity slipping past a naive `<= 0` guard,
a caller-supplied floor below the mathematical minimum trying to switch
VaR/ES off, and the clock the caller supplied.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from qat.domain.risk_engine.book_risk import BookRisk, compute_book_risk

NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=index)


def test_an_empty_book_is_absent_not_zero():
    result = compute_book_risk(
        weights={},
        returns={},
        total_equity=1_000_000.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.single_name_pct is None
    assert result.sector_pct is None
    assert result.symbols == 0
    assert any("no positions held" in note for note in result.notes)


def test_one_observation_is_absent_not_zero():
    """⚠️ THE TEST THIS TASK EXISTS FOR. compute_historical_var returns 0.0
    below two observations, so a live path that called it blindly would tell
    the model 'no tail risk' about a book it could not measure - the exact
    failure risk_metrics' own docstring was written to prevent."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01])},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.es_975 is None
    assert result.observations < 30
    assert any("30" in note for note in result.notes)
    assert result.computed_at == NOW


def test_below_the_floor_the_concentration_fields_still_report():
    """single_name_pct needs no return history, so a thin book still gets it.

    The two positions share ONE sector, so the sector total (0.35) exceeds the
    largest single name (0.25). Putting them in different sectors would let an
    implementation that never groups by sector - one that just aliases
    sector_pct to single_name_pct - pass by coincidence."""
    result = compute_book_risk(
        weights={"A2M.AX": 250_000.0, "ANZ.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01, -0.02]), "ANZ.AX": _series([0.0, 0.01])},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.single_name_pct == 0.25
    assert result.sector_pct == 0.35
    assert result.computed_at == NOW


def test_no_equity_is_absent_not_zero():
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=0.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.single_name_pct is None
    assert any("equity" in note for note in result.notes)
    assert result.symbols == 1


def test_nan_equity_is_absent_not_zero():
    """nan <= 0 is False, so a naive `total_equity <= 0` guard lets NaN
    equity slip through. Downstream the weights become NaN and pandas'
    skipna=True collapses the all-NaN series to a MEASURED 0.0 - the exact
    sentinel this module exists to refuse."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=float("nan"),
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.single_name_pct is None
    assert result.sector_pct is None
    assert result.symbols == 1
    assert any("equity" in note for note in result.notes)


def test_a_caller_supplied_floor_below_two_cannot_switch_the_rail_off():
    """min_observations is an unvalidated int handed in by the caller.
    compute_historical_var and compute_expected_shortfall are only
    mathematically defined from 2 observations up, so compute_book_risk must
    enforce that floor itself - a caller passing 0 or 1 must not be able to
    make a book it cannot measure report a measured 0.0."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01])},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=1,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.observations == 1
    assert any("floor" in note for note in result.notes)


def test_computed_at_is_the_clock_it_was_given():
    result = compute_book_risk(
        weights={},
        returns={},
        total_equity=1.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.computed_at == NOW
    assert isinstance(result, BookRisk)
