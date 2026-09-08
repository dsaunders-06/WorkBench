"""The matrix must not flip regimes on noise.

Raised in review, 8 September. `decide` selects a DISCRETE regime from
CONTINUOUS inputs, so a value resting on a boundary changes the answer every
reading: RV oscillating either side of HV alternates BULL and BEAR, and spreads
at 3.49 against 3.51 alternates BEAR and RECESSION - a scaled cut against
HALVING THE BOOK.

⚠️ `RegimeEngine` already solved this with `fusion.HysteresisGate`, which cannot
be reused here: it compares PROBABILITIES against a margin and this matrix emits
a bare label. Persistence is the equivalent for a hard classifier.

⚠️ `decide` STAYS PURE. Smoothing is stateful and lives in its own object, so
the arithmetic remains same-inputs-same-answer and auditable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import (
    MatrixRefusal,
    RegimeDecision,
    RegimeHysteresis,
    decide,
)
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.regime import Regime

_SB = 0.20


def _signal(rv: float, hv: float | None = 15.0) -> MacroSignal:
    return MacroSignal(
        realized_vol_annualized_pct=rv,
        vol_direction="steady",
        vix_shock=False,
        term_structure="normal",
        spreads="normal",
        baseline_vol_annualized_pct=hv,
        pct_above_trend=1.0,
        drawdown_from_recent_high_pct=1.0,
        suggested_regime="neutral",
        elevated_volatility=False,
        below_trend=False,
    )


def _bucket(yoy: float) -> str:
    """Mirrors `classify_growth`'s own bucketing, so a fixture's yoy value still
    implies the regime the test is reasoning about."""
    if yoy < 0.0:
        return "negative"
    if yoy < 1.5:
        return "low"
    if yoy < 3.0:
        return "normal"
    return "high"


def _growth(yoy: float) -> GrowthRead:
    return GrowthRead(
        series="GDPC1",
        bucket=_bucket(yoy),  # type: ignore[arg-type]
        summary=f"{yoy:+.1f}% y/y",
        yoy_pct=yoy,
        direction="flattening",
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        age_days=70,
    )


def _read(gate: RegimeHysteresis, rv: float, yoy: float):
    return gate.settle(decide(_signal(rv), _growth(yoy), scaling_unit=_SB, baseline=0.85))


def test_the_first_reading_is_reported_as_it_stands() -> None:
    gate = RegimeHysteresis()

    result = _read(gate, rv=8.74, yoy=4.0)

    assert isinstance(result, RegimeDecision)
    assert result.regime == Regime.BULL


def test_a_single_contrary_reading_does_not_flip_the_regime() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. One reading either side of a boundary
    is noise, not a regime change."""
    gate = RegimeHysteresis(min_persistence=3)
    _read(gate, rv=8.74, yoy=4.0)

    flipped = _read(gate, rv=45.0, yoy=-1.0)

    assert isinstance(flipped, RegimeDecision)
    assert flipped.regime == Regime.BULL, "one contrary reading changed the reported regime"


def test_a_challenger_that_persists_does_take_over() -> None:
    """Smoothing must not become deafness."""
    gate = RegimeHysteresis(min_persistence=3)
    _read(gate, rv=8.74, yoy=4.0)

    for _ in range(3):
        result = _read(gate, rv=45.0, yoy=-1.0)

    assert isinstance(result, RegimeDecision)
    assert result.regime == Regime.BEAR


def test_an_interrupted_challenge_starts_over() -> None:
    """Two readings of bear, one of bull, two of bear is not a regime change -
    it is exactly the flapping this exists to absorb."""
    gate = RegimeHysteresis(min_persistence=3)
    _read(gate, rv=8.74, yoy=4.0)
    _read(gate, rv=45.0, yoy=-1.0)
    _read(gate, rv=45.0, yoy=-1.0)
    _read(gate, rv=8.74, yoy=4.0)
    _read(gate, rv=45.0, yoy=-1.0)
    result = _read(gate, rv=45.0, yoy=-1.0)

    assert isinstance(result, RegimeDecision)
    assert result.regime == Regime.BULL


def test_a_held_regime_still_reports_todays_arithmetic() -> None:
    """⚠️ The NAME is smoothed; the FIGURES are not. Showing yesterday's numbers
    beside today's market would be a different lie."""
    gate = RegimeHysteresis(min_persistence=3)
    _read(gate, rv=8.74, yoy=4.0)

    held = _read(gate, rv=45.0, yoy=-1.0)

    assert isinstance(held, RegimeDecision)
    assert held.regime == Regime.BULL
    assert "45.0" in " ".join(held.reasons), "the held decision hid the live reading"
    assert any("holding" in reason for reason in held.reasons)


def test_a_refusal_passes_straight_through_and_is_never_held() -> None:
    """⚠️ Holding the last good regime over MISSING INPUTS would report a market
    nobody measured - the fabricated-all-clear shape. A refusal must surface
    the moment it happens."""
    gate = RegimeHysteresis(min_persistence=3)
    _read(gate, rv=8.74, yoy=4.0)

    result = gate.settle(decide(_signal(8.74), None, scaling_unit=_SB, baseline=0.85))

    assert isinstance(result, MatrixRefusal)


def test_a_refusal_does_not_advance_a_challenger() -> None:
    """A gap in the inputs is not evidence for the challenging regime."""
    gate = RegimeHysteresis(min_persistence=2)
    _read(gate, rv=8.74, yoy=4.0)
    _read(gate, rv=45.0, yoy=-1.0)
    gate.settle(decide(_signal(8.74), None, scaling_unit=_SB, baseline=0.85))

    result = _read(gate, rv=45.0, yoy=-1.0)

    assert isinstance(result, RegimeDecision)
    assert result.regime == Regime.BULL, "the refusal counted toward the challenge"
