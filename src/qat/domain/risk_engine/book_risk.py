"""Portfolio risk over the book ACTUALLY HELD, independent of any decision.

⚠️ WHY THIS EXISTS. `risk_metrics()` read the last risk decision's
`portfolio_check`, which is written one rail AFTER the governor's position-count
rejection. With the book at 10 of 10 every candidate is refused before the
portfolio checker runs, so 3,533 of 3,596 audit rows carry no number at all - and
`AuditLog._entries` is in-memory, so `entries()` is empty at every startup
regardless. The model was being told "none available" on every run.

⚠️ ABSENT IS None, NEVER 0.0. `compute_historical_var` and
`compute_expected_shortfall` both return 0.0 below two observations. Calling them
blindly on a thin book would hand the model "no tail risk" about something it
could not measure, which is precisely the failure `risk_metrics`' docstring names:
"a metric the last check did not record reached the model as a MEASURED ZERO".
Every gate here happens BEFORE the call - but that alone is not the guarantee:
`min_observations` arrives as an unvalidated int, and a caller passing 0 or 1
would otherwise gate on nothing. `compute_book_risk` clamps it up to 2, the
floor those two functions themselves impose, so the rail cannot be switched
off by whoever calls it.

The computation reuses `PortfolioRiskChecker`'s own internals rather than
reimplementing them, because the live figure is displayed BESIDE the decision
figure and two numbers measured with different instruments cannot be compared.
That is the 8 August lesson: 5.02% against a true 5.87%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from qat.domain.risk_engine.portfolio_risk import (
    _ES_CONFIDENCE,
    _VAR_CONFIDENCE_95,
    _VAR_CONFIDENCE_99,
    PortfolioRiskChecker,
    compute_expected_shortfall,
    compute_historical_var,
)

# The mathematical floor, not a policy choice: compute_historical_var and
# compute_expected_shortfall both return 0.0 (not None) below this many
# observations. compute_book_risk enforces it regardless of what
# min_observations its caller passes - see the CRITICAL note above.
_MIN_OBSERVATIONS_FLOOR = 2


@dataclass(frozen=True, slots=True)
class BookRisk:
    """One measurement of the held book. Every metric is optional, and `None`
    means "not measurable", which is a DIFFERENT CLAIM from zero."""

    computed_at: datetime
    symbols: int
    observations: int
    var_95: float | None
    var_99: float | None
    es_975: float | None
    single_name_pct: float | None
    sector_pct: float | None
    notes: tuple[str, ...]

    @property
    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.var_95,
                self.var_99,
                self.es_975,
                self.single_name_pct,
                self.sector_pct,
            )
        )

    def age_seconds(self, now: datetime) -> float:
        return (now - self.computed_at).total_seconds()


def _absent(now: datetime, notes: tuple[str, ...], symbols: int = 0) -> BookRisk:
    return BookRisk(
        computed_at=now,
        symbols=symbols,
        observations=0,
        var_95=None,
        var_99=None,
        es_975=None,
        single_name_pct=None,
        sector_pct=None,
        notes=notes,
    )


def compute_book_risk(
    *,
    weights: dict[str, float],
    returns: dict[str, pd.Series],
    total_equity: float,
    sector_by_symbol: dict[str, str] | None,
    now: datetime,
    min_observations: int,
) -> BookRisk:
    """Measure the held book. Never raises; never substitutes zero for absent.

    ⚠️ `single_name_pct` and `sector_pct` are the LARGEST in the book, where the
    decision path's fields of the same name are the CANDIDATE's. There is no
    candidate here. Wherever the two are displayed together they must be
    labelled differently, or a coincidence reads as agreement.

    `min_observations` is an unvalidated int supplied by the caller; it is
    clamped up to `_MIN_OBSERVATIONS_FLOOR` before it gates anything, so a
    caller passing 0 or 1 cannot switch VaR/ES off.
    """
    notes: list[str] = []
    held: dict[str, float] = {}
    for symbol, value in weights.items():
        if not value:
            continue
        if not math.isfinite(value):
            # A NaN or infinite dollar weight is truthy, so the zero-filter just
            # above lets it through. Left in `held` it turns the weight fraction
            # below into NaN, and pandas' skipna=True then collapses the all-NaN
            # row to a MEASURED 0.0 - the same failure mode already closed for
            # equity, on the sibling input. Exclude it AND say so, rather than
            # let it vanish as if it were simply zero exposure.
            notes.append(
                f"{symbol} weight is not finite (nan/inf), so it cannot be "
                "measured and was excluded from the book"
            )
            continue
        held[symbol] = value

    if not held:
        return _absent(now, tuple(notes) or ("no positions held",))
    if not (math.isfinite(total_equity) and total_equity > 0):
        # Finiteness and sign must both be checked: `total_equity <= 0` alone
        # lets NaN through (nan <= 0 is False), and `total_equity > 0` alone
        # lets +inf through (inf > 0 is True). Either one reaching here turns
        # every weight fraction downstream into NaN or 0.0, and pandas'
        # skipna=True then collapses the all-NaN row to a MEASURED 0.0 -
        # exactly the sentinel this module exists to refuse.
        notes.append("equity is not available, so nothing can be measured")
        return _absent(now, tuple(notes), len(held))

    # Concentration needs no return history, so it is computed first and
    # survives a book too thin for VaR.
    single_name_pct = max(abs(value) for value in held.values()) / total_equity

    sector_pct: float | None = None
    if sector_by_symbol:
        by_sector: dict[str, float] = {}
        for symbol, value in held.items():
            sector = sector_by_symbol.get(symbol)
            if sector is None:
                continue
            by_sector[sector] = by_sector.get(sector, 0.0) + abs(value)
        if by_sector:
            sector_pct = max(by_sector.values()) / total_equity

    if sector_pct is None:
        notes.append("no held symbol is in the sector map, so sector concentration is unknown")

    portfolio_returns = PortfolioRiskChecker._combined_portfolio_returns(
        held, returns, total_equity
    )
    observations = len(portfolio_returns)

    # ⚠️ THE GATE, BEFORE THE CALL - and the floor it gates on is not simply
    # whatever min_observations the caller passed. See _MIN_OBSERVATIONS_FLOOR.
    # Below the floor these three stay None.
    floor = max(_MIN_OBSERVATIONS_FLOOR, min_observations)
    if observations < floor:
        notes.append(
            f"{observations} overlapping return observation(s) across {len(held)} position(s), "
            f"below the floor of {floor} needed - VaR and ES are UNKNOWN, not zero"
        )
        return BookRisk(
            computed_at=now,
            symbols=len(held),
            observations=observations,
            var_95=None,
            var_99=None,
            es_975=None,
            single_name_pct=single_name_pct,
            sector_pct=sector_pct,
            notes=tuple(notes),
        )

    return BookRisk(
        computed_at=now,
        symbols=len(held),
        observations=observations,
        var_95=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_95),
        var_99=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_99),
        es_975=compute_expected_shortfall(portfolio_returns, _ES_CONFIDENCE),
        single_name_pct=single_name_pct,
        sector_pct=sector_pct,
        notes=tuple(notes),
    )
