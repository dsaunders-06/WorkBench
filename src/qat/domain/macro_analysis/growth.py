"""The GROWTH axis of the 7-regime macro matrix.

Phase 2 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

Every regime in that matrix keys on growth - high, negative, normal, low,
accelerating, flat - and QAT had PRICE TREND against a 50-day average and
nothing else. ⚠️ Those are not the same thing. Reading a market above its moving
average as "high growth" is the silent category error section 3.3 of the spec
forbids, and it would put a share price where an economy belongs.

⚠️ **THE SERIES IS THE OPERATOR'S CHOICE, NOT THIS MODULE'S.** Everything here
works over whatever observation history FRED returns. WHICH series - and so
which economy - is `Settings.macro_growth_series`, and it ships EMPTY: no growth
axis until someone chooses one, and the matrix refuses growth-dependent regimes
until then. Picking a default here would quietly answer the spec's open question
3, which is also the question of whether US macro should drive an ASX book.

⚠️ **EVERY CANDIDATE IS LAGGED, AND THE MATRIX MUST KNOW IT.** Real GDP is
quarterly and published a month or more after the quarter closes; Australian GDP
is later still, so a reading can be five months old before it moves at all.
`GrowthRead.age_days` carries that so Phase 3 can decide rather than discover.
This module does NOT refuse on age: what counts as too stale depends entirely on
the series chosen, and inventing a limit before the series exists would be
guessing twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from qat.data.macro_fred import MacroObservation

logger = logging.getLogger(__name__)

GrowthDirection = Literal["accelerating", "flattening", "decelerating"]

# ⚠️ CONVENTIONAL, NOT MEASURED - the same caveat Phase 1's thresholds carry.
# How much the year-on-year rate must move between readings to count as a turn
# rather than ordinary revision noise. Named so it can be argued with.
_DIRECTION_TOLERANCE_PCT = 0.3

# How far from exactly one year an observation may sit and still serve as the
# year-ago base.
#
# ⚠️ A WINDOW, NOT A NEAREST-MATCH. Quarterly data will not land on the
# anniversary, so some tolerance is required - but silently reaching to a
# TWO-year-old reading would report a growth rate for a period nobody asked
# about. Outside the window there is no base and the answer is None.
_YEAR_AGO_TOLERANCE_DAYS = 65


@dataclass(frozen=True, slots=True)
class GrowthRead:
    """Year-on-year growth, its direction, and how old the reading is."""

    series: str
    yoy_pct: float
    # `None` when there is not enough history to compare two year-on-year
    # figures. One rate is not a smaller derivative - it is a different fact.
    direction: GrowthDirection | None
    as_of: datetime
    age_days: int


def _year_ago(
    observations: list[MacroObservation], anchor: MacroObservation
) -> MacroObservation | None:
    target = anchor.ts - timedelta(days=365)
    best: MacroObservation | None = None
    best_gap = _YEAR_AGO_TOLERANCE_DAYS + 1
    for observation in observations:
        gap = abs((observation.ts - target).days)
        if gap <= _YEAR_AGO_TOLERANCE_DAYS and gap < best_gap:
            best, best_gap = observation, gap
    return best


def _yoy(observations: list[MacroObservation], anchor: MacroObservation) -> float | None:
    base = _year_ago(observations, anchor)
    if base is None or base.value <= 0:
        # A percentage change against zero or a negative base is not a large
        # number, it is no number.
        return None
    return (anchor.value - base.value) / base.value * 100.0


def classify_growth(observations: list[MacroObservation]) -> GrowthRead | None:
    """Year-on-year growth from a level series, with its direction.

    ⚠️ FROM A LEVEL, NOT A RATE. `GDPC1` and `INDPRO` are index levels, not
    growth rates - reading one straight off would report "growth" of 22,000.
    The year-on-year change is what the matrix's growth axis means.

    Returns `None` rather than a partial answer whenever the history cannot
    support one: too short, no observation near the one-year mark, or a base
    that cannot be divided by. The habit `compute_macro_signal` already follows.
    """
    if not observations:
        return None
    ordered = sorted(observations, key=lambda o: o.ts)
    latest = ordered[-1]

    yoy = _yoy(ordered, latest)
    if yoy is None:
        return None

    # The direction needs a SECOND year-on-year figure, one observation back.
    direction: GrowthDirection | None = None
    if len(ordered) >= 2:
        previous = _yoy(ordered[:-1], ordered[-2])
        if previous is not None:
            change = yoy - previous
            if change > _DIRECTION_TOLERANCE_PCT:
                direction = "accelerating"
            elif change < -_DIRECTION_TOLERANCE_PCT:
                direction = "decelerating"
            else:
                direction = "flattening"

    now = datetime.now(UTC)
    as_of = latest.ts if latest.ts.tzinfo else latest.ts.replace(tzinfo=UTC)
    return GrowthRead(
        series=latest.series,
        yoy_pct=yoy,
        direction=direction,
        as_of=as_of,
        age_days=max(0, (now - as_of).days),
    )
