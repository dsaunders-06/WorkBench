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

This round adds the sibling hole on the WEIGHT input: NaN is truthy too, so
`if value` alone lets a NaN (or infinite) dollar weight into the book, and
the same skipna=True collapse produces the same measured-zero failure - or,
alongside a healthy position, a silently NaN concentration that would pass
every downstream cap because `nan > limit` is always False. +inf equity gets
the same treatment: `total_equity > 0` alone is True for +inf, so the guard
must check finiteness as well as sign. Two mutation-testing gaps are closed
too: a zero-weight position actually being excluded from `symbols`, and the
"no held symbol is in the sector map" note actually firing.

A later round closes the third sibling hole, on the RETURNS input:
`_combined_portfolio_returns`'s dropna() drops NaN rows but not +/-inf ones,
so a lone infinite observation - a legitimate `pct_change()` artifact over a
vendor zero close - would otherwise reach `np.percentile` and `tail.mean()`
directly. These tests cover one bad tick alongside 59 good ones, enough bad
ticks to fall back through the existing floor gate, an entirely infinite
series, and the reachable case with a real SHORT position rather than a
constructed one. This file also pins the one shape that filter had never
been exercised against: a length-0 RETURNS input entirely, the state at the
very first live poll before any symbol's bar history has warmed.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from qat.domain.risk_engine.book_risk import BookRisk, compute_book_risk
from qat.domain.risk_engine.portfolio_risk import PortfolioRiskChecker

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


def test_a_zero_weight_position_is_excluded_from_symbols():
    """A zero-dollar position is not actually held. Mutating away the
    `if value` filter that excludes it leaves every other test green, since
    none of them checks `symbols` against a book that mixes a zero-weight
    position with a real one."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0, "ZERO.AX": 0.0},
        returns={"A2M.AX": _series([0.01] * 60), "ZERO.AX": _series([0.01] * 60)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.symbols == 1


def test_no_held_symbol_in_sector_map_produces_a_note():
    """The sector map is non-empty but names none of the held symbols, so
    `sector_pct` falls through to None - and that must come with a note, not
    silence. Mutating away the note-append leaves every other test green,
    since the other six either never reach this line (they return absent
    earlier) or supply a sector map that DOES cover the held symbol."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=1_000_000.0,
        sector_by_symbol={"UNRELATED.AX": "Energy"},
        now=NOW,
        min_observations=30,
    )

    assert result.sector_pct is None
    assert any("no held symbol is in the sector map" in note for note in result.notes)


