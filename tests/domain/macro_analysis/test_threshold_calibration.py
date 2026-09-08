"""Spec open question 8: "Are the Phase 1 thresholds right?"

They were conventions, and the module said so: *"CONVENTIONAL, NOT MEASURED...
NOT validated against this account's history."* Measured 8 September 2026.

| threshold | was | measured | now |
|---|---|---|---|
| spreads widening | 2.5 | 68.5th pct, true 31.5% of days | **3.0** (87.4th, 12.6%) |
| spreads distressed | 3.5 | 97.1st pct, 2.9% of days; 28.5% of GFC | unchanged |
| RV/HV shock multiple | 1.5 | 90.5th pct of ^AXJO, 9.5% of days | unchanged |
| VIX shock level | 25.0 | 82.7nd pct of VIXCLS, 17.3% of days | unchanged, now per-series |
| vol direction | 0.15 | called 64.5% of days a TREND | **0.25** (54.9% steady) |
| index direction | 0.10 | median monthly |move| is 0.110 | unchanged |

⚠️ **TWO WERE WRONG AND THREE WERE FINE**, which is the useful outcome of
measuring rather than assuming. "Widening" held on a third of all days, and the
volatility band whose stated job is to separate a trend from sampling noise
called the majority of days a trend when the median move exceeds it.

⚠️ **AND ONE WAS A HIDDEN SWITCH.** `compute_macro_signal` looked up
`"VIXCLS"` by a hardcoded literal while `RegimeFeatureBuilder.vix_series` had
been made configurable - so pointing this application's VIX at `^AXVI` moved
the regime engine's column and left this reading hunting for a series nobody
publishes. `vix_shock` would be `None` all session, and `None` is not "no
shock": it removes the SHOCK row from the matrix altogether.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qat.domain.macro_analysis.signal import (
    US_VIX_SHOCK_LEVEL,
    classify_spreads,
    compute_macro_signal,
)


def _bars(n: int = 300, vol: float = 0.004, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0002, vol, n)
    return pd.DataFrame({"close": 100.0 * np.exp(np.cumsum(steps))})


# --- credit spreads -------------------------------------------------------


def test_the_widening_line_no_longer_holds_on_a_third_of_all_days() -> None:
    """⚠️ 2.5 was true on 31.5% of 10,169 readings since 1986. A state that
    common is the weather, and the panel prints the word "widening"."""
    assert classify_spreads(2.8) == "normal"
    assert classify_spreads(3.0) == "widening"


def test_the_distressed_line_is_untouched_because_it_measured_well() -> None:
    """⚠️ THE LOAD-BEARING ONE - the single condition separating BEAR from
    RECESSION, which HALVES THE BOOK. 2.9% of all days, 28.5% of GFC days,
    6.8% of COVID days, 0.0% of 2024-2026."""
    assert classify_spreads(3.49) == "widening"
    assert classify_spreads(3.5) == "distressed"


# --- the VIX, and which series carries it ---------------------------------


def test_the_shock_reads_whichever_series_carries_this_application_s_vix() -> None:
    """⚠️ THE HIDDEN SWITCH. The lookup was the literal "VIXCLS" while the
    regime engine's column had become configurable, so a swap moved one reader
    and stranded the other."""
    signal = compute_macro_signal(
        _bars(), macro_series={"^AXVI": 30.0}, vix_series="^AXVI", vix_shock_level=25.0
    )

    assert signal is not None
    assert signal.vix_shock is True


def test_the_wrong_series_yields_None_rather_than_no_shock() -> None:
    """⚠️ `None` IS NOT "no shock". It removes the SHOCK row from the matrix
    entirely, which is why the stranded-reader bug was worth finding: it looks
    like a calm market from every angle."""
    signal = compute_macro_signal(_bars(), macro_series={"VIXCLS": 40.0}, vix_series="^AXVI")

    assert signal is not None
    assert signal.vix_shock is None


def test_the_default_series_and_level_are_the_american_ones() -> None:
    """Unchanged on purpose: 25.0 is the source document's number, and moving
    it changes which regime the matrix reports."""
    assert US_VIX_SHOCK_LEVEL == 25.0

    signal = compute_macro_signal(_bars(), macro_series={"VIXCLS": 26.0})

    assert signal is not None
    assert signal.vix_shock is True


def test_the_level_travels_with_the_series_rather_than_being_baked_in() -> None:
    """⚠️ Measured over the two years Yahoo serves, `^AXVI` reaches 25.0 on 0.2%
    of ASX days - median 11.52, 99th percentile 18.47. Keeping the American
    level while pointing at the Australian index switches SHOCK off silently
    and permanently, so the level has to be settable beside the series."""
    signal = compute_macro_signal(
        _bars(), macro_series={"^AXVI": 15.0}, vix_series="^AXVI", vix_shock_level=13.0
    )

    assert signal is not None
    assert signal.vix_shock is True


# --- volatility direction --------------------------------------------------


def test_a_move_smaller_than_the_typical_one_is_not_a_trend() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. The median absolute move between
    adjacent 20-day windows on ^AXJO is 0.219, and the old 0.15 tolerance
    called 64.5% of days a trend - a band meant to separate a trend from
    sampling noise, calling the noise a trend most of the time. RECOVERY
    requires `vol_direction == "falling"`, so it was firing on sampling error.
    """
    from qat.domain.macro_analysis.signal import _VOL_DIRECTION_TOLERANCE

    assert _VOL_DIRECTION_TOLERANCE == 0.25


