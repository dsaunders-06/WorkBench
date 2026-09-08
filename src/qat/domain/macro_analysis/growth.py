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
GrowthBucket = Literal["negative", "low", "normal", "high"]

# ⚠️ THE BUCKET IS SET BY WHOEVER KNOWS THE UNITS. The matrix used to derive it
# from a year-on-year percentage with thresholds this project invented (1.5% and
# 3.0%). That works for a LEVEL series like GDPC1, and is meaningless for an
# ACTIVITY INDEX: CFNAI is normalised so zero IS trend growth, so a move from
# -0.5 to -0.1 is an 80% "year-on-year change" that actually means "still below
# trend, improving". Each reader now returns the bucket in the units it
# understands, and the matrix stops guessing.

# ⚠️ CONVENTIONAL, NOT MEASURED - the same caveat Phase 1's thresholds carry.
# How much the year-on-year rate must move between readings to count as a turn
# rather than ordinary revision noise. Named so it can be argued with.
_DIRECTION_TOLERANCE_PCT = 0.3

# ⚠️ THE CHICAGO FED'S OWN, not this project's. Below -0.70 following an
# expansion is their published signal that a recession has begun. +0.20 is their
# sustained-inflation threshold, used here as the high-growth boundary - an
# interpretation, stated rather than implied.
_CFNAI_RECESSION = -0.70
_CFNAI_STRONG = 0.20
# In index units, and this one IS ours.
_INDEX_DIRECTION_TOLERANCE = 0.10

# ⚠️ CONVENTIONAL, NOT MEASURED - the year-on-year buckets, kept for level
# series like GDPC1 and INDPRO. Open question 8 in the spec.
_YOY_LOW_PCT = 1.5
_YOY_HIGH_PCT = 3.0

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
    """A growth reading, whatever series it came from."""

    series: str
    bucket: GrowthBucket
    """Where this reading sits, decided by the reader that knows the units."""
    summary: str
    """The reading in ITS OWN units, for the audit trail - "+2.1% y/y", or
    "CFNAI-MA3 -0.85". ⚠️ The matrix quotes this rather than formatting a
    number it cannot interpret."""
    yoy_pct: float | None
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

    return _read(
        latest,
        bucket=_bucket_from_yoy(yoy),
        summary=f"{yoy:+.1f}% y/y",
        yoy_pct=yoy,
        direction=direction,
    )


def _bucket_from_yoy(yoy_pct: float) -> GrowthBucket:
    """⚠️ CONVENTIONAL, NOT MEASURED - unlike the CFNAI bands below, which are
    the Chicago Fed's own. These are the boundaries this project chose for a
    year-on-year rate, and they remain open question 8 in the spec."""
    if yoy_pct < 0.0:
        return "negative"
    if yoy_pct < _YOY_LOW_PCT:
        return "low"
    if yoy_pct < _YOY_HIGH_PCT:
        return "normal"
    return "high"


def _read(
    latest: MacroObservation,
    *,
    bucket: GrowthBucket,
    summary: str,
    yoy_pct: float | None,
    direction: GrowthDirection | None,
) -> GrowthRead:
    now = datetime.now(UTC)
    as_of = latest.ts if latest.ts.tzinfo else latest.ts.replace(tzinfo=UTC)
    return GrowthRead(
        series=latest.series,
        bucket=bucket,
        summary=summary,
        yoy_pct=yoy_pct,
        direction=direction,
        as_of=as_of,
        age_days=max(0, (now - as_of).days),
    )


def classify_activity_index(observations: list[MacroObservation]) -> GrowthRead | None:
    """A composite activity index read against its OWN published bands.

    ⚠️ FOR CFNAI-MA3 AND ITS KIND, NOT FOR A LEVEL SERIES. CFNAI is a weighted
    average of 85 indicators, normalised so ZERO IS TREND GROWTH and the units
    are standard deviations. Putting it through `classify_growth` would compute
    the year-on-year change OF A DEVIATION MEASURE - a move from -0.5 to -0.1
    reads as an 80% change and actually means "still below trend, improving".

    ⚠️ THE BANDS ARE THE CHICAGO FED'S, NOT THIS PROJECT'S, and that is the
    point of choosing this series: it retires two of the invented thresholds the
    spec flagged. Below -0.70 following an expansion is their published
    recession signal. +0.20 is their SUSTAINED-INFLATION threshold, used here as
    the high-growth boundary - that reading is an interpretation and is said out
    loud rather than presented as their rule.

    ⚠️ The direction tolerance below IS this project's, in index units. One
    invented constant remains where three were.
    """
    if not observations:
        return None
    ordered = sorted(observations, key=lambda o: o.ts)
    latest = ordered[-1]
    value = latest.value

    if value < _CFNAI_RECESSION:
        bucket: GrowthBucket = "negative"
    elif value < 0.0:
        bucket = "low"
    elif value < _CFNAI_STRONG:
        bucket = "normal"
    else:
        bucket = "high"

    direction: GrowthDirection | None = None
    if len(ordered) >= 2:
        change = value - ordered[-2].value
        if change > _INDEX_DIRECTION_TOLERANCE:
            direction = "accelerating"
        elif change < -_INDEX_DIRECTION_TOLERANCE:
            direction = "decelerating"
        else:
            direction = "flattening"

    band = (
        f" (below the {_CFNAI_RECESSION} recession threshold)"
        if bucket == "negative"
        else " (above trend)" if value >= 0.0 else " (below trend)"
    )
    return _read(
        latest,
        bucket=bucket,
        summary=f"{latest.series} {value:+.2f}{band}",
        yoy_pct=None,
        direction=direction,
    )
