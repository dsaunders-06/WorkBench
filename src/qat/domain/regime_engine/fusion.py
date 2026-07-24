"""Rules overlay + fusion + hysteresis (spec §E, paper §7.1, §9.1, §11.3).

The HMM's state-signature-weighted posterior gives five raw scores (bull,
bear, sideways, high-vol, low-vol) from return/vol statistics alone; rules
add what return/vol structurally can't see (recession risk from the yield
curve, the 200-day bull-block, the VIX vol axis), and recovery is scored
from a price/curve heuristic since there's no real GDP/employment feed yet.
Hysteresis then smooths the discrete label so it doesn't whipsaw on noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from qat.domain.regime import ALL_REGIMES, Regime
from qat.domain.regime_engine.hmm_core import StateSignature

# Illustrative default probit coefficients (Estrella-Mishkin-style NY Fed
# recession-model structure) - NOT the Fed's actual published calibration,
# which isn't reproduced here with confidence. Replace with the Fed's
# published coefficients before relying on this for real signal.
_RECESSION_PROBIT_A = -0.53
_RECESSION_PROBIT_B = -0.63

_VIX_LOW_THRESHOLD = 15.0
_VIX_HIGH_THRESHOLD = 25.0

_EXPOSURE_SCALARS: dict[Regime, float] = {
    Regime.BULL: 1.0,
    Regime.RECOVERY: 0.9,
    Regime.LOW_VOL: 1.0,
    Regime.SIDEWAYS: 0.7,
    Regime.BEAR: 0.5,
    Regime.HIGH_VOL: 0.4,
    Regime.RECESSION: 0.3,
}


def compute_recession_probability(
    yield_curve_slope_pct: float,
    a: float = _RECESSION_PROBIT_A,
    b: float = _RECESSION_PROBIT_B,
) -> float:
    """NY Fed/Estrella-Mishkin probit structure: P = Phi(a + b * spread).
    An inverted (negative) spread raises the probability given b < 0."""
    z = a + b * yield_curve_slope_pct
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def is_bull_blocked(price: float, sma_200: float) -> bool:
    """Price below the 200-day average blocks the Bull label (paper §11.3)."""
    return sma_200 > 0 and price < sma_200


def classify_vix_axis(vix_level: float) -> Literal["low_vol", "normal", "high_vol"]:
    if vix_level < _VIX_LOW_THRESHOLD:
        return "low_vol"
    if vix_level > _VIX_HIGH_THRESHOLD:
        return "high_vol"
    return "normal"


def exposure_scalar_for(label: Regime) -> float:
    return _EXPOSURE_SCALARS[label]


_MAX_Z_SCORE_CONTRIBUTION = 2.0


def _relu(x: float) -> float:
    return max(0.0, x)


def _bounded_relu(x: float) -> float:
    """Like _relu, but capped so a single outlier state (z-scores are
    relative to as few as 2-4 fitted states, so they're not as
    well-behaved as a population z-score) can't unboundedly dominate the
    fixed-scale rule bonuses in RegimeFusion.compute."""
    return max(0.0, min(x, _MAX_Z_SCORE_CONTRIBUTION))


_EMPTY_HMM_SCORES: dict[Regime, float] = {
    Regime.BULL: 0.0,
    Regime.BEAR: 0.0,
    Regime.SIDEWAYS: 0.0,
    Regime.HIGH_VOL: 0.0,
    Regime.LOW_VOL: 0.0,
}


def score_from_hmm(
    posterior: list[float], signatures: dict[int, StateSignature]
) -> dict[Regime, float]:
    """Turns the HMM's per-state posterior into raw bull/bear/sideways/
    high-vol/low-vol scores via each state's return/vol z-score signature.

    States the HMM never actually assigned any observations to (NaN
    signature - see hmm_core.py) are excluded from the z-score population:
    including a fabricated placeholder there produces a pure artifact - with
    n_states-1 empty states at exactly (0, 0), the lone real state's z-score
    is always sqrt(n_states - 1) regardless of the actual data, since that's
    just the z-score of one nonzero point against a population of zeros.
    """
    valid_states = [s for s in range(len(posterior)) if not math.isnan(signatures[s].mean_return)]
    if not valid_states:
        return dict(_EMPTY_HMM_SCORES)

    returns = [signatures[s].mean_return for s in valid_states]
    vols = [signatures[s].mean_vol for s in valid_states]
    return_mean = sum(returns) / len(returns)
    return_std = (sum((r - return_mean) ** 2 for r in returns) / len(returns)) ** 0.5
    vol_mean = sum(vols) / len(vols)
    vol_std = (sum((v - vol_mean) ** 2 for v in vols) / len(vols)) ** 0.5

    bull = bear = sideways = high_vol = low_vol = 0.0
    for state in valid_states:
        p = posterior[state]
        return_z = (
            (signatures[state].mean_return - return_mean) / return_std if return_std > 0 else 0.0
        )
        vol_z = (signatures[state].mean_vol - vol_mean) / vol_std if vol_std > 0 else 0.0
        bull += p * _bounded_relu(return_z)
        bear += p * _bounded_relu(-return_z)
        sideways += p * _relu(1.0 - abs(return_z))
        high_vol += p * _bounded_relu(vol_z)
        low_vol += p * _bounded_relu(-vol_z)

    return {
        Regime.BULL: bull,
        Regime.BEAR: bear,
        Regime.SIDEWAYS: sideways,
        Regime.HIGH_VOL: high_vol,
        Regime.LOW_VOL: low_vol,
    }


@dataclass
class RegimeFusion:
    # Comparable in scale to the now-bounded HMM z-score contributions
    # (see _bounded_relu) so the VIX rule can meaningfully compete with -
    # not be swamped by - a noisy HMM read, per paper §11.3's intent that
    # rules should guard against HMM mislabelling.
    vix_bonus: float = 1.0

    def compute(
        self,
        posterior: list[float],
        signatures: dict[int, StateSignature],
        yield_curve_slope: float,
        yield_curve_slope_prev: float,
        vix_level: float,
        price: float,
        sma_200: float,
        sma_200_prev: float,
    ) -> dict[Regime, float]:
        scores = score_from_hmm(posterior, signatures)

        if is_bull_blocked(price, sma_200):
            scores[Regime.BULL] = 0.0

        vix_axis = classify_vix_axis(vix_level)
        if vix_axis == "high_vol":
            scores[Regime.HIGH_VOL] += self.vix_bonus
        elif vix_axis == "low_vol":
            scores[Regime.LOW_VOL] += self.vix_bonus

        recession_prob = compute_recession_probability(yield_curve_slope)
        scores[Regime.RECESSION] = (
            recession_prob * (scores[Regime.BEAR] + scores[Regime.HIGH_VOL]) / 2.0
        )

        curve_steepening = yield_curve_slope - yield_curve_slope_prev
        sma_rising = sma_200 - sma_200_prev > 0
        near_reclaim = sma_200 > 0 and 0.95 <= price / sma_200 <= 1.05
        recovery_bonus = (
            scores[Regime.BULL] if (curve_steepening > 0 and sma_rising and near_reclaim) else 0.0
        )
        scores[Regime.RECOVERY] = recovery_bonus + max(0.0, curve_steepening) * 0.5

        total = sum(max(0.0, v) for v in scores.values())
        if total <= 0:
            uniform = 1.0 / len(ALL_REGIMES)
            return dict.fromkeys(ALL_REGIMES, uniform)
        return {regime: max(0.0, scores.get(regime, 0.0)) / total for regime in ALL_REGIMES}


class HysteresisGate:
    """Only flips the discrete label when a challenger beats the current
    label by `margin` for `min_persistence` consecutive updates - probs are
    still reported honestly every time; only the sticky label is smoothed."""

    def __init__(self, margin: float = 0.15, min_persistence: int = 3) -> None:
        self.margin = margin
        self.min_persistence = min_persistence
        self._current_label: Regime | None = None
        self._challenger: Regime | None = None
        self._challenger_streak = 0

    def update(self, probs: dict[Regime, float]) -> Regime:
        candidate = max(probs, key=lambda r: probs[r])

        if self._current_label is None:
            self._current_label = candidate
            self._reset_challenger()
            return self._current_label

        if candidate == self._current_label:
            self._reset_challenger()
            return self._current_label

        if probs[candidate] - probs[self._current_label] <= self.margin:
            self._reset_challenger()
            return self._current_label

        if candidate == self._challenger:
            self._challenger_streak += 1
        else:
            self._challenger = candidate
            self._challenger_streak = 1

        if self._challenger_streak >= self.min_persistence:
            self._current_label = candidate
            self._reset_challenger()

        return self._current_label

    def _reset_challenger(self) -> None:
        self._challenger = None
        self._challenger_streak = 0