def test_a_genuine_collapse_in_volatility_still_reads_as_falling() -> None:
    """Calibration must not become deafness: a real halving is still a trend."""
    rng = np.random.default_rng(3)
    loud = rng.normal(0.0, 0.02, 20)
    quiet = rng.normal(0.0, 0.003, 20)
    steps = np.concatenate([rng.normal(0.0, 0.01, 260), loud, quiet])
    bars = pd.DataFrame({"close": 100.0 * np.exp(np.cumsum(steps))})

    signal = compute_macro_signal(bars)

    assert signal is not None
    assert signal.vol_direction == "falling"


def test_a_genuine_spike_still_reads_as_rising() -> None:
    rng = np.random.default_rng(11)
    quiet = rng.normal(0.0, 0.003, 20)
    loud = rng.normal(0.0, 0.02, 20)
    steps = np.concatenate([rng.normal(0.0, 0.005, 260), quiet, loud])
    bars = pd.DataFrame({"close": 100.0 * np.exp(np.cumsum(steps))})

    signal = compute_macro_signal(bars)

    assert signal is not None
    assert signal.vol_direction == "rising"


def test_an_unchanged_market_reads_as_steady() -> None:
    rng = np.random.default_rng(5)
    steps = rng.normal(0.0, 0.006, 300)
    signal = compute_macro_signal(pd.DataFrame({"close": 100.0 * np.exp(np.cumsum(steps))}))

    assert signal is not None
    assert signal.vol_direction == "steady"


# --- the two that measured well and stay -----------------------------------


def test_the_shock_multiple_and_index_tolerance_are_recorded_as_measured() -> None:
    """⚠️ Unchanged, and that is a RESULT rather than an omission. 1.5x sits at
    the 90.5th percentile of ^AXJO's RV20/HV252 (9.5% of days), and the CFNAI
    tolerance of 0.10 sits beside a median monthly move of 0.110."""
    from qat.domain.macro_analysis.growth import _INDEX_DIRECTION_TOLERANCE
    from qat.domain.macro_analysis.matrix import _SHOCK_VOL_MULTIPLE

    assert _SHOCK_VOL_MULTIPLE == 1.5
    assert _INDEX_DIRECTION_TOLERANCE == 0.10