def test_nan_weight_alone_is_absent_not_zero():
    """The sibling hole to NaN equity: NaN is truthy, so a naive `if value`
    filter lets a NaN dollar weight into the book. Left in, it turns the
    weight fraction into NaN and pandas' skipna=True collapses the all-NaN
    row to a MEASURED 0.0 - the exact sentinel this module exists to
    refuse. It must come back absent, with a note naming the symbol."""
    result = compute_book_risk(
        weights={"A2M.AX": float("nan")},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.single_name_pct is None
    assert result.sector_pct is None
    assert result.symbols == 0
    assert result.has_any is False
    assert any("A2M.AX" in note for note in result.notes)


def test_nan_weight_alongside_a_healthy_position_is_excluded_not_zero():
    """With a healthy position beside it, a naive implementation computes
    var_95 from the good leg alone (pandas silently treats the NaN leg as
    zero exposure via skipna=True) but leaves single_name_pct/sector_pct
    NaN - which `nan > limit` would then pass every concentration cap
    silently - and adds no note, so the NaN symbol vanishes as if it had
    never been held. The fix must exclude it AND say so, while still
    measuring the healthy leg on its own."""
    result = compute_book_risk(
        weights={"A2M.AX": float("nan"), "ANZ.AX": 100_000.0},
        returns={
            "A2M.AX": _series([0.01] * 60),
            "ANZ.AX": _series([0.01, -0.03] * 30),
        },
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Financials"},
        now=NOW,
        min_observations=30,
    )

    assert result.symbols == 1
    assert result.single_name_pct == 0.1
    assert result.sector_pct == 0.1
    assert result.var_95 is not None
    assert result.var_95 > 0
    assert any("A2M.AX" in note for note in result.notes)


def test_infinite_weight_is_absent_not_zero():
    """The same guard that catches NaN weight must catch +/-inf too: inf is
    truthy, and `abs(inf) / total_equity` is inf, not a measurable
    concentration."""
    result = compute_book_risk(
        weights={"A2M.AX": float("inf")},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.single_name_pct is None
    assert result.symbols == 0
    assert any("A2M.AX" in note for note in result.notes)


def test_infinite_equity_is_absent_not_zero():
    """`inf > 0` is True, so a naive `total_equity > 0` guard lets +inf
    equity through unchecked. Downstream every weight fraction becomes 0.0
    (not NaN, since a finite number divided by inf is 0.0) - an equally
    MEASURED, and equally wrong, zero."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=float("inf"),
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


def test_a_single_non_finite_return_is_excluded_and_metrics_still_compute():
    """The third sibling hole, on the RETURNS input: dropna() inside
    `_combined_portfolio_returns` removes NaN rows but NOT +/-inf ones, so a
    lone -inf return would otherwise reach np.percentile and tail.mean()
    directly - and can come back as an equally non-finite (or, via the
    nan->0.0 collapse below, a MEASURED 0.0) result. It must be excluded
    before VaR/ES are called, with `observations` and a note reflecting the
    drop - and the 59 finite rows that remain must still be measured, not
    thrown away wholesale."""
    values = [0.01, -0.02, 0.015, -0.01, 0.005, -0.004, 0.02, -0.008, 0.003, -0.012] * 6
    values[7] = float("-inf")
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series(values)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.observations == 59
    assert result.var_95 is not None and math.isfinite(result.var_95)
    assert result.var_99 is not None and math.isfinite(result.var_99)
    assert result.es_975 is not None and math.isfinite(result.es_975)
    assert any("1 non-finite return observation" in note for note in result.notes)


def test_enough_non_finite_returns_drops_the_remainder_below_the_floor():
    """If excluding the non-finite observations leaves too few to measure,
    the existing floor gate must catch the REDUCED count - the same way an
    all-NaN book already does - rather than computing VaR/ES on whatever
    finite rows happen to remain, or on the unfiltered (and non-finite-
    contaminated) series."""
    values = [0.01, -0.015] * 20  # 40 observations
    for i in range(12):
        values[i] = float("inf") if i % 2 == 0 else float("-inf")
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series(values)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.observations == 28
    assert any("12 non-finite return observation" in note for note in result.notes)
    assert any("below the floor of 30" in note for note in result.notes)


def test_all_non_finite_returns_is_absent_not_zero():
    """Every observation unmeasurable must end as None via the existing
    floor gate (0 finite rows), never as the 0.0/inf mess that two
    infinities landing either side of a percentile target produce -
    max(0.0, -float(nan)) is 0.0 because nan > 0.0 is False, the exact
    sentinel this module exists to refuse."""
    values = [float("inf") if i % 2 == 0 else float("-inf") for i in range(60)]
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series(values)},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.observations == 0
    assert any("60 non-finite return observation" in note for note in result.notes)


def test_a_held_book_with_no_return_history_anywhere_is_absent_not_zero():
    """The likeliest live-startup shape: the account snapshot already carries
    real positions but the bar aggregator has not warmed a single symbol yet,
    so the whole RETURNS dict is empty rather than any one symbol's series
    merely being short. `_combined_portfolio_returns` then hands back a
    genuine length-0 Series - a shape no other test in this file produces,
    since every other 'thin book' case still has SOME overlapping return
    data. The non-finite filter (`portfolio_returns.map(math.isfinite)`) and
    the length comparison that follows it must both handle zero rows without
    raising or fabricating an exclusion note about a drop that never
    happened."""
    result = compute_book_risk(
        weights={"A2M.AX": 120_000.0},
        returns={},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.observations == 0
    assert result.single_name_pct == 0.12
    assert result.symbols == 1
    assert not any("non-finite return observation" in note for note in result.notes)
    assert any("below the floor of 30" in note for note in result.notes)


def test_short_weight_over_pct_change_with_zero_closes_is_never_a_measured_zero():
    """The reachable, not-constructed case: `closes.pct_change().dropna()`
    (the exact expression signal_bridge.py:182 uses) produces +inf across a
    vendor zero close, and a SHORT position's negative weight fraction
    flips that to -inf in the combined portfolio series - short positions
    are a documented recurring event in this codebase. Four such incidents
    reproduce the defect signature verbatim on the pre-fix module: var_95
    and var_99 both MEASURED as 0.0, es_975 as inf, with empty notes. None
    of the three may be 0.0 while notes stays empty."""
    closes = [100.0]
    cycle = [1.01, 0.985, 1.015, 0.99, 1.005, 0.996, 1.02, 0.992, 1.003, 0.988]
    for i in range(56):
        closes.append(closes[-1] * cycle[i % len(cycle)])
    # Four separate bad-zero-tick incidents (a vendor zero, then a bounce
    # back to a real price), spread through the series.
    for pos in (10, 22, 34, 46):
        closes.insert(pos, 0.0)
        closes.insert(pos + 1, closes[pos - 1])
    closes_series = pd.Series(
        closes, index=pd.date_range("2026-01-01", periods=len(closes), freq="D")
    )
    returns = closes_series.pct_change().dropna()
    assert any(not math.isfinite(v) for v in returns)  # sanity: the artifact is really there

    result = compute_book_risk(
        weights={"A2M.AX": -100_000.0},
        returns={"A2M.AX": returns},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is not None and math.isfinite(result.var_95)
    assert result.var_99 is not None and math.isfinite(result.var_99)
    assert result.es_975 is not None and math.isfinite(result.es_975)
    assert any("non-finite return observation" in note for note in result.notes)


def _noisy(seed: int, n: int = 120) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.Series(rng.normal(0.0, 0.01, n), index=index)


def test_a_real_book_reports_every_metric():
    weights = {"A2M.AX": 120_000.0, "ANZ.AX": 90_000.0, "BOQ.AX": 60_000.0}
    returns = {"A2M.AX": _noisy(1), "ANZ.AX": _noisy(2), "BOQ.AX": _noisy(3)}

    result = compute_book_risk(
        weights=weights,
        returns=returns,
        total_equity=1_000_000.0,
        sector_by_symbol={
            "A2M.AX": "Consumer Staples",
            "ANZ.AX": "Financials",
            "BOQ.AX": "Financials",
        },
        now=NOW,
        min_observations=30,
    )

    assert result.symbols == 3
    assert result.observations >= 30
    assert result.var_95 is not None and result.var_95 > 0
    assert result.var_99 is not None and result.var_99 >= result.var_95
    assert result.es_975 is not None and result.es_975 > 0
    # Largest single name is A2M at 120k of 1M.
    assert result.single_name_pct == 0.12
    # Largest SECTOR is Financials: ANZ 90k + BOQ 60k = 150k of 1M.
    assert result.sector_pct == 0.15
    assert result.notes == ()


def test_var_matches_the_checker_measured_on_the_same_inputs():
    """⚠️ THE COMPARABILITY CLAIM, ASSERTED. These two numbers are displayed
    side by side, so they must be produced by the same instrument. Measuring a
    rail with a different instrument than the rail uses is how 8 August read
    5.02% against a true 5.87%."""
    weights = {"A2M.AX": 120_000.0, "ANZ.AX": 90_000.0}
    returns = {"A2M.AX": _noisy(1), "ANZ.AX": _noisy(2)}
    equity = 1_000_000.0

    live = compute_book_risk(
        weights=weights,
        returns=returns,
        total_equity=equity,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    # The checker with a candidate of ZERO exposure sees the same book.
    checker = PortfolioRiskChecker()
    decision = checker.check(
        existing_weights=weights,
        existing_returns=returns,
        candidate_symbol="A2M.AX",
        candidate_dollar_exposure=0.0,
        candidate_returns=returns["A2M.AX"],
        total_equity=equity,
    )

    assert live.var_95 == decision.historical_var_95
    assert live.var_99 == decision.historical_var_99
    assert live.es_975 == decision.expected_shortfall_975


def test_a_symbol_with_no_returns_is_excluded_from_var_but_not_concentration():
    """The state after a restart before the warm start finishes: a held symbol
    whose aggregator frame is still empty."""
    result = compute_book_risk(
        weights={"A2M.AX": 120_000.0, "ANZ.AX": 300_000.0},
        returns={"A2M.AX": _noisy(1)},
        total_equity=1_000_000.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    # ANZ has no series, so it cannot enter the combined return math...
    assert result.var_95 is not None
    # ...but it is still held, so it still dominates concentration.
    assert result.single_name_pct == 0.3
    assert result.symbols == 2
